"""Tests for Stage 3 LLM refine (orchestrator.llm_refine / phase2/refine.py).

Uses fake ``ground_and_check``/``apply_refine_edits`` hooks (the shape ``make_tpcagent_solve_fn``
attaches to a TPCAgent-backed ``solve_fn``) so no WorldEnv/TPCAgent is needed here -- TPCAgent-side
grounding of the typed edit ops is covered separately in tests/phase2/test_llm_refine_agent.py.
Covers the floor (no hook / already accepted -> zero LLM calls, plan unchanged), the
acceptance-gated repair path (commit / reject-on-non-acceptance / reject-on-regression), graceful
degradation (no client, budget too small, LLM error, invalid JSON, no edits, ungroundable edits),
and that the prompt never carries an oracle field.
"""

from __future__ import annotations

from chinatravel.agent.phase2 import orchestrator as O
from chinatravel.agent.phase2 import refine as R

EDIT_RESPONSE = '{"edits":[{"op":"drop_activity","day":1,"location":"X"}]}'


class FakeClient:
    def __init__(self, response, timeout=None):
        self.response = response
        self.calls = []
        if timeout is not None:
            self.timeout = timeout

    def complete(self, prompt, *, system=None, cache_key=None):
        self.calls.append({"prompt": prompt, "cache_key": cache_key})
        return self.response


class BoomClient:
    def complete(self, prompt, *, system=None, cache_key=None):
        raise RuntimeError("network blew up")


def _hooks(*, accepted_before, key_before, accepted_after=True, key_after=None, applied=1,
           failure=None):
    """A scripted (ground_and_check, apply_refine_edits) pair: the first ground_and_check call
    reports the input plan's state, the second (post-edit) call reports the trial's state."""
    failure = failure if failure is not None else {"failed_constraint_families": ["required_attractions"]}
    key_after = key_before if key_after is None else key_after
    calls = {"gac": 0, "are": 0}

    def ground_and_check(plan):
        calls["gac"] += 1
        if calls["gac"] == 1:
            return accepted_before, plan, key_before, failure
        return accepted_after, plan, key_after, {}

    def apply_refine_edits(plan, edits):
        calls["are"] += 1
        trial = dict(plan)
        trial["itinerary"] = list(plan.get("itinerary", [])) + [{"day": 99, "activities": [], "_edited": True}]
        return trial, applied

    return ground_and_check, apply_refine_edits, calls


def _plan():
    return {"itinerary": [{"day": 1, "activities": []}]}


def test_no_ground_and_check_hook_is_noop(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    out, info = O.llm_refine(plan, one_query, llm, 30.0, None, None)
    assert out is plan
    assert info["improve_skip_reason"] == "no_ground_and_check_hook"
    assert info["improve_llm_called"] is False
    assert llm.calls == []


def test_already_accepted_is_noop_repair_only_v1(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, _ = _hooks(accepted_before=True, key_before=(1, 1, 1, 0))
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert out is plan
    assert info["improve_skip_reason"] == "already_accepted"
    assert llm.calls == []


def test_no_llm_client_is_noop(one_query):
    plan = _plan()
    gac, are, _ = _hooks(accepted_before=False, key_before=(0, 0, 0, 0))
    out, info = O.llm_refine(plan, one_query, None, 30.0, gac, are)
    assert out is plan
    assert info["improve_skip_reason"] == "no_llm_client"


def test_skips_when_budget_cannot_fit_one_call(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE, timeout=30.0)
    gac, are, _ = _hooks(accepted_before=False, key_before=(0, 0, 0, 0))
    out, info = O.llm_refine(plan, one_query, llm, 5.0, gac, are)
    assert out is plan
    assert info["improve_skip_reason"] == "skipped_deadline"
    assert llm.calls == []


def test_repair_commits_on_accept_and_no_regression(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, calls = _hooks(
        accepted_before=False, key_before=(0.5, 0.5, 1, 0),
        accepted_after=True, key_after=(0.6, 0.6, 1, 0),
    )
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert info["improve_llm_called"] is True
    assert info["improve_committed"] is True
    assert info["improve_edit_count"] == 1
    assert out != plan
    assert len(out["itinerary"]) == len(plan["itinerary"]) + 1  # per the fake apply_refine_edits
    assert len(llm.calls) == 1
    assert calls["are"] == 1


def test_rejects_when_trial_not_accepted(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, _ = _hooks(accepted_before=False, key_before=(0.5, 0.5, 1, 0), accepted_after=False)
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert out is plan
    assert info["improve_committed"] is False
    assert info["improve_skip_reason"] == "not_accepted_or_regressed"


def test_rejects_when_eval_key_regresses(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, _ = _hooks(
        accepted_before=False, key_before=(0.9, 0.9, 3, 0),
        accepted_after=True, key_after=(0.1, 0.1, 1, 0),
    )
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert out is plan
    assert info["improve_committed"] is False
    assert info["improve_skip_reason"] == "not_accepted_or_regressed"


def test_graceful_degrade_on_invalid_json(one_query):
    plan = _plan()
    llm = FakeClient("not json")
    gac, are, _ = _hooks(accepted_before=False, key_before=(0, 0, 0, 0))
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert out is plan
    assert info["improve_llm_called"] is True
    assert info["improve_skip_reason"] == "llm_error_or_invalid_json"


def test_graceful_degrade_on_llm_error(one_query):
    plan = _plan()
    gac, are, _ = _hooks(accepted_before=False, key_before=(0, 0, 0, 0))
    out, info = O.llm_refine(plan, one_query, BoomClient(), 30.0, gac, are)
    assert out is plan
    assert info["improve_skip_reason"] == "llm_error_or_invalid_json"


def test_graceful_degrade_on_no_edits_proposed(one_query):
    plan = _plan()
    llm = FakeClient('{"edits":[]}')
    gac, are, _ = _hooks(accepted_before=False, key_before=(0, 0, 0, 0))
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert out is plan
    assert info["improve_skip_reason"] == "no_edits_proposed"


def test_graceful_degrade_on_ungroundable_edit(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, _ = _hooks(accepted_before=False, key_before=(0, 0, 0, 0), applied=0)
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert out is plan
    assert info["improve_edit_count"] == 0
    assert info["improve_skip_reason"] == "no_groundable_edits"


def test_graceful_degrade_on_ground_and_check_error(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)

    def boom_gac(_plan):
        raise RuntimeError("checker blew up")

    out, info = O.llm_refine(plan, one_query, llm, 30.0, boom_gac, lambda p, e: (p, 0))
    assert out is plan
    assert info["improve_skip_reason"] == "ground_and_check_error"
    assert llm.calls == []


def test_no_apply_edits_hook_is_noop_after_llm_call(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, _are, _ = _hooks(accepted_before=False, key_before=(0, 0, 0, 0))
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, None)
    assert out is plan
    assert info["improve_llm_called"] is True
    assert info["improve_skip_reason"] == "no_apply_edits_hook"


def test_unknown_ops_are_dropped_by_parser():
    edits = R.parse_llm_refine_edits(
        '{"edits":[{"op":"rewrite_everything"},{"op":"drop_activity","day":1,"location":"X"}]}'
    )
    assert len(edits) == 1
    assert edits[0]["op"] == "drop_activity"


def test_parse_raises_on_invalid_json():
    import pytest

    with pytest.raises(ValueError):
        R.parse_llm_refine_edits("not json at all")


def test_parse_raises_on_missing_edits_key():
    # Regression for a Copilot review finding on PR #32: a response shape violation (wrong key
    # name, e.g. the model wrote "edit" instead of "edits") must raise, not silently degrade to
    # "no edits proposed" -- that would mask a real prompt/model regression.
    import pytest

    with pytest.raises(ValueError):
        R.parse_llm_refine_edits('{"edit": [{"op": "drop_activity"}]}')


def test_parse_raises_on_non_list_edits_value():
    import pytest

    with pytest.raises(ValueError):
        R.parse_llm_refine_edits('{"edits": "none"}')


def test_parse_returns_empty_for_explicit_empty_edits_list():
    assert R.parse_llm_refine_edits('{"edits": []}') == []


def test_cache_key_stable_and_scoped_to_uid_and_prompt():
    q1 = {"uid": "abc"}
    q2 = {"uid": "xyz"}
    k1 = R.llm_refine_cache_key(q1, "prompt-a")
    k2 = R.llm_refine_cache_key(q1, "prompt-a")
    k3 = R.llm_refine_cache_key(q2, "prompt-a")
    k4 = R.llm_refine_cache_key(q1, "prompt-b")
    assert k1 == k2
    assert k1 != k3
    assert k1 != k4
    assert k1.startswith("refine_abc_")


def test_prompt_has_no_oracle_fields(one_query):
    # one_query is real tpc_phase1 data and typically carries hard_logic_py -- the prompt must
    # never embed it (or any *_py verifier field), only the visible allowlist + plan + failure
    # summary.
    plan = _plan()
    failure = {"failed_constraint_families": ["required_attractions"], "failed_commonsense_checks": []}
    prompt = R.build_llm_refine_prompt(one_query, plan, failure)
    assert "hard_logic_py" not in prompt
    assert "hard_logic" not in prompt
    for key in one_query:
        if key.endswith("_py") or key in ("hard_logic", "hard_logic_py", "plan"):
            assert str(one_query[key]) not in prompt or key in ("uid",)


def test_prompt_lists_allowed_ops_and_edit_cap():
    plan = {"itinerary": [{"day": 1, "activities": [
        {"type": "attraction", "position": "Museum", "start_time": "09:00", "end_time": "10:00"},
    ]}]}
    prompt = R.build_llm_refine_prompt({"uid": "u1"}, plan, {})
    for op in R.REFINE_ALLOWED_OPS:
        assert op in prompt
    assert "Museum" in prompt
    assert str(R.MAX_REFINE_EDITS) in prompt
