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
            "cache": False,
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


def test_infradeep_backend_builds_openai_compatible_request(monkeypatch):
    captured = {}

    class FakeMessage:
        content = "infradeep-answer"

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
            "backend": "infradeep",
            "model": "qwen3.6-27b",
            "base_url": "https://api.infradeep.example/v1",
            "api_key": "idp-key",
            "cache": False,
        }
    )
    out = client.complete("hi")
    assert out == "infradeep-answer"
    assert client.backend == "infradeep"
    assert captured["model"] == "qwen3.6-27b"
    assert captured["client_kwargs"]["base_url"] == "https://api.infradeep.example/v1"


def test_load_local_env_parses_export_lines(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "export INFRADEEP_API_KEY=abc123\n"
        "TPC_P2_LLM_MODEL='Qwen/Qwen3.6-27B-Instruct'\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("INFRADEEP_API_KEY", raising=False)
    monkeypatch.delenv("TPC_P2_LLM_MODEL", raising=False)

    loaded = lc.load_local_env(str(env_file))
    assert loaded["INFRADEEP_API_KEY"] == "abc123"
    assert loaded["TPC_P2_LLM_MODEL"] == "Qwen/Qwen3.6-27B-Instruct"


def test_load_local_env_does_not_override_existing_by_default(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text('export INFRADEEP_API_KEY="file-value"\n', encoding="utf-8")
    monkeypatch.setenv("INFRADEEP_API_KEY", "existing-value")

    loaded = lc.load_local_env(str(env_file))
    assert loaded == {}
    assert lc.os.environ["INFRADEEP_API_KEY"] == "existing-value"


def test_infradeep_backend_defaults_base_url(monkeypatch):
    captured = {}

    class FakeMessage:
        content = "ok"

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
    monkeypatch.setenv("INFRADEEP_API_KEY", "idp-key")

    client = lc.build_llm_client({"backend": "infradeep", "model": "qwen3.6-27b", "cache": False})
    assert client.backend == "infradeep"
    assert captured["client_kwargs"]["base_url"] == "https://api.deepinfra.com/v1/openai"


def test_infradeep_backend_default_model_is_a_real_deepinfra_id(monkeypatch):
    """Regression test: the previous default ("qwen3.6-27b", no org prefix, lowercase) 404'd on
    every real DeepInfra call ("model qwen3.6-27b does not exist"), silently swallowed by
    parse_to_ir's fallback-on-exception -- every infradeep run without an explicit
    TPC_P2_LLM_MODEL/INFRADEEP_MODEL override never actually called the LLM. DeepInfra model IDs
    are case-sensitive "Org/Name"; verified "Qwen/Qwen3.6-27B" live 2026-07-11."""
    captured = {}

    class FakeMessage:
        content = "ok"

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
            self.chat = FakeChat()

    monkeypatch.setattr(lc, "_load_openai_class", lambda: FakeOpenAI)
    monkeypatch.setenv("INFRADEEP_API_KEY", "idp-key")
    monkeypatch.delenv("TPC_P2_LLM_MODEL", raising=False)
    monkeypatch.delenv("INFRADEEP_MODEL", raising=False)

    client = lc.build_llm_client({"backend": "infradeep", "cache": False})
    client.complete("hi")
    assert captured["model"] == lc.DEFAULT_INFRADEEP_MODEL == "Qwen/Qwen3.6-27B"


# --- CachingLLMClient --------------------------------------------------------


class _CountingClient(lc.LLMClient):
    backend = "openai"
    model = "test-model"

    def __init__(self, response="live-answer"):
        self.response = response
        self.calls = 0

    def complete(self, prompt, *, system=None, cache_key=None):
        self.calls += 1
        return self.response


def test_caching_client_cold_call_hits_inner_and_persists(tmp_path):
    inner = _CountingClient()
    client = lc.CachingLLMClient(inner, tmp_path)
    out = client.complete("prompt", cache_key="k1")
    assert out == "live-answer"
    assert inner.calls == 1
    cached = list((tmp_path / "test-model").glob("*.json"))
    assert len(cached) == 1


def test_caching_client_warm_call_skips_inner(tmp_path, no_network):
    inner = _CountingClient()
    client = lc.CachingLLMClient(inner, tmp_path)
    client.complete("prompt", cache_key="k1")
    out = client.complete("prompt", cache_key="k1")
    assert out == "live-answer"
    assert inner.calls == 1  # second call was a cache hit, no second inner.complete


def test_caching_client_different_keys_do_not_collide(tmp_path):
    inner = _CountingClient()
    client = lc.CachingLLMClient(inner, tmp_path)
    client.complete("prompt a", cache_key="k1")
    client.complete("prompt b", cache_key="k2")
    assert inner.calls == 2


def test_caching_client_falls_back_to_prompt_hash_without_cache_key(tmp_path):
    inner = _CountingClient()
    client = lc.CachingLLMClient(inner, tmp_path)
    client.complete("same prompt")
    client.complete("same prompt")
    assert inner.calls == 1


def test_caching_client_reports_inner_backend(tmp_path):
    inner = _CountingClient()
    client = lc.CachingLLMClient(inner, tmp_path)
    assert client.backend == "openai"


def test_build_llm_client_wraps_openai_backend_in_cache_by_default(monkeypatch, tmp_path):
    class FakeMessage:
        content = "answer"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeCompletion()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setattr(lc, "_load_openai_class", lambda: FakeOpenAI)
    client = lc.build_llm_client(
        {"backend": "openai", "model": "m", "api_key": "k", "cache_dir": str(tmp_path)}
    )
    assert isinstance(client, lc.CachingLLMClient)
    assert client.backend == "openai"


def test_build_llm_client_cache_env_var_disables_wrapping(monkeypatch, tmp_path):
    class FakeMessage:
        content = "answer"

    class FakeChoice:
        message = FakeMessage()

    class FakeCompletion:
        choices = [FakeChoice()]

    class FakeCompletions:
        def create(self, **kwargs):
            return FakeCompletion()

    class FakeChat:
        completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = FakeChat()

    monkeypatch.setattr(lc, "_load_openai_class", lambda: FakeOpenAI)
    monkeypatch.setenv("TPC_P2_LLM_CACHE", "0")
    client = lc.build_llm_client({"backend": "openai", "model": "m", "api_key": "k"})
    assert isinstance(client, lc.OpenAILLMClient)
    assert not isinstance(client, lc.CachingLLMClient)
