"""Local smoke test for the wend-agent entrypoint.

Skips when claude or git aren't on PATH so CI without those binaries still
runs the rest of the Tempus test suite.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not installed")
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_dispatch_emits_sse_envelope(tmp_path):
    port = _free_port()
    env = os.environ.copy()
    env.update({
        "WEND_NO_TUNNEL": "1",
        "WEND_REPO": "",
        "WEND_LISTEN_PORT": str(port),
        "WEND_IDLE_TIMEOUT_SEC": "60",
    })
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "entrypoint.py")],
        env=env, stderr=subprocess.PIPE,
    )
    try:
        for _ in range(40):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("entrypoint never bound the port")

        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        conn.request("POST", "/v1/dispatch",
                     body=json.dumps({"prompt": "say hi"}),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.getheader("Content-Type", "").startswith("text/event-stream")

        # Accumulate into a rolling buffer: SSE markers can straddle read
        # boundaries. read1() returns whatever is available — read(1024)
        # would block for a full 1024 bytes that never arrive at the tail
        # of the stream (the server holds the connection open after done).
        buf = ""
        deadline = time.time() + 90
        while time.time() < deadline:
            chunk = resp.read1(1024).decode("utf-8", "replace")
            if not chunk:
                break  # stream closed
            buf += chunk
            if "event: done" in buf:
                break
        assert "event: route" in buf, "missing event: route"
        assert "event: done" in buf, "missing event: done"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
