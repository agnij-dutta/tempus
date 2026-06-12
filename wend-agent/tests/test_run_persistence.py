"""Unit tests for run-record capture/derivation/persistence in entrypoint.py.

Pure-Python tests: no claude CLI, no network. boto3 is monkeypatched for the
persist_run shape tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import entrypoint  # noqa: E402


def _sse_frame(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# ---------------------------------------------------------------------------
# _capture_frame: tool_result accumulation
# ---------------------------------------------------------------------------

def test_capture_tool_result_string_and_blocks():
    captured = {"assistant": "", "tool_uses": [], "tool_calls": [],
                "tool_result_text": "", "result": None, "session_id": ""}
    entrypoint._capture_frame(_sse_frame({
        "type": "user",
        "message": {"content": [
            {"type": "tool_result", "content": "plain string result "},
        ]},
    }), captured)
    entrypoint._capture_frame(_sse_frame({
        "type": "user",
        "message": {"content": [
            {"type": "tool_result", "content": [
                {"type": "text", "text": "block one "},
                {"type": "text", "text": "block two"},
                {"type": "image", "source": "ignored"},
            ]},
        ]},
    }), captured)
    assert captured["tool_result_text"] == "plain string result block one block two"


def test_capture_tool_result_buffer_bounded(monkeypatch):
    monkeypatch.setattr(entrypoint, "_RESULT_TEXT_CAP", 10)
    captured = {"tool_result_text": ""}
    entrypoint._capture_frame(_sse_frame({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": "abcdefgh"}]},
    }), captured)
    entrypoint._capture_frame(_sse_frame({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": "ijklmnop"}]},
    }), captured)
    assert captured["tool_result_text"] == "abcdefghij"  # capped at 10
    # further appends are dropped entirely
    entrypoint._capture_frame(_sse_frame({
        "type": "user",
        "message": {"content": [{"type": "tool_result", "content": "XYZ"}]},
    }), captured)
    assert len(captured["tool_result_text"]) == 10


def test_capture_still_collects_tool_calls():
    captured = {"assistant": "", "tool_uses": [], "tool_calls": [],
                "tool_result_text": "", "result": None, "session_id": ""}
    entrypoint._capture_frame(_sse_frame({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
            {"type": "text", "text": "done"},
        ]},
    }), captured)
    assert captured["tool_uses"] == ["Bash"]
    assert captured["tool_calls"] == [{"name": "Bash", "input": {"command": "ls"}}]
    assert captured["assistant"] == "done"


# ---------------------------------------------------------------------------
# extract_links
# ---------------------------------------------------------------------------

def test_links_punctuation_stripping_and_dedupe():
    text = ("See https://example.com/docs), then https://example.com/docs;\n"
            "and 'https://other.dev/page'.")
    links = entrypoint.extract_links(text, [], "")
    assert links == ["https://example.com/docs", "https://other.dev/page"]


def test_links_exclusions():
    text = ("https://localhost:3000/app https://127.0.0.1:8080/x "
            "https://0.0.0.0/y "
            "https://abc123.execute-api.ap-south-1.amazonaws.com/prod/v1 "
            "https://amazonaws.com/root "
            "https://keep.example.com/ok")
    links = entrypoint.extract_links(text, [], "")
    assert links == ["https://keep.example.com/ok"]


def test_links_pr_urls_ordered_first():
    text = ("First https://example.com/a then "
            "https://github.com/org/repo/pull/42 and "
            "https://github.com/org/repo/issues/7")
    links = entrypoint.extract_links(text, [], "")
    assert links[0] == "https://github.com/org/repo/pull/42"
    assert links[1:] == ["https://example.com/a",
                         "https://github.com/org/repo/issues/7"]


def test_links_from_tool_inputs_and_result_buffer():
    tool_calls = [
        {"name": "Bash", "input": {"command": "gh pr view https://github.com/o/r/pull/9"}},
        {"name": "WebFetch", "input": {"url": "https://docs.example.com/api"}},
        {"name": "Read", "input": {"file_path": "/tmp/x"}},  # no url/command
    ]
    links = entrypoint.extract_links("", tool_calls, "result says https://result.example.com/z")
    assert links == [
        "https://github.com/o/r/pull/9",
        "https://docs.example.com/api",
        "https://result.example.com/z",
    ]


def test_links_capped_at_50_pr_survives():
    text = " ".join(f"https://example.com/page/{i}" for i in range(60))
    text += " https://github.com/o/r/pull/1"
    links = entrypoint.extract_links(text, [], "")
    assert len(links) == 50
    assert links[0] == "https://github.com/o/r/pull/1"


# ---------------------------------------------------------------------------
# extract_files_changed
# ---------------------------------------------------------------------------

def test_files_changed_extraction_and_dedupe():
    tool_calls = [
        {"name": "Write", "input": {"file_path": "/a.py", "content": "x"}},
        {"name": "Edit", "input": {"file_path": "/a.py"}},          # dupe
        {"name": "MultiEdit", "input": {"path": "/b.py"}},
        {"name": "NotebookEdit", "input": {"notebook_path": "/c.ipynb"}},
        {"name": "Create", "input": {"file_path": "/d.txt"}},
        {"name": "Bash", "input": {"command": "rm /e"}},             # wrong tool
        {"name": "Write", "input": {"content": "no path"}},          # no path key
        {"name": "Write", "input": "not-a-dict"},
    ]
    assert entrypoint.extract_files_changed(tool_calls) == [
        "/a.py", "/b.py", "/c.ipynb", "/d.txt",
    ]


def test_files_changed_capped_at_200():
    tool_calls = [{"name": "Write", "input": {"file_path": f"/f{i}.py"}}
                  for i in range(250)]
    files = entrypoint.extract_files_changed(tool_calls)
    assert len(files) == 200
    assert files[0] == "/f0.py" and files[-1] == "/f199.py"


# ---------------------------------------------------------------------------
# serialize_tool_calls
# ---------------------------------------------------------------------------

def test_tool_calls_passthrough_when_small():
    calls = [{"name": "Bash", "input": {"command": "ls -la"}},
             {"name": "Read", "input": {"file_path": "/x"}}]
    out = entrypoint.serialize_tool_calls(calls, "short response")
    assert out == calls


def test_tool_calls_single_input_truncation_keeps_file_path():
    big = "z" * (20 * 1024)
    calls = [{"name": "Write",
              "input": {"file_path": "/very/important/path.py", "content": big}}]
    out = entrypoint.serialize_tool_calls(calls, "")
    assert out[0]["name"] == "Write"
    inp = out[0]["input"]
    assert inp["file_path"] == "/very/important/path.py"
    assert inp["content"].endswith("…[truncated]")
    assert len(inp["content"]) < len(big)
    assert entrypoint._json_size(inp) <= entrypoint._SINGLE_INPUT_CAP


def test_tool_calls_truncates_nested_edit_strings():
    big = "y" * (20 * 1024)
    calls = [{"name": "MultiEdit", "input": {
        "file_path": "/a.py",
        "edits": [{"old_string": big, "new_string": big}],
    }}]
    out = entrypoint.serialize_tool_calls(calls, "")
    edit = out[0]["input"]["edits"][0]
    assert edit["old_string"].endswith("…[truncated]")
    assert edit["new_string"].endswith("…[truncated]")
    assert out[0]["input"]["file_path"] == "/a.py"


def test_tool_calls_array_cap_drops_largest_inputs(monkeypatch):
    monkeypatch.setattr(entrypoint, "_TOOL_CALLS_JSON_CAP", 300)
    calls = [
        {"name": "Small", "input": {"k": "v"}},
        {"name": "Huge", "input": {"data": "x" * 500}},
        {"name": "Medium", "input": {"data": "y" * 100}},
    ]
    out = entrypoint.serialize_tool_calls(calls, "")
    names = [e["name"] for e in out]
    assert names == ["Small", "Huge", "Medium"]  # names always kept
    assert "input" not in out[1]                  # largest dropped first
    assert entrypoint._json_size(out) <= 300


def test_tool_calls_respects_combined_response_budget(monkeypatch):
    monkeypatch.setattr(entrypoint, "_COMBINED_CAP", 1000)
    calls = [{"name": f"T{i}", "input": {"data": "x" * 200}} for i in range(5)]
    response = "r" * 900  # leaves only 100 bytes for toolCalls
    out = entrypoint.serialize_tool_calls(calls, response)
    assert entrypoint._json_size(out) <= 100
    for e in out:
        assert "input" not in e


def test_tool_calls_unserializable_input_dropped_name_kept():
    calls = [{"name": "Weird", "input": {"obj": object()}}]
    out = entrypoint.serialize_tool_calls(calls, "")
    # default=str makes it serializable; name retained either way
    assert out[0]["name"] == "Weird"


# ---------------------------------------------------------------------------
# persist_run item shapes
# ---------------------------------------------------------------------------

class _FakeDdb:
    def __init__(self):
        self.put_items: list[dict] = []

    def put_item(self, TableName: str, Item: dict):
        self.put_items.append({"table": TableName, "item": Item})


@pytest.fixture
def fake_ddb(monkeypatch):
    import boto3
    fake = _FakeDdb()
    monkeypatch.setattr(boto3, "client", lambda *_a, **_k: fake)
    monkeypatch.setattr(entrypoint, "RUNS_TABLE", "wend-runs-test")
    monkeypatch.setattr(entrypoint, "NOTE_ID", "note-1")
    return fake


def test_persist_run_omits_empty_links_and_files(fake_ddb):
    captured = {"assistant": "no urls here", "tool_uses": [], "tool_calls": [],
                "tool_result_text": "", "result": None, "session_id": "s1"}
    entrypoint.persist_run(captured, 1000.0, 1001.0, ok=True)
    assert len(fake_ddb.put_items) == 1
    item = fake_ddb.put_items[0]["item"]
    assert "links" not in item
    assert "filesChanged" not in item
    assert item["toolCallsJson"] == {"S": "[]"}
    assert item["toolUses"] == {"SS": ["__none__"]}
    assert item["status"] == {"S": "done"}


def test_persist_run_writes_links_files_and_tool_calls(fake_ddb):
    captured = {
        "assistant": "Opened https://github.com/o/r/pull/3 for you",
        "tool_uses": ["Write", "Bash"],
        "tool_calls": [
            {"name": "Write", "input": {"file_path": "/a.py", "content": "hi"}},
            {"name": "Bash", "input": {"command": "echo https://example.com/x"}},
        ],
        "tool_result_text": "result link https://result.example.com/r",
        "result": {"total_cost_usd": 0.5},
        "session_id": "s2",
    }
    entrypoint.persist_run(captured, 1000.0, 1002.0, ok=True)
    item = fake_ddb.put_items[0]["item"]
    assert item["links"] == {"SS": [
        "https://github.com/o/r/pull/3",
        "https://example.com/x",
        "https://result.example.com/r",
    ]}
    assert item["filesChanged"] == {"SS": ["/a.py"]}
    parsed = json.loads(item["toolCallsJson"]["S"])
    assert parsed == captured["tool_calls"]
    assert item["costUsd"] == {"N": "0.5"}


def test_persist_run_noop_without_table(monkeypatch):
    monkeypatch.setattr(entrypoint, "RUNS_TABLE", "")
    # must not raise nor try to reach AWS
    entrypoint.persist_run({"assistant": "", "tool_uses": [], "tool_calls": []},
                           0.0, 1.0, ok=True)
