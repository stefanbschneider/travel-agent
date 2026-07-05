"""Shared fixtures for Phase 2 harness tests.

Design notes:
- ``sample_queries`` loads a few real ``tpc_phase1`` queries once per session by reading the
  English data files directly (no heavy dataset machinery).
- ``SpyLLMClient`` records every call so tests can assert the deterministic path never touches
  the LLM when all flags are off.
- ``fast_solve_fn`` is an injectable Stage-2 stub so orchestrator unit tests do not need a real
  ``WorldEnv`` / solver.
- ``no_network`` monkeypatches sockets to fail loudly, guarding the "no API calls by default" rule.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# Allow importing modules that live in the (non-package) scripts/ directory.
_SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_AGENT_ENV_SCRIPTS = PROJECT_ROOT / "agent_env" / "scripts"
if str(_AGENT_ENV_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_AGENT_ENV_SCRIPTS))

EN_DATA_DIR = PROJECT_ROOT / "chinatravel" / "data" / "en" / "TPC_IJCAI_2026_phase1_EN"
SPLIT_FILE = PROJECT_ROOT / "chinatravel" / "evaluation" / "default_splits" / "tpc_phase1.txt"


def _read_split_uids() -> list[str]:
    with open(SPLIT_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def all_phase1_uids() -> list[str]:
    return _read_split_uids()


@pytest.fixture(scope="session")
def sample_uids() -> list[str]:
    """A small, stable set of uids that exist in the local English data directory."""
    uids = []
    for uid in _read_split_uids():
        if (EN_DATA_DIR / f"{uid}.json").exists():
            uids.append(uid)
        if len(uids) >= 8:
            break
    if not uids:
        pytest.skip("No local tpc_phase1 English query files found.")
    return uids


@pytest.fixture(scope="session")
def sample_queries(sample_uids) -> dict[str, dict]:
    queries = {}
    for uid in sample_uids:
        with open(EN_DATA_DIR / f"{uid}.json", "r", encoding="utf-8") as f:
            q = json.load(f)
        q.setdefault("uid", uid)
        queries[uid] = q
    return queries


@pytest.fixture(scope="session")
def one_query(sample_queries) -> dict:
    return next(iter(sample_queries.values()))


class SpyLLMClient:
    """LLM client stand-in that records calls; asserts nothing hits a real model."""

    def __init__(self):
        self.calls = []

    @property
    def backend(self) -> str:
        return "spy"

    def complete(self, prompt, *, system=None, cache_key=None):
        self.calls.append({"prompt": prompt, "system": system, "cache_key": cache_key})
        return ""


@pytest.fixture
def spy_llm() -> SpyLLMClient:
    return SpyLLMClient()


@pytest.fixture
def fast_solve_fn():
    """A Stage-2 solve stub: returns a minimal non-empty plan quickly, no WorldEnv needed."""

    def _solve(query, variants, budget_sec):
        return {
            "people_number": query.get("people_number", 1),
            "start_city": query.get("start_city", ""),
            "target_city": query.get("target_city", ""),
            "itinerary": [{"day": 1, "activities": []}],
            "_stub": True,
        }

    return _solve


@pytest.fixture
def no_network(monkeypatch):
    """Make any attempt to open a socket fail loudly."""

    def _blocked(*args, **kwargs):
        raise AssertionError("Network access is not allowed in this test.")

    monkeypatch.setattr(socket, "socket", _blocked)
    # Guard the common high-level entry points too.
    monkeypatch.setattr(socket, "create_connection", _blocked, raising=False)
    return True
