from __future__ import annotations


def _clear_llm_env(monkeypatch):
    for name in (
        "TPC_P2_LLM_BACKEND",
        "TPC_P2_LLM_FIXTURES",
        "TPC_P2_LLM_MODEL",
        "TPC_P2_LLM_BASE_URL",
        "TPC_P2_LLM_API_KEY_ENV",
        "TPC_P2_LLM_API_KEY",
        "TPC_P2_LLM_PARSE",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_MODEL",
        "OPENAI_API_KEY",
        "SGLANG_BASE_URL",
        "DEEPINFRA_BASE_URL",
        "DEEPINFRA_MODEL",
        "DEEPINFRA_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def _stub_client_builder(monkeypatch, runner):
    def build(cfg):
        client = type("FakeLLM", (), {})()
        client.backend = str(cfg.get("backend") or "none")
        client.config = dict(cfg)
        return client

    monkeypatch.setattr(runner.p2_llm, "build_llm_client", build)


def test_no_relevant_env_keeps_backend_none_and_parse_off(monkeypatch):
    import solve_phase2 as runner

    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "_read_local_config", lambda path=runner.DEFAULT_CONFIG_PATH: {})
    _stub_client_builder(monkeypatch, runner)

    client, flags = runner.resolve_llm_client_and_flags()

    assert client.backend == "none"
    assert client.backend_source == "none"
    assert flags.llm_backend == "none"
    assert flags.llm_parse is False


def test_autodetect_base_url_and_model_stays_parse_off(monkeypatch):
    import solve_phase2 as runner

    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "_read_local_config", lambda path=runner.DEFAULT_CONFIG_PATH: {})
    _stub_client_builder(monkeypatch, runner)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("TPC_P2_LLM_MODEL", "fake-model")

    client, flags = runner.resolve_llm_client_and_flags()

    assert client.backend == "openai"
    assert client.backend_source == "autodetect"
    assert client.config["model"] == "fake-model"
    assert client.config["api_key"] == "EMPTY"
    assert flags.llm_backend == "openai"
    assert flags.llm_parse is False


def test_explicit_backend_keeps_parse_off_by_default(monkeypatch):
    """TPC_P2_LLM_PARSE is an explicit recorded decision (roadmap W8), not an auto-enable: a
    configured backend alone must not turn the parse audit on, only an explicit override does
    (see test_operator_override_reaches_explicit_backend below)."""
    import solve_phase2 as runner

    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "_read_local_config", lambda path=runner.DEFAULT_CONFIG_PATH: {})
    _stub_client_builder(monkeypatch, runner)
    monkeypatch.setenv("TPC_P2_LLM_BACKEND", "deepinfra")

    client, flags = runner.resolve_llm_client_and_flags()

    assert client.backend == "deepinfra"
    assert client.backend_source == "env-explicit"
    assert flags.llm_backend == "deepinfra"
    assert flags.llm_parse is False


def test_operator_override_reaches_explicit_backend(monkeypatch):
    import solve_phase2 as runner

    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "_read_local_config", lambda path=runner.DEFAULT_CONFIG_PATH: {})
    _stub_client_builder(monkeypatch, runner)
    monkeypatch.setenv("TPC_P2_LLM_BACKEND", "deepinfra")
    monkeypatch.setenv("TPC_P2_LLM_PARSE", "1")

    client, flags = runner.resolve_llm_client_and_flags()

    assert client.backend == "deepinfra"
    assert flags.llm_parse is True


def test_autodetect_probe_failure_degrades_to_none(monkeypatch):
    import solve_phase2 as runner

    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "_read_local_config", lambda path=runner.DEFAULT_CONFIG_PATH: {})
    _stub_client_builder(monkeypatch, runner)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9999/v1")

    def boom(*args, **kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(runner, "_probe_openai_model_id", boom)

    client, flags = runner.resolve_llm_client_and_flags()

    assert client.backend == "none"
    assert client.backend_source == "none"
    assert flags.llm_backend == "none"
    assert flags.llm_parse is False


def test_autodetect_empty_model_list_degrades_to_none(monkeypatch):
    import solve_phase2 as runner

    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "_read_local_config", lambda path=runner.DEFAULT_CONFIG_PATH: {})
    _stub_client_builder(monkeypatch, runner)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setattr(runner, "_probe_openai_model_id", lambda *args, **kwargs: None)

    client, flags = runner.resolve_llm_client_and_flags()

    assert client.backend == "none"
    assert client.backend_source == "none"
    assert flags.llm_backend == "none"
    assert flags.llm_parse is False


def test_operator_override_keeps_autodetect_parse_on(monkeypatch):
    import solve_phase2 as runner

    _clear_llm_env(monkeypatch)
    monkeypatch.setattr(runner, "_read_local_config", lambda path=runner.DEFAULT_CONFIG_PATH: {})
    _stub_client_builder(monkeypatch, runner)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9999/v1")
    monkeypatch.setenv("TPC_P2_LLM_MODEL", "fake-model")
    monkeypatch.setenv("TPC_P2_LLM_PARSE", "1")

    client, flags = runner.resolve_llm_client_and_flags()

    assert client.backend == "openai"
    assert client.backend_source == "autodetect"
    assert flags.llm_backend == "openai"
    assert flags.llm_parse is True