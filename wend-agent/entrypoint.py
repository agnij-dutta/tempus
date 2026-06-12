"""
wend-agent container entrypoint.

Clones a GitHub repo, brings cloudflared up, exposes a Mac-daemon-compatible
SSE endpoint, and self-terminates on idle. See
~/Desktop/Wend/Cloud Agent - Technical Design.md for the surrounding flow.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import IO

WORKSPACE = "/workspace"
ENV = os.environ
AGENT_ID = ENV.get("WEND_AGENT_ID", "dev-agent")
REPO = ENV.get("WEND_REPO", "")
REPO_REF = ENV.get("WEND_REPO_REF", "main")
GITHUB_TOKEN = ENV.get("WEND_GITHUB_INSTALL_TOKEN", "")
ANTHROPIC_API_KEY = ENV.get("WEND_ANTHROPIC_API_KEY", "")
IDLE_TIMEOUT = int(ENV.get("WEND_IDLE_TIMEOUT_SEC", "900"))
LISTEN_PORT = int(ENV.get("WEND_LISTEN_PORT", "8080"))
NO_TUNNEL = ENV.get("WEND_NO_TUNNEL", "").lower() in ("1", "true", "yes")
DDB_TABLE = ENV.get("WEND_DDB_TABLE", "")


def log(msg: str) -> None:
    sys.stderr.write(f"[wend-agent {time.strftime('%H:%M:%S')}] {msg}\n")
    sys.stderr.flush()


class IdleTimer:
    """Resets on every incoming request; trips the watchdog when exceeded."""
    def __init__(self, timeout_sec: int) -> None:
        self._timeout = timeout_sec
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def touch(self) -> None:
        with self._lock:
            self._last = time.monotonic()

    def expired(self) -> bool:
        with self._lock:
            return (time.monotonic() - self._last) > self._timeout

    def idle_seconds(self) -> int:
        with self._lock:
            return int(time.monotonic() - self._last)


IDLE = IdleTimer(IDLE_TIMEOUT)
TUNNEL_URL: str | None = None


def clone_repo() -> None:
    if not REPO:
        log("WEND_REPO not set; skipping clone (dev mode)")
        return
    if os.listdir(WORKSPACE):
        log(f"workspace not empty; clearing before clone")
        for entry in os.listdir(WORKSPACE):
            path = os.path.join(WORKSPACE, entry)
            shutil.rmtree(path, ignore_errors=True) if os.path.isdir(path) else os.remove(path)
    auth_url = (
        f"https://x-access-token:{GITHUB_TOKEN}@github.com/{REPO}.git"
        if GITHUB_TOKEN
        else f"https://github.com/{REPO}.git"
    )
    log(f"cloning {REPO}@{REPO_REF}")
    r = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", REPO_REF, auth_url, WORKSPACE],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        log(f"clone failed ({r.returncode}): {r.stderr}")
        sys.exit(2)


def start_cloudflared() -> None:
    global TUNNEL_URL
    if NO_TUNNEL:
        log("WEND_NO_TUNNEL set; skipping cloudflared")
        return

    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{LISTEN_PORT}"],
        stderr=subprocess.PIPE, text=True, bufsize=1,
    )

    def reader() -> None:
        global TUNNEL_URL
        assert proc.stderr is not None
        pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
        for line in proc.stderr:
            m = pattern.search(line)
            if m and TUNNEL_URL is None:
                TUNNEL_URL = m.group(0)
                log(f"tunnel up: {TUNNEL_URL}")
                _publish_tunnel_url(TUNNEL_URL)

    threading.Thread(target=reader, daemon=True).start()

    waited = 0
    while TUNNEL_URL is None and waited < 30:
        time.sleep(0.5)
        waited += 1
    if TUNNEL_URL is None:
        log("cloudflared did not surface a tunnel URL in 15s")


def _publish_tunnel_url(url: str) -> None:
    if not DDB_TABLE or not AGENT_ID:
        return
    try:
        import boto3
        ddb = boto3.client("dynamodb")
        ddb.update_item(
            TableName=DDB_TABLE,
            Key={"agentId": {"S": AGENT_ID}},
            UpdateExpression="SET tunnelUrl = :u, #s = :s",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":u": {"S": url}, ":s": {"S": "READY"}},
        )
    except Exception as exc:
        log(f"ddb publish failed: {exc}")


def sse(stream: IO[bytes], event: str | None, data: str) -> None:
    """Emit a single SSE frame matching the Mac daemon's wire format."""
    frame = ""
    if event:
        frame += f"event: {event}\n"
    frame += f"data: {data}\n\n"
    stream.write(frame.encode("utf-8"))
    stream.flush()


def stream_claude(prompt: str, sink: IO[bytes], session_id: str | None) -> None:
    """Spawn claude --output-format=stream-json --print and pipe JSONL to SSE."""
    # /workspace only exists in the container; guard so local dev/tests work.
    cwd = WORKSPACE if os.path.isdir(WORKSPACE) and os.listdir(WORKSPACE) else None
    sse(sink, "route", json.dumps({
        "name": REPO.split("/")[-1] if REPO else "cloud",
        "cwd": cwd or "/workspace",
        "source": "cloud",
        "confidence": 1.0,
    }))

    cmd = ["claude", "--output-format", "stream-json", "--print", "--verbose"]
    if session_id:
        cmd.extend(["--resume", session_id])
    env = os.environ.copy()
    if ANTHROPIC_API_KEY:
        env["ANTHROPIC_API_KEY"] = ANTHROPIC_API_KEY

    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=cwd, env=env, text=False,
    )
    assert proc.stdin and proc.stdout and proc.stderr

    proc.stdin.write(prompt.encode("utf-8"))
    proc.stdin.close()

    def pump_stderr() -> None:
        for line in proc.stderr:
            text = line.decode("utf-8", "replace").rstrip("\n")
            if text:
                sse(sink, "stderr", json.dumps(text))

    threading.Thread(target=pump_stderr, daemon=True).start()

    for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if not line:
            continue
        IDLE.touch()
        sse(sink, None, line)

    code = proc.wait()
    sse(sink, "done", json.dumps({"code": code}))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a, **_kw):
        pass

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self) -> None:
        if self.path.startswith("/health"):
            IDLE.touch()
            payload = json.dumps({
                "ok": True,
                "agentId": AGENT_ID,
                "tunnel": TUNNEL_URL,
                "idleSec": IDLE.idle_seconds(),
            }).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path.startswith("/v1/dispatch") or self.path.startswith("/run"):
            IDLE.touch()
            payload = self._read_json()
            prompt = (payload.get("prompt") or "").strip()
            session_id = payload.get("sessionId") or payload.get("session_id")
            if not prompt:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":"prompt required"}')
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                stream_claude(prompt, self.wfile, session_id)
            except BrokenPipeError:
                log("client disconnected mid-stream")
            return
        if self.path.startswith("/abort"):
            log("abort requested")
            self.send_response(202)
            self.end_headers()
            os.kill(os.getpid(), signal.SIGTERM)
            return
        self.send_response(404)
        self.end_headers()


def watchdog() -> None:
    while True:
        time.sleep(10)
        if IDLE.expired():
            log(f"idle {IDLE.idle_seconds()}s > {IDLE_TIMEOUT}s; exiting")
            os._exit(0)


MODE = ENV.get("WEND_MODE", "http")
WS_CONNECTION_ID = ENV.get("WEND_WS_CONNECTION_ID", "")
WS_CALLBACK_URL = ENV.get("WEND_WS_CALLBACK_URL", "")
WS_PROMPT = ENV.get("WEND_PROMPT", "")
WS_SESSION_ID = ENV.get("WEND_SESSION_ID", "")
PUSH_TOKEN = ENV.get("WEND_PUSH_TOKEN", "")
NOTE_TITLE = ENV.get("WEND_NOTE_TITLE", "")
NOTE_ID = ENV.get("WEND_NOTE_ID", "")
USER_ID = ENV.get("WEND_USER_ID", "")
RUNS_TABLE = ENV.get("WEND_RUNS_TABLE", "")


def fire_push(body: str, ok: bool) -> None:
    """Fire an Expo push to the user's device. Best-effort; failures are
    logged but don't impact the dispatch result. Short body — the
    notification panel only shows ~2 lines."""
    if not PUSH_TOKEN:
        return
    title = (NOTE_TITLE or REPO.split("/")[-1] or "Wend") if ok else "Wend run failed"
    payload = {
        "to": PUSH_TOKEN,
        "title": title[:60],
        "body": body[:120],
        "sound": None,
        "data": {"noteId": NOTE_ID or "", "ok": ok},
    }
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://exp.host/--/api/v2/push/send",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except Exception as exc:
        log(f"push fire failed: {exc}")


class WSSink:
    """SSE sink that posts each frame to an API Gateway WebSocket connection
    via ApiGatewayManagementApi.PostToConnection. Frames are buffered into
    full SSE-style records (event: + data:) and delivered as JSON envelopes
    so the mobile WS client can split events without re-parsing SSE."""

    def __init__(self, callback_url: str, connection_id: str) -> None:
        import boto3
        self._client = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=callback_url,
        )
        self._connection_id = connection_id
        self._closed = False

    def write(self, payload: bytes) -> None:
        if self._closed:
            return
        # Each call to write() corresponds to a full SSE frame as built by
        # the existing sse() helper. Split on the blank-line delimiter so
        # we send one event per WS message.
        text = payload.decode("utf-8", "replace")
        for chunk in text.split("\n\n"):
            chunk = chunk.strip()
            if not chunk:
                continue
            event_type: str | None = None
            data_parts: list[str] = []
            for line in chunk.splitlines():
                if line.startswith("event: "):
                    event_type = line[len("event: "):]
                elif line.startswith("data: "):
                    data_parts.append(line[len("data: "):])
                elif line.startswith("data:"):
                    data_parts.append(line[len("data:"):])
            data = "\n".join(data_parts)
            self._post({"event": event_type or "message", "data": data})

    def flush(self) -> None:
        pass

    def _post(self, body: dict) -> None:
        try:
            self._client.post_to_connection(
                ConnectionId=self._connection_id,
                Data=json.dumps(body).encode("utf-8"),
            )
        except Exception as exc:
            log(f"post_to_connection failed: {exc}; closing sink")
            self._closed = True


def run_ws_mode() -> None:
    log(f"WS mode: agent={AGENT_ID} repo={REPO}@{REPO_REF} connection={WS_CONNECTION_ID}")
    if not WS_PROMPT:
        log("WEND_PROMPT missing; nothing to run")
        fire_push("Wend couldn't find a prompt to run", ok=False)
        return
    clone_repo()
    sink = WSSink(WS_CALLBACK_URL, WS_CONNECTION_ID)
    captured: dict = {
        "assistant": "", "tool_uses": [], "tool_calls": [],
        "tool_result_text": "", "result": None, "session_id": "",
    }
    started_at = time.time()
    ok = True
    try:
        original_write = sink.write
        def capture_and_write(data: bytes) -> None:
            try:
                text = data.decode("utf-8", "replace")
                _capture_frame(text, captured)
            except Exception:
                pass
            original_write(data)
        sink.write = capture_and_write  # type: ignore[assignment]
        stream_claude(WS_PROMPT, sink, WS_SESSION_ID or None)
    except Exception as exc:
        ok = False
        log(f"WS dispatch raised: {exc}")
    finally:
        sink._closed = True
        ended_at = time.time()
        persist_run(captured, started_at, ended_at, ok=ok)
        body = (captured["assistant"][:120] if captured["assistant"]
                else ("Reply ready" if ok else "Run errored"))
        fire_push(body, ok=ok)
        log("WS dispatch complete; exiting")


# Bound on accumulated tool-result text. Used ONLY for link extraction;
# never persisted wholesale.
_RESULT_TEXT_CAP = 256 * 1024


def _append_result_text(captured: dict, text: str) -> None:
    """Accumulate tool-result text into a bounded buffer (drop beyond cap)."""
    if not text:
        return
    buf = captured.setdefault("tool_result_text", "")
    remaining = _RESULT_TEXT_CAP - len(buf)
    if remaining <= 0:
        return
    captured["tool_result_text"] = buf + text[:remaining]


def _capture_frame(text: str, captured: dict) -> None:
    """Pull useful pieces out of each SSE frame as it streams so we can
    persist a complete record at the end."""
    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        data_parts: list[str] = []
        for line in chunk.splitlines():
            if line.startswith("data: "):
                data_parts.append(line[len("data: "):])
            elif line.startswith("data:"):
                data_parts.append(line[len("data:"):])
        data = "\n".join(data_parts).strip()
        if not data:
            continue
        try:
            frame = json.loads(data)
        except Exception:
            continue
        ftype = frame.get("type")
        if ftype == "assistant" and isinstance(frame.get("message"), dict):
            for block in frame["message"].get("content", []) or []:
                if isinstance(block, dict):
                    if block.get("type") == "text" and isinstance(block.get("text"), str):
                        captured["assistant"] += block["text"]
                    elif block.get("type") == "tool_use" and isinstance(block.get("name"), str):
                        captured["tool_uses"].append(block["name"])
                        captured["tool_calls"].append({
                            "name": block["name"],
                            "input": block.get("input"),
                        })
        elif ftype == "user" and isinstance(frame.get("message"), dict):
            # stream-json surfaces tool results as user frames whose content
            # blocks are {"type": "tool_result", "content": str | [{type, text}]}.
            for block in frame["message"].get("content", []) or []:
                if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                    continue
                content = block.get("content")
                if isinstance(content, str):
                    _append_result_text(captured, content)
                elif isinstance(content, list):
                    for part in content:
                        if (isinstance(part, dict) and part.get("type") == "text"
                                and isinstance(part.get("text"), str)):
                            _append_result_text(captured, part["text"])
        elif ftype == "result":
            captured["result"] = frame
            sid = frame.get("session_id")
            if isinstance(sid, str):
                captured["session_id"] = sid


# --- run-record derivation -------------------------------------------------

_URL_RE = re.compile(r"https://[^\s<>\"'`]+")
_GITHUB_PR_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+/pull/\d+")
_LINK_TRAILING_PUNCT = ")>.,;'\""
_MAX_LINKS = 50

_FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Create"}
_PATH_KEYS = ("file_path", "path", "notebook_path")
_MAX_FILES_CHANGED = 200

_SINGLE_INPUT_CAP = 16 * 1024       # per-tool-call serialized input cap
_TOOL_CALLS_JSON_CAP = 250 * 1024   # whole toolCalls array cap
_COMBINED_CAP = 380 * 1024          # response + toolCalls budget (400 KB item limit)


def _link_excluded(url: str) -> bool:
    """Drop localhost/loopback and AWS infra URLs."""
    try:
        host = url.split("//", 1)[1].split("/", 1)[0].split("@")[-1]
        host = host.split(":", 1)[0].lower()
    except Exception:
        return True
    if host in ("localhost", "127.0.0.1", "0.0.0.0"):
        return True
    if host == "amazonaws.com" or host.endswith(".amazonaws.com"):
        return True
    return False


def extract_links(assistant_text: str, tool_calls: list, result_text: str) -> list[str]:
    """All https URLs from assistant text, tool-call command/url inputs, and
    the bounded tool-result buffer. Deduped in first-seen order, infra URLs
    excluded, GitHub PR URLs first, capped at _MAX_LINKS."""
    parts = [assistant_text or ""]
    for call in tool_calls or []:
        inp = call.get("input") if isinstance(call, dict) else None
        if isinstance(inp, dict):
            for key in ("command", "url"):
                if key in inp:
                    val = inp[key]
                    if isinstance(val, str):
                        parts.append(val)
                    else:
                        try:
                            parts.append(json.dumps(val, default=str))
                        except Exception:
                            pass
    parts.append(result_text or "")

    ordered: list[str] = []
    seen: set[str] = set()
    for m in _URL_RE.finditer("\n".join(parts)):
        url = m.group(0).rstrip(_LINK_TRAILING_PUNCT)
        if not url or url in seen:
            continue
        if _link_excluded(url):
            continue
        seen.add(url)
        ordered.append(url)

    prs = [u for u in ordered if _GITHUB_PR_RE.match(u)]
    rest = [u for u in ordered if not _GITHUB_PR_RE.match(u)]
    return (prs + rest)[:_MAX_LINKS]


def extract_files_changed(tool_calls: list) -> list[str]:
    """file_path/path/notebook_path of write-shaped tool calls, deduped in
    order, capped at _MAX_FILES_CHANGED."""
    out: list[str] = []
    seen: set[str] = set()
    for call in tool_calls or []:
        if not isinstance(call, dict) or call.get("name") not in _FILE_TOOLS:
            continue
        inp = call.get("input")
        if not isinstance(inp, dict):
            continue
        path = next(
            (inp[k] for k in _PATH_KEYS if isinstance(inp.get(k), str) and inp[k]),
            None,
        )
        if path and path not in seen:
            seen.add(path)
            out.append(path)
            if len(out) >= _MAX_FILES_CHANGED:
                break
    return out


def _truncate_strings(value, limit: int):
    """Recursively truncate string values, keeping path-identifying keys
    intact, marking truncations with a suffix."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _PATH_KEYS and isinstance(v, str):
                out[k] = v
            else:
                out[k] = _truncate_strings(v, limit)
        return out
    if isinstance(value, list):
        return [_truncate_strings(v, limit) for v in value]
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…[truncated]"
    return value


def _json_size(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def serialize_tool_calls(tool_calls: list, response_text: str) -> list[dict]:
    """Make captured tool calls persistable as {name, input?} entries.

    Per call: JSON-round-trip the input; if a single serialized input exceeds
    _SINGLE_INPUT_CAP, truncate its string fields (paths kept intact). The
    whole array must fit _TOOL_CALLS_JSON_CAP, and response + array must fit
    _COMBINED_CAP — inputs are dropped from the largest entries (names kept)
    until it fits; entries are dropped from the end as a last resort."""
    entries: list[dict] = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        if not isinstance(name, str) or not name:
            continue
        inp = call.get("input")
        try:
            inp = json.loads(json.dumps(inp, ensure_ascii=False, default=str))
        except Exception:
            inp = None
        if inp is not None and _json_size(inp) > _SINGLE_INPUT_CAP:
            for limit in (1024, 128):
                inp = _truncate_strings(inp, limit)
                if _json_size(inp) <= _SINGLE_INPUT_CAP:
                    break
            else:
                inp = None  # pathological (huge paths/many fields): keep name only
        entry: dict = {"name": name}
        if inp is not None:
            entry["input"] = inp
        entries.append(entry)

    response_bytes = len((response_text or "").encode("utf-8"))
    budget = min(_TOOL_CALLS_JSON_CAP, max(_COMBINED_CAP - response_bytes, 2))

    while entries and _json_size(entries) > budget:
        with_input = [e for e in entries if "input" in e]
        if not with_input:
            entries.pop()  # all inputs already dropped; shed entries from the end
            continue
        largest = max(with_input, key=lambda e: _json_size(e["input"]))
        del largest["input"]
    return entries


def persist_run(captured: dict, started_at: float, ended_at: float, ok: bool) -> None:
    """Write a one-shot wend-runs row so the phone can catch up to a
    run that finished while it was offline."""
    if not RUNS_TABLE or not NOTE_ID:
        return
    try:
        import boto3, uuid
        ddb = boto3.client("dynamodb")
        result = captured.get("result") or {}
        assistant_text = captured.get("assistant") or ""
        raw_tool_calls = captured.get("tool_calls") or []
        links = extract_links(
            assistant_text, raw_tool_calls, captured.get("tool_result_text") or "")
        files_changed = extract_files_changed(raw_tool_calls)
        tool_calls = serialize_tool_calls(raw_tool_calls, assistant_text)
        item = {
            "noteId": {"S": NOTE_ID},
            "createdAt": {"N": str(int(started_at * 1000))},
            "runId": {"S": str(uuid.uuid4())},
            "userId": {"S": USER_ID or "unknown"},
            "agentId": {"S": AGENT_ID or "unknown"},
            "repo": {"S": REPO or ""},
            "response": {"S": captured.get("assistant") or ""},
            "sessionId": {"S": captured.get("session_id") or ""},
            "status": {"S": "done" if ok else "error"},
            "durationMs": {"N": str(int((ended_at - started_at) * 1000))},
            "costUsd": {"N": str(float(result.get("total_cost_usd") or 0.0))},
            "toolUses": {"SS": list(set(captured["tool_uses"])) if captured["tool_uses"] else ["__none__"]},
            "toolCallsJson": {"S": json.dumps(tool_calls, ensure_ascii=False)},
            "expiresAt": {"N": str(int(ended_at) + 86400 * 30)},  # 30-day retention
        }
        # DynamoDB string sets can't be empty — omit the attribute entirely.
        if links:
            item["links"] = {"SS": links}
        if files_changed:
            item["filesChanged"] = {"SS": files_changed}
        ddb.put_item(TableName=RUNS_TABLE, Item=item)
        log(f"wend-runs persisted noteId={NOTE_ID}")
    except Exception as exc:
        log(f"persist_run failed: {exc}")




def main() -> None:
    if MODE == "ws":
        run_ws_mode()
        return
    log(f"booting agentId={AGENT_ID} repo={REPO}@{REPO_REF} port={LISTEN_PORT}")
    clone_repo()
    start_cloudflared()
    threading.Thread(target=watchdog, daemon=True).start()

    server = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    log(f"listening on 127.0.0.1:{LISTEN_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
