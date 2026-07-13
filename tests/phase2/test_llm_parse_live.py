"""Tier 2 (plan3 N7): live-LLM smokes against the real DeepInfra endpoint.

Opt-in only (`pytest -m llm`); excluded from the default suite by `addopts` in pyproject.toml.
These guard the real-endpoint plumbing and merge policy, not model quality: assert properties any
correct response satisfies (schema-validity, whitelisted keys, telemetry health), never exact
strings, since Qwen3.6-27B output is nondeterministic even at temperature 0.

Must NOT use the `no_network` fixture -- these tests need real sockets.
"""

from __future__ import annotations

import os

import pytest

from chinatravel.agent.phase2 import llm_client as lc
from chinatravel.agent.phase2 import normalize
from chinatravel.agent.phase2 import orchestrator as O

pytestmark = pytest.mark.llm


def _skip_if_no_key():
    lc.load_local_env()
    if not os.environ.get("DEEPINFRA_API_KEY"):
        pytest.skip("DEEPINFRA_API_KEY not set (put it in .env or export it) -- skipping live-LLM smoke.")


@pytest.fixture
def live_deepinfra_client():
    _skip_if_no_key()
    return lc.build_llm_client({"backend": "deepinfra", "cache": False})


def test_deepinfra_client_completes_a_trivial_prompt(live_deepinfra_client):
    # Guards the raw transport: base_url/model/auth actually reach a real DeepInfra response.
    out = live_deepinfra_client.complete("Reply with exactly the word: pong", system="Be terse.")
    assert isinstance(out, str)
    assert out.strip()


def test_llm_parse_stub_on_canonical_query_stays_within_allowed_keys(one_query, live_deepinfra_client):
    # One unambiguous canonical query through the real Stage-1 LLM path (plan3 N7 Tier 2).
    flags = O.Flags(llm_backend="deepinfra", llm_parse=True)
    deterministic_raw = normalize.parse_to_ir(one_query, llm_client=None, flags=O.Flags())
    ir = normalize.parse_to_ir(one_query, llm_client=live_deepinfra_client, flags=flags)

    # Attempted and succeeded: the call must not silently fail over the network (measurement
    # hygiene rule in CLAUDE.md -- confirm telemetry, not just that something came back).
    assert ir.llm_parse_error is None

    # The patch may only ever touch the whitelisted family keys, even against a live response --
    # this is the merge guard's whitelist enforcement (_apply_patch), exercised end to end.
    added_or_changed = set(ir.raw.keys()) - set(deterministic_raw.raw.keys())
    for key in ir.raw:
        if ir.raw[key] != deterministic_raw.raw.get(key):
            added_or_changed.add(key)
    assert added_or_changed <= normalize._LLM_PARSE_ALLOWED_KEYS

    # The resulting IR must still produce schema-shaped solver variants (no crash downstream).
    variants = normalize.ir_to_solver_variants(ir, one_query, flags=flags)
    assert isinstance(variants, list)
    assert len(variants) >= 1


def test_llm_parse_remove_guard_holds_against_live_response(one_query, live_deepinfra_client):
    # N4 merge guard, exercised end to end against a real (nondeterministic) model response: any
    # family the deterministic parser emitted that is absent from the final IR must have been
    # removed either via the small whitelist or paired with its opposite-polarity correction --
    # never via a bare "this looks spurious" claim (G1: that precision judgment barely matters for
    # e2e outcomes and isn't trusted alone).
    flags = O.Flags(llm_backend="deepinfra", llm_parse=True)
    deterministic_raw = normalize.parse_to_ir(one_query, llm_client=None, flags=O.Flags())
    ir = normalize.parse_to_ir(one_query, llm_client=live_deepinfra_client, flags=flags)
    assert ir.llm_parse_error is None

    removed = set(deterministic_raw.raw) - set(ir.raw)
    for field in removed:
        opposite = normalize._LLM_REMOVE_POLARITY_OPPOSITE.get(field)
        assert field in normalize._LLM_REMOVE_WHITELIST or (
            opposite is not None and opposite in ir.raw
        ), f"{field} was removed without a whitelist entry or an opposite-polarity correction"
