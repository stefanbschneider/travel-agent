"""Smoke tests for the stdio MCP-style harness entry point (agent_env/mcp_stdio.py).

The adapter-level oracle-hiding and tool-allowlisting invariants already have unit coverage
(``tests/phase2/test_agent_env_security.py``), but the actual wire protocol organizers/harnesses
speak -- JSON-RPC ``initialize``/``tools/list``/``tools/call``/``ping`` over stdio -- had zero
coverage. These tests exercise ``_handle`` directly (the pure per-message dispatcher ``main()``
loops over), so they cover the real request/response shape without spawning a subprocess.
"""

from __future__ import annotations

import json

from agent_env.mcp_stdio import _handle


def test_initialize_reports_server_info():
    resp = _handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["id"] == 1
    assert resp["result"]["serverInfo"]["name"] == "chinatravel-agent-env"
    assert "tools" in resp["result"]["capabilities"]


def test_ping_responds_empty_result():
    resp = _handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    assert resp == {"jsonrpc": "2.0", "id": 2, "result": {}}


def test_tools_list_returns_non_empty_catalog():
    resp = _handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})
    tools = resp["result"]["tools"]
    assert isinstance(tools, list) and len(tools) > 0
    names = {t["name"] for t in tools}
    assert "china_travel_load_query" in names
    assert "china_travel_world_command" in names


def test_tools_call_list_splits_succeeds():
    resp = _handle({
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "china_travel_list_splits", "arguments": {}},
    })
    assert resp["result"]["isError"] is False
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["success"] is True
    assert "tpc_phase2_val" in payload["splits"]


def test_tools_call_rejects_oracle_override_over_the_wire():
    """The oracle-hiding contract must hold through the actual JSON-RPC call path, not just the
    adapter object directly."""
    resp = _handle({
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {
            "name": "china_travel_load_query",
            "arguments": {"split": "tpc_phase2_val", "uid": "does-not-matter",
                          "oracle_translation": True},
        },
    })
    assert resp["result"]["isError"] is True
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert payload["success"] is False
    assert "oracle_translation" in payload["error"]


def test_unknown_method_returns_json_rpc_error():
    resp = _handle({"jsonrpc": "2.0", "id": 6, "method": "bogus/method"})
    assert resp["error"]["code"] == -32601


def test_notification_without_id_produces_no_response():
    assert _handle({"jsonrpc": "2.0", "method": "ping"}) is None
