"""Unit tests for the /v1/runs item decoding (PersistedRun projection)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.wend_agent.runs_routes import _decode_item  # noqa: E402


def _base_item() -> dict:
    return {
        "runId": {"S": "r-1"},
        "noteId": {"S": "n-1"},
        "createdAt": {"N": "1700000000000"},
        "response": {"S": "hello"},
        "sessionId": {"S": "sess"},
        "status": {"S": "done"},
        "durationMs": {"N": "1234"},
        "costUsd": {"N": "0.07"},
        "toolUses": {"SS": ["Bash", "Write"]},
        "repo": {"S": "org/repo"},
        "agentId": {"S": "agent-1"},
    }


def test_decode_new_fields_present():
    item = _base_item()
    tool_calls = [
        {"name": "Write", "input": {"file_path": "/a.py"}},
        {"name": "Bash"},  # input dropped during truncation upstream
    ]
    item["toolCallsJson"] = {"S": json.dumps(tool_calls)}
    item["links"] = {"SS": ["https://github.com/o/r/pull/5", "https://example.com"]}
    item["filesChanged"] = {"SS": ["/a.py"]}

    run = _decode_item(item)
    assert run["toolCalls"] == tool_calls
    assert set(run["links"]) == {"https://github.com/o/r/pull/5", "https://example.com"}
    assert run["filesChanged"] == ["/a.py"]
    # pre-existing shape untouched
    assert run["runId"] == "r-1"
    assert run["toolUses"] == ["Bash", "Write"]


def test_decode_old_rows_default_to_empty():
    """Rows persisted before this change have none of the new attributes."""
    run = _decode_item(_base_item())
    assert run["toolCalls"] == []
    assert run["links"] == []
    assert run["filesChanged"] == []


def test_decode_garbage_tool_calls_json_swallowed():
    item = _base_item()
    item["toolCallsJson"] = {"S": "{not valid json"}
    assert _decode_item(item)["toolCalls"] == []


def test_decode_non_list_tool_calls_json_defaults():
    item = _base_item()
    item["toolCallsJson"] = {"S": json.dumps({"name": "Bash"})}
    assert _decode_item(item)["toolCalls"] == []


def test_decode_empty_tool_calls_json_string():
    item = _base_item()
    item["toolCallsJson"] = {"S": ""}
    assert _decode_item(item)["toolCalls"] == []


def test_decode_filters_sentinel_from_string_sets():
    item = _base_item()
    item["toolUses"] = {"SS": ["__none__"]}
    item["links"] = {"SS": ["__none__"]}
    item["filesChanged"] = {"SS": ["__none__", "/real.py"]}
    run = _decode_item(item)
    assert run["toolUses"] == []
    assert run["links"] == []
    assert run["filesChanged"] == ["/real.py"]
