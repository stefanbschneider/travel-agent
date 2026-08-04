"""LLM client abstraction for the Phase 2 harness.

Backends, selected by config / the ``TPC_P2_LLM_BACKEND`` env var:

- ``none``    : default. No LLM. Calling ``complete`` raises ``LLMDisabledError`` — the
                deterministic path must never call it. Guarantees zero network locally.
- ``fixture`` : replays cached responses from a fixtures directory, keyed by ``cache_key``
                (or a hash of the prompt). Zero network. For dev (hand-produced parses) + tests.
- ``openai``  : OpenAI-compatible endpoint (SGLang, OpenRouter, local Qwen, ...). Reuses the
                ``openai`` package. OpenRouter is just a ``base_url`` + ``api_key`` preset. This is
                the backend for the organizer-confirmed evaluation endpoint (SGLang serving
                ``Qwen3.6-27B`` at ``http://127.0.0.1:30000/v1``, 2026-08-04 organizer email; see
                ``agent_env/config.phase2.example.toml``) -- unused by the packaged submission,
                whose library-default backend stays ``none``.
- ``deepinfra``: DeepInfra preset over the same OpenAI-compatible wire protocol.

Both network backends default Qwen3-family "thinking mode" off when the configured model name looks
like Qwen3 (see ``_thinking_disabled_extra_body`` / ``_looks_like_qwen3_model``): with it on, a
chain-of-thought precedes every answer at roughly 10x the latency, which the 30s per-call timeout is
not sized for. The check is model-gated, not backend-gated, because ``openai`` is also the generic
escape hatch for non-Qwen providers (OpenRouter, plain OpenAI, ...) that would reject the
SGLang/vLLM-specific ``chat_template_kwargs`` field outright.

Config keys (dict or ``[phase2.llm]`` in agent_env/config.toml):
    backend, model, base_url, api_key, api_key_env, fixtures_dir, temperature, max_tokens.

Design rule: nothing here is constructed or called on the default deterministic path.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


class LLMError(Exception):
    """Base class for LLM client errors."""


class LLMDisabledError(LLMError):
    """Raised when the ``none`` backend is asked to produce output."""


class FixtureMissingError(LLMError):
    """Raised when a fixture response is not found on disk."""


DEFAULT_BACKEND = "none"
# Bounds any single network/LLM call. Without this, a hung request (a 116s outlier was observed
# live against DeepInfra) can consume most of a query's budget before the solver ever starts --
# the SDK-level timeout is the actual bound; the orchestrator's parse-stage deadline check (below)
# additionally skips the call entirely when it can't possibly finish in the remaining slice.
DEFAULT_LLM_TIMEOUT_SEC = 30.0
DEFAULT_DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
# DeepInfra model IDs are case-sensitive "Org/Name" (verified live 2026-07-11); the previous
# lowercase no-prefix default ("qwen3.6-27b") 404'd on every real call and was masked by
# parse_to_ir's silent fallback-on-exception -- every deepinfra run without an explicit
# TPC_P2_LLM_MODEL/DEEPINFRA_MODEL override silently never called the LLM at all.
DEFAULT_DEEPINFRA_MODEL = "Qwen/Qwen3.6-27B"


def _find_project_root(start: Path | None = None) -> Path | None:
    here = (start or Path(__file__).resolve()).parent
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return None


def _parse_env_line(line: str) -> tuple[str, str] | None:
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    if text.startswith("export "):
        text = text[len("export "):].strip()
    if "=" not in text:
        return None
    key, value = text.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return key, value


def load_local_env(env_file: str | os.PathLike | None = None, *, overwrite: bool = False) -> dict[str, str]:
    """Load local .env entries into os.environ.

    - If ``env_file`` is omitted, reads ``<project_root>/.env`` when available.
    - By default does not overwrite already-set environment variables.
    - Returns the key/value pairs loaded into the process environment.
    """
    path: Path | None
    if env_file is None:
        root = _find_project_root()
        path = (root / ".env") if root else None
    else:
        path = Path(env_file)

    if path is None or not path.exists():
        return {}

    loaded: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if not parsed:
            continue
        key, value = parsed
        if key in os.environ and not overwrite:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded


def _hash_prompt(prompt: str, system: str | None) -> str:
    h = hashlib.sha256()
    if system:
        h.update(system.encode("utf-8"))
        h.update(b"\x00")
    h.update(prompt.encode("utf-8"))
    return h.hexdigest()[:16]


class LLMClient:
    """Base client. Subclasses implement ``complete``."""

    backend = "base"

    def complete(self, prompt: str, *, system: str | None = None, cache_key: str | None = None) -> str:
        raise NotImplementedError


class NoneLLMClient(LLMClient):
    backend = "none"

    def complete(self, prompt: str, *, system: str | None = None, cache_key: str | None = None) -> str:
        raise LLMDisabledError(
            "LLM backend is 'none'; the deterministic path must not call the LLM. "
            "Set TPC_P2_LLM_BACKEND=fixture|openai|deepinfra (and the relevant feature flag) to enable it."
        )


class FixtureLLMClient(LLMClient):
    backend = "fixture"

    def __init__(self, fixtures_dir: str | os.PathLike):
        self.fixtures_dir = Path(fixtures_dir)

    def complete(self, prompt: str, *, system: str | None = None, cache_key: str | None = None) -> str:
        key = cache_key or _hash_prompt(prompt, system)
        path = self.fixtures_dir / f"{key}.json"
        if not path.exists():
            raise FixtureMissingError(
                f"No fixture for key {key!r} at {path}. Record it (e.g. via a Kiro/Copilot session) "
                f"or run with backend 'openai'."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "response" in data:
            return str(data["response"])
        if isinstance(data, str):
            return data
        raise FixtureMissingError(f"Fixture {path} must be a string or an object with a 'response' key.")


class CachingLLMClient(LLMClient):
    """Wraps another client with an on-disk response cache, keyed by ``cache_key`` (falling back
    to a hash of prompt+system when the caller doesn't supply one).

    Warm evals become free and byte-deterministic: a repeat run over the same uids issues zero
    network calls and returns the exact same response, which both keeps DeepInfra usage
    economical and satisfies the organizers' 5-run-averaging stability concern (temperature is
    already 0, so a cached response is what a live call would return anyway).
    """

    def __init__(self, inner: LLMClient, cache_dir: str | os.PathLike):
        self.inner = inner
        self.backend = inner.backend
        self.timeout = getattr(inner, "timeout", None)
        self.cache_dir = Path(cache_dir) / getattr(inner, "model", "unknown")

    def _cache_path(self, prompt: str, system: str | None, cache_key: str | None) -> Path:
        key = cache_key or _hash_prompt(prompt, system)
        # cache_key values (e.g. "parse_<uid>_<hash>") are already filesystem-safe; hash anyway
        # to tolerate arbitrary caller-supplied keys.
        safe_key = key if key.replace("_", "").replace("-", "").isalnum() else _hash_prompt(key, None)
        return self.cache_dir / f"{safe_key}.json"

    def complete(self, prompt: str, *, system: str | None = None, cache_key: str | None = None) -> str:
        path = self._cache_path(prompt, system, cache_key)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return str(data["response"])

        response = self.inner.complete(prompt, system=system, cache_key=cache_key)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"cache_key": cache_key, "response": response}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return response


def _load_openai_class():  # pragma: no cover - trivial import indirection (mocked in tests)
    from openai import OpenAI

    return OpenAI


class OpenAILLMClient(LLMClient):
    backend = "openai"

    def __init__(self, *, model: str, base_url: str | None = None, api_key: str | None = None,
                 temperature: float = 0.0, max_tokens: int | None = None,
                 extra_body: dict | None = None, timeout: float = DEFAULT_LLM_TIMEOUT_SEC):
        if not model:
            raise ValueError("openai backend requires a 'model'.")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_body = extra_body
        self.timeout = timeout
        openai_cls = _load_openai_class()
        client_kwargs: dict[str, Any] = {"timeout": timeout, "max_retries": 0}
        if base_url:
            client_kwargs["base_url"] = base_url
        if api_key:
            client_kwargs["api_key"] = api_key
        self._client = openai_cls(**client_kwargs)

    def complete(self, prompt: str, *, system: str | None = None, cache_key: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        completion = self._client.chat.completions.create(**kwargs)
        return completion.choices[0].message.content or ""


class DeepInfraLLMClient(OpenAILLMClient):
    backend = "deepinfra"


def _looks_like_qwen3_model(model: str) -> bool:
    """Whether ``model`` names a Qwen3-family checkpoint (``Qwen3.6-27B``, ``Qwen/Qwen3.6-27B``,
    ``qwen3.6-27b-instruct``, ...). Case-insensitive substring match on ``qwen3``."""
    return "qwen3" in model.lower()


def _thinking_disabled_extra_body(config: dict, model: str) -> dict | None:
    """``extra_body`` that disables Qwen3-family "thinking mode" unless overridden.

    Thinking mode is on by default for Qwen3-family chat templates (DeepInfra and the
    organizer-confirmed SGLang deployment alike: ``sglang serve --reasoning-parser qwen3``,
    2026-08-04 organizer email) and adds a full chain-of-thought before the answer -- verified
    live against DeepInfra 2026-07-11 (10.6s with thinking vs 1.1s without, for the same trivial
    prompt, ~10x). We only need the short structured JSON parse/refine response, and
    ``DEFAULT_LLM_TIMEOUT_SEC`` (30s) is sized for the non-thinking case, so both the ``openai``
    backend (the one pointed at an OpenAI-compatible SGLang/local endpoint, per
    ``agent_env/config.phase2.example.toml``) and ``deepinfra`` default it off *when the configured
    model looks like a Qwen3 checkpoint*. The ``openai`` backend is also the generic escape hatch
    for non-Qwen OpenAI-compatible providers (OpenRouter, plain OpenAI, ...), and
    ``chat_template_kwargs`` is an SGLang/vLLM extension outside the OpenAI wire spec -- sending it
    to a provider that rejects unknown request fields would break every call, so the default only
    fires for a model name that actually looks like Qwen3. Override with config
    ``enable_thinking: True``, ``TPC_P2_LLM_ENABLE_THINKING=1``, or a raw ``extra_body`` config
    value, either of which always wins outright regardless of the model name.
    """
    extra_body = config.get("extra_body")
    if extra_body is not None:
        return extra_body
    enable_thinking = config.get("enable_thinking")
    if enable_thinking is None:
        enable_thinking = str(os.environ.get("TPC_P2_LLM_ENABLE_THINKING", "")).lower() in (
            "1", "true", "yes",
        )
    if enable_thinking or not _looks_like_qwen3_model(model):
        return None
    return {"chat_template_kwargs": {"enable_thinking": False}}


def build_llm_client(config: dict | None = None) -> LLMClient:
    """Factory honoring config + ``TPC_P2_LLM_BACKEND``. Default backend is ``none``.

    ``config`` keys: backend, model, base_url, api_key, api_key_env, fixtures_dir,
    temperature, max_tokens.
    """
    config = dict(config or {})
    backend = str(config.get("backend") or os.environ.get("TPC_P2_LLM_BACKEND") or DEFAULT_BACKEND).lower()

    # Convenience: allow scripts to run without an explicit shell `source .env`.
    # Existing exported env vars still win unless overwrite=True is requested via direct call.
    if backend in {"openai", "deepinfra"}:
        load_local_env()

    if backend == "none":
        return NoneLLMClient()

    if backend == "fixture":
        fixtures_dir = config.get("fixtures_dir") or os.environ.get("TPC_P2_LLM_FIXTURES")
        if not fixtures_dir:
            raise ValueError("fixture backend requires 'fixtures_dir' (config or TPC_P2_LLM_FIXTURES).")
        return FixtureLLMClient(fixtures_dir)

    if backend == "openai":
        api_key = config.get("api_key")
        api_key_env = config.get("api_key_env")
        if not api_key and api_key_env:
            api_key = os.environ.get(str(api_key_env))
        model = str(config.get("model") or os.environ.get("TPC_P2_LLM_MODEL") or "")
        client = OpenAILLMClient(
            model=model,
            base_url=config.get("base_url") or os.environ.get("TPC_P2_LLM_BASE_URL"),
            api_key=api_key,
            temperature=float(config.get("temperature", 0.0)),
            max_tokens=config.get("max_tokens"),
            extra_body=_thinking_disabled_extra_body(config, model),
            timeout=_resolve_timeout(config),
        )
        return _maybe_wrap_cache(client, config)

    if backend == "deepinfra":
        api_key = config.get("api_key") or os.environ.get("DEEPINFRA_API_KEY")
        api_key_env = config.get("api_key_env") or "DEEPINFRA_API_KEY"
        if not api_key and api_key_env:
            api_key = os.environ.get(str(api_key_env))
        base_url = (
            config.get("base_url")
            or os.environ.get("TPC_P2_LLM_BASE_URL")
            or os.environ.get("DEEPINFRA_BASE_URL")
            or DEFAULT_DEEPINFRA_BASE_URL
        )
        model = str(
            config.get("model")
            or os.environ.get("TPC_P2_LLM_MODEL")
            or os.environ.get("DEEPINFRA_MODEL")
            or DEFAULT_DEEPINFRA_MODEL
        )
        extra_body = _thinking_disabled_extra_body(config, model)
        client = DeepInfraLLMClient(
            model=model,
            base_url=str(base_url),
            api_key=api_key,
            temperature=float(config.get("temperature", 0.0)),
            max_tokens=config.get("max_tokens"),
            extra_body=extra_body,
            timeout=_resolve_timeout(config),
        )
        return _maybe_wrap_cache(client, config)

    raise ValueError(f"Unknown LLM backend: {backend!r} (expected none|fixture|openai|deepinfra).")


def _resolve_timeout(config: dict) -> float:
    value = config.get("timeout")
    if value is None:
        value = os.environ.get("TPC_P2_LLM_TIMEOUT_SEC")
    return float(value) if value is not None else DEFAULT_LLM_TIMEOUT_SEC


def _maybe_wrap_cache(client: LLMClient, config: dict) -> LLMClient:
    """Wrap a network-backed client in CachingLLMClient unless disabled via
    TPC_P2_LLM_CACHE=0 or config['cache'] is False. Enabled by default: temperature is always 0
    for these backends, so a cached response is exactly what a live call would return."""
    cache_flag = config.get("cache")
    if cache_flag is None:
        cache_flag = os.environ.get("TPC_P2_LLM_CACHE", "1")
    if str(cache_flag) in ("0", "false", "False"):
        return client
    cache_dir = config.get("cache_dir") or os.environ.get("TPC_P2_LLM_CACHE_DIR")
    if not cache_dir:
        root = _find_project_root() or Path.cwd()
        cache_dir = root / "cache" / "phase2_llm_parse"
    return CachingLLMClient(client, cache_dir)
