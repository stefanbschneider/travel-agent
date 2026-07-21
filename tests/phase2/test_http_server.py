"""Smoke tests for the stdlib HTTP harness entry point (agent_env/http_server.py).

Spins up a real ``ThreadingHTTPServer`` on an OS-assigned loopback port and issues real HTTP
requests, so this covers the actual wire path (routing, headers, JSON encoding) organizers/harnesses
would hit -- previously untested. Adapter-level oracle-hiding/tool-allowlisting already has unit
coverage in ``tests/phase2/test_agent_env_security.py``.
"""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from agent_env.http_server import Handler


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd
    finally:
        httpd.shutdown()
        thread.join(timeout=5)
        httpd.server_close()


def _get(server, path):
    conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())
    finally:
        conn.close()


def _post(server, path, payload):
    conn = HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
    try:
        body = json.dumps(payload).encode("utf-8")
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read())
    finally:
        conn.close()


def test_health_endpoint(server):
    status, payload = _get(server, "/health")
    assert status == 200
    assert payload == {"success": True, "service": "chinatravel-agent-env"}


def test_tools_endpoint_returns_catalog(server):
    status, payload = _get(server, "/tools")
    assert status == 200
    assert payload["success"] is True
    names = {t["name"] for t in payload["tools"]}
    assert "china_travel_load_query" in names


def test_splits_endpoint(server):
    status, payload = _get(server, "/splits")
    assert status == 200
    assert payload["success"] is True
    assert "tpc_phase2_val" in payload["splits"]


def test_unknown_get_path_is_404(server):
    status, payload = _get(server, "/nope")
    assert status == 404
    assert payload["success"] is False


def test_call_endpoint_list_splits(server):
    status, payload = _post(server, "/call", {"tool": "china_travel_list_splits", "arguments": {}})
    assert status == 200
    assert payload["success"] is True
    assert "tpc_phase2_val" in payload["splits"]


def test_call_endpoint_rejects_oracle_override_over_the_wire(server):
    """The oracle-hiding contract must hold through the actual HTTP call path."""
    status, payload = _post(server, "/call", {
        "tool": "china_travel_load_query",
        "arguments": {"split": "tpc_phase2_val", "uid": "does-not-matter", "oracle_translation": True},
    })
    assert status == 200
    assert payload["success"] is False
    assert "oracle_translation" in payload["error"]


def test_unknown_post_path_is_404(server):
    status, payload = _post(server, "/nope", {})
    assert status == 404
    assert payload["success"] is False
