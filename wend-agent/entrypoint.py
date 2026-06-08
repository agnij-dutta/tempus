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
    cwd = WORKSPACE if os.listdir(WORKSPACE) else None
    sse(sink, "route", json.dumps({
        "name": REPO.split("/")[-1] if REPO else "cloud",
        "cwd": cwd or "/workspace",
        "source": "cloud",
        "confidence": 1.0,
    }))

    cmd = ["claude", "--output-format", "stream-json", "--print"]
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
        return
    clone_repo()
    sink = WSSink(WS_CALLBACK_URL, WS_CONNECTION_ID)
    try:
        stream_claude(WS_PROMPT, sink, WS_SESSION_ID or None)
    finally:
        sink._closed = True
        log("WS dispatch complete; exiting")


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
