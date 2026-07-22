"""Live-LLM smoke tests for the Stage 3 refine prompt against the real DeepInfra/Qwen endpoint.

Opt-in only (`pytest -m llm`); excluded from the default suite by `addopts` in pyproject.toml.
These guard the real-endpoint plumbing (prompt -> real Qwen response -> parse_llm_refine_edits),
not model quality: assert properties any well-formed response satisfies (strict JSON, allowed op
vocabulary, no crash), never exact edits, since Qwen3.6-27B output is nondeterministic even at
temperature 0 and the model may reasonably propose zero edits for an already-fine synthetic plan.

Must NOT use the `no_network` fixture -- these tests need real sockets.
"""

from __future__ import annotations

import os

import pytest

from chinatravel.agent.phase2 import llm_client as lc
from chinatravel.agent.phase2 import refine as R

pytestmark = pytest.mark.llm


def _skip_if_no_key():
    lc.load_local_env()
    if not os.environ.get("DEEPINFRA_API_KEY"):
        pytest.skip("DEEPINFRA_API_KEY not set (put it in .env or export it) -- skipping live-LLM smoke.")


@pytest.fixture
def live_deepinfra_client():
    _skip_if_no_key()
    return lc.build_llm_client({"backend": "deepinfra", "cache": False})


_QUERY = {
    "uid": "phase2_refine_live_smoke",
    "people_number": 2,
    "start_city": "Beijing",
    "target_city": "Shanghai",
    "nature_language": (
        "Plan a 2-day trip to Shanghai for 2 people. We must have breakfast at Nanyang Inn "
        "between 07:50 and 08:40."
    ),
}

# A plan where the required Nanyang Inn breakfast landed outside its clause window -- the exact
# failure family Stage 3 targets (roadmap "Solver-only headroom": timed_visit_named_poi).
_MISTIMED_PLAN = {
    "people_number": 2,
    "start_city": "Beijing",
    "target_city": "Shanghai",
    "itinerary": [
        {
            "day": 1,
            "activities": [
                {"type": "breakfast", "position": "Nanyang Inn", "start_time": "07:00", "end_time": "07:30"},
                {"type": "attraction", "position": "The Bund", "start_time": "09:00", "end_time": "11:00"},
                {"type": "lunch", "position": "Din Tai Fung", "start_time": "12:00", "end_time": "13:00"},
                {"type": "accommodation", "position": "Nanyang Inn", "start_time": "20:00", "end_time": "24:00"},
            ],
        },
    ],
}

_FAILURE_SUMMARY = {
    "failed_constraint_families": ["activity_time_windows"],
    "failed_commonsense_checks": [],
    "schema_ok": True,
}


def test_refine_prompt_yields_strict_json_with_allowed_ops(live_deepinfra_client):
    prompt = R.build_llm_refine_prompt(_QUERY, _MISTIMED_PLAN, _FAILURE_SUMMARY)
    response = live_deepinfra_client.complete(prompt, cache_key="refine_live_smoke_test")
    assert isinstance(response, str)
    assert response.strip()

    # Must parse as the strict JSON schema this prompt asks for; a live-model response that isn't
    # valid JSON (or isn't an object with an "edits" list) is a real prompt/model regression, not
    # something to silently tolerate here (llm_refine itself degrades gracefully in that case, but
    # this smoke exists specifically to catch the schema break).
    edits = R.parse_llm_refine_edits(response)
    for edit in edits:
        assert edit["op"] in R.REFINE_ALLOWED_OPS
        if edit["op"] in ("shift_activity_window", "drop_activity"):
            assert "location" in edit
        if edit["op"] == "swap_activity":
            assert "location_a" in edit and "location_b" in edit
        if edit["op"] == "reorder_day":
            assert isinstance(edit.get("order"), list)


def test_refine_prompt_never_leaks_oracle_fields(live_deepinfra_client):
    # A defense-in-depth check against the real prompt text actually sent over the wire (unit
    # tests already cover this against fixture data; this exercises the exact string a live call
    # sees).
    prompt = R.build_llm_refine_prompt(_QUERY, _MISTIMED_PLAN, _FAILURE_SUMMARY)
    assert "hard_logic_py" not in prompt
    assert "hard_logic" not in prompt
