"""Tests for the Phase 2 LLM client abstraction (Task 3).

The deterministic path must never hit the network. Backends:
- none: default; refuses to produce output (must not be called on the default path).
- fixture: replays cached responses from disk (zero network); used for dev + tests.
- openai: OpenAI-compatible endpoint; here only the request construction is exercised, with the
  HTTP layer mocked so no live network call happens.
"""

from __future__ import annotations

import json

import pytest

from chinatravel.agent.phase2 import llm_client as lc


def test_default_backend_is_none():
    client = lc.build_llm_client()
    assert client.backend == "none"


def test_none_backend_does_not_call_network(no_network):
    client = lc.build_llm_client({"backend": "none"})
    # Building and inspecting must not touch the network.
    assert client.backend == "none"
    # Calling the none backend is a programming error (the default path should never call it).
    with pytest.raises(lc.LLMDisabledError):
        client.complete("hello")


def test_fixture_backend_returns_cached_response(tmp_path, no_network):
    fixtures = tmp_path / "fix"
    fixtures.mkdir()
    (fixtures / "abc123.json").write_text(
        json.dumps({"response": "cached-answer"}), encoding="utf-8"
    )
    client = lc.build_llm_client({"backend": "fixture", "fixtures_dir": str(fixtures)})
    assert client.complete("some prompt", cache_key="abc123") == "cached-answer"


def test_fixture_backend_missing_key_raises_clear_error(tmp_path, no_network):
    fixtures = tmp_path / "fix"
    fixtures.mkdir()
    client = lc.build_llm_client({"backend": "fixture", "fixtures_dir": str(fixtures)})
    with pytest.raises(lc.FixtureMissingError):
        client.complete("prompt", cache_key="does-not-exist")


def test_openai_backend_builds_request_without_network(monkeypatch):
    captured = {}

    class FakeMessage:
        content = "openai-answer"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeCompletion()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.chat = FakeChat()

    monkeypatch.setattr(lc, "_load_openai_class", lambda: FakeOpenAI)

    client = lc.build_llm_client(
        {
            "backend": "openai",
            "model": "qwen3.6-27b",
            "base_url": "http://localhost:8000/v1",
            "api_key": "test-key",
        }
    )
    out = client.complete("hi", system="be brief")
    assert out == "openai-answer"
    assert captured["model"] == "qwen3.6-27b"
    # system + user messages assembled
    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user"]
    assert captured["client_kwargs"]["base_url"] == "http://localhost:8000/v1"


def test_unknown_backend_raises():
    with pytest.raises(ValueError):
        lc.build_llm_client({"backend": "nonsense"})
