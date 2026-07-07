"""LLM client abstraction for the Phase 2 harness.

Three backends, selected by config / the ``TPC_P2_LLM_BACKEND`` env var:

- ``none``    : default. No LLM. Calling ``complete`` raises ``LLMDisabledError`` — the
                deterministic path must never call it. Guarantees zero network locally.
- ``fixture`` : replays cached responses from a fixtures directory, keyed by ``cache_key``
                (or a hash of the prompt). Zero network. For dev (hand-produced parses) + tests.
- ``openai``  : OpenAI-compatible endpoint (SGLang, OpenRouter, local Qwen, ...). Reuses the
                ``openai`` package. OpenRouter is just a ``base_url`` + ``api_key`` preset.

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
            "Set TPC_P2_LLM_BACKEND=fixture|openai (and the relevant feature flag) to enable it."
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


def _load_openai_class():  # pragma: no cover - trivial import indirection (mocked in tests)
    from openai import OpenAI

    return OpenAI


class OpenAILLMClient(LLMClient):
    backend = "openai"

    def __init__(self, *, model: str, base_url: str | None = None, api_key: str | None = None,
                 temperature: float = 0.0, max_tokens: int | None = None):
        if not model:
            raise ValueError("openai backend requires a 'model'.")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        openai_cls = _load_openai_class()
        client_kwargs: dict[str, Any] = {}
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
        completion = self._client.chat.completions.create(**kwargs)
        return completion.choices[0].message.content or ""


def build_llm_client(config: dict | None = None) -> LLMClient:
    """Factory honoring config + ``TPC_P2_LLM_BACKEND``. Default backend is ``none``.

    ``config`` keys: backend, model, base_url, api_key, api_key_env, fixtures_dir,
    temperature, max_tokens.
    """
    config = dict(config or {})
    backend = str(config.get("backend") or os.environ.get("TPC_P2_LLM_BACKEND") or DEFAULT_BACKEND).lower()

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
        return OpenAILLMClient(
            model=str(config.get("model") or os.environ.get("TPC_P2_LLM_MODEL") or ""),
            base_url=config.get("base_url") or os.environ.get("TPC_P2_LLM_BASE_URL"),
            api_key=api_key,
            temperature=float(config.get("temperature", 0.0)),
            max_tokens=config.get("max_tokens"),
        )

    raise ValueError(f"Unknown LLM backend: {backend!r} (expected none|fixture|openai).")
