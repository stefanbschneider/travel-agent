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
        reasons = [{"op": e.get("op"), "committed": bool(applied), "reason": "committed" if applied else "test_stub"}
                   for e in (edits or [])]
        return trial, applied, reasons

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
    assert info["improve_edit_reasons"] == [{"op": "drop_activity", "committed": True, "reason": "committed"}]
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


def _two_attempt_hooks(*, key_before, second_attempt_accepts, applied=1):
    """Scripts three ground_and_check calls: (1) the initial check on the input plan -- rejected,
    driving the first refine attempt; (2) the post-edit check on attempt 1's trial -- also
    rejected, driving the bounded second attempt (bucket 2); (3) the post-edit check on attempt 2's
    trial -- accepts iff ``second_attempt_accepts``. Each attempt's failure summary differs (a
    distinct family name) so a test can confirm the second attempt's prompt is built from the
    *post-edit* failure, not the original."""
    failures = [
        {"failed_constraint_families": ["required_attractions"]},
        {"failed_constraint_families": ["required_restaurants"]},
        {},
    ]
    calls = {"gac": 0, "are": 0}

    def ground_and_check(plan):
        idx = calls["gac"]
        calls["gac"] += 1
        failure = failures[min(idx, len(failures) - 1)]
        if idx < 2:
            return False, plan, key_before, failure
        return second_attempt_accepts, plan, key_before, failure

    def apply_refine_edits(plan, edits):
        calls["are"] += 1
        trial = dict(plan)
        trial["itinerary"] = list(plan.get("itinerary", [])) + [
            {"day": 90 + calls["are"], "activities": [], "_edited": True}
        ]
        reasons = [{"op": e.get("op"), "committed": bool(applied), "reason": "committed" if applied else "test_stub"}
                   for e in (edits or [])]
        return trial, applied, reasons

    return ground_and_check, apply_refine_edits, calls


def test_second_attempt_commits_after_first_batch_rejected(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, calls = _two_attempt_hooks(key_before=(0.5, 0.5, 1, 0), second_attempt_accepts=True)
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert info["improve_committed"] is True
    assert info["improve_attempts"] == 2
    assert info["improve_skip_reason"] is None
    assert calls["gac"] == 3
    assert calls["are"] == 2
    assert len(llm.calls) == 2
    assert len(out["itinerary"]) == len(plan["itinerary"]) + 2


def test_second_attempt_prompt_uses_post_edit_plan_and_failure(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, _calls = _two_attempt_hooks(key_before=(0.5, 0.5, 1, 0), second_attempt_accepts=True)
    O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert len(llm.calls) == 2
    assert "required_attractions" in llm.calls[0]["prompt"]
    assert "required_restaurants" not in llm.calls[0]["prompt"]
    assert "required_restaurants" in llm.calls[1]["prompt"]


def test_second_attempt_also_rejected_reports_final_skip_reason(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, calls = _two_attempt_hooks(key_before=(0.5, 0.5, 1, 0), second_attempt_accepts=False)
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert out is plan
    assert info["improve_committed"] is False
    assert info["improve_skip_reason"] == "not_accepted_or_regressed"
    assert info["improve_attempts"] == 2
    assert len(llm.calls) == 2


def test_no_second_attempt_when_first_batch_has_no_groundable_edits(one_query):
    # Bucket 2's second attempt is scoped to "grounded but rejected" (not_accepted_or_regressed);
    # a first batch that produces no groundable edits at all must not trigger a retry.
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, _ = _hooks(accepted_before=False, key_before=(0, 0, 0, 0), applied=0)
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert out is plan
    assert info["improve_skip_reason"] == "no_groundable_edits"
    assert info["improve_attempts"] == 1
    assert len(llm.calls) == 1


def test_second_attempt_skipped_when_slice_cannot_fit_two_calls(one_query, monkeypatch):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE, timeout=20.0)
    gac, are, calls = _two_attempt_hooks(key_before=(0.5, 0.5, 1, 0), second_attempt_accepts=True)
    # Fake a 15s-elapsed first attempt against a 20s budget -- only 5s remains, less than the
    # client's own 20s timeout, so the second call must be skipped rather than started.
    ticks = iter([0.0, 15.0])
    monkeypatch.setattr(O.time, "perf_counter", lambda: next(ticks))
    out, info = O.llm_refine(plan, one_query, llm, 20.0, gac, are)
    assert out is plan
    assert info["improve_committed"] is False
    assert info["improve_skip_reason"] == "not_accepted_or_regressed"
    assert info["improve_second_attempt_skip_reason"] == "skipped_deadline"
    assert info["improve_attempts"] == 1
    assert len(llm.calls) == 1
    assert calls["gac"] == 2


# --- Copilot review findings on PR #36 --------------------------------------------------------

def test_llm_refine_attempt_never_raises_on_prompt_build_error(one_query, monkeypatch):
    # Prompt/cache-key construction must be inside the same try/except as the LLM call -- a
    # malformed base_plan/failure_summary (e.g. bad retry context) must degrade via
    # improve_skip_reason, never bubble an exception out of llm_refine's "never raises" contract.
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, _ = _hooks(accepted_before=False, key_before=(0, 0, 0, 0))

    def boom_prompt(query, plan, failure_summary):
        raise RuntimeError("bad failure_summary shape")

    monkeypatch.setattr(O.refine_mod, "build_llm_refine_prompt", boom_prompt)
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert out is plan
    assert info["improve_skip_reason"] == "llm_error_or_invalid_json"
    assert info["improve_llm_called"] is False
    assert llm.calls == []


def test_second_attempt_skipped_on_invalid_retry_context(one_query):
    # A misbehaving ground_and_check hook could in principle report a non-dict "grounded plan" --
    # attempt 2 must not build a prompt from it; it should skip with a dedicated reason instead of
    # crashing or silently misclassifying the failure as an LLM/JSON error.
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    calls = {"gac": 0, "are": 0}

    def ground_and_check(p):
        calls["gac"] += 1
        if calls["gac"] == 1:
            return False, p, (0.5, 0.5, 1, 0), {"failed_constraint_families": ["required_attractions"]}
        # Post-edit-1 check: rejected, and returns a non-dict grounded plan.
        return False, "not-a-dict", (0.5, 0.5, 1, 0), {"failed_constraint_families": ["required_restaurants"]}

    def apply_refine_edits(p, edits):
        calls["are"] += 1
        trial = dict(p)
        trial["itinerary"] = list(p.get("itinerary", [])) + [{"day": 99, "activities": [], "_edited": True}]
        reasons = [{"op": e.get("op"), "committed": True, "reason": "committed"} for e in (edits or [])]
        return trial, 1, reasons

    out, info = O.llm_refine(plan, one_query, llm, 30.0, ground_and_check, apply_refine_edits)
    assert out is plan
    assert info["improve_committed"] is False
    assert info["improve_skip_reason"] == "not_accepted_or_regressed"
    assert info["improve_second_attempt_skip_reason"] == "invalid_retry_context"
    assert info["improve_attempts"] == 1
    assert len(llm.calls) == 1
    assert calls["are"] == 1


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
    assert info["improve_edit_reasons"] == [{"op": "drop_activity", "committed": False, "reason": "test_stub"}]


def test_graceful_degrade_on_ground_and_check_error(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)

    def boom_gac(_plan):
        raise RuntimeError("checker blew up")

    out, info = O.llm_refine(plan, one_query, llm, 30.0, boom_gac, lambda p, e: (p, 0, []))
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


# --- max_attempts loop (roadmap P6, TPC_P2_LLM_REPAIR_LOOP) ------------------------------------
#
# TPC_P2_LLM_REFINE's own default (max_attempts=2, unchanged) is covered exhaustively above; these
# generalize the same "rejected -> retry with post-edit failure" mechanism past two rounds.

def _n_attempt_hooks(*, key_before, n_rounds_before_accept, applied=1):
    """Rejects the first ``n_rounds_before_accept`` post-edit checks, then accepts. Each round's
    failure summary is distinct (family name includes the round index) so a test can confirm round
    k's prompt is built from round (k-1)'s post-edit failure, not a stale one."""
    calls = {"gac": 0, "are": 0}

    def ground_and_check(plan):
        idx = calls["gac"]
        calls["gac"] += 1
        failure = {"failed_constraint_families": [f"family_{idx}"]}
        accepted = idx > n_rounds_before_accept
        return accepted, plan, key_before, failure

    def apply_refine_edits(plan, edits):
        calls["are"] += 1
        trial = dict(plan)
        trial["itinerary"] = list(plan.get("itinerary", [])) + [
            {"day": 90 + calls["are"], "activities": [], "_edited": True}
        ]
        reasons = [{"op": e.get("op"), "committed": bool(applied), "reason": "committed" if applied else "test_stub"}
                   for e in (edits or [])]
        return trial, applied, reasons

    return ground_and_check, apply_refine_edits, calls


def test_default_max_attempts_is_two_reproducing_todays_behaviour(one_query):
    """No max_attempts argument at all -- the library default must still be exactly 2, so every
    TPC_P2_LLM_REFINE caller (and every test above) is unaffected by this item."""
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, calls = _n_attempt_hooks(key_before=(0.5, 0.5, 1, 0), n_rounds_before_accept=1)
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are)
    assert info["improve_committed"] is True
    assert info["improve_attempts"] == 2
    assert len(llm.calls) == 2


def test_max_attempts_six_commits_on_a_later_round(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, calls = _n_attempt_hooks(key_before=(0.5, 0.5, 1, 0), n_rounds_before_accept=4)
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are, max_attempts=6)
    assert info["improve_committed"] is True
    assert info["improve_attempts"] == 5
    assert len(llm.calls) == 5
    assert out != plan


def test_max_attempts_six_prompts_use_each_rounds_own_post_edit_failure(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, calls = _n_attempt_hooks(key_before=(0.5, 0.5, 1, 0), n_rounds_before_accept=4)
    O.llm_refine(plan, one_query, llm, 30.0, gac, are, max_attempts=6)
    assert len(llm.calls) == 5
    for i, call in enumerate(llm.calls):
        assert f"family_{i}" in call["prompt"]


def test_max_attempts_exhausted_without_committing_reports_final_skip_reason(one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, calls = _n_attempt_hooks(key_before=(0.5, 0.5, 1, 0), n_rounds_before_accept=99)
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are, max_attempts=6)
    assert out is plan
    assert info["improve_committed"] is False
    assert info["improve_skip_reason"] == "not_accepted_or_regressed"
    assert info["improve_attempts"] == 6
    assert len(llm.calls) == 6


def test_max_attempts_one_never_retries():
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE)
    gac, are, calls = _n_attempt_hooks(key_before=(0.5, 0.5, 1, 0), n_rounds_before_accept=1)
    out, info = O.llm_refine(plan, {"uid": "u1"}, llm, 30.0, gac, are, max_attempts=1)
    assert out is plan
    assert info["improve_committed"] is False
    assert info["improve_attempts"] == 1
    assert len(llm.calls) == 1


def test_max_attempts_six_still_stops_on_deadline_mid_loop(monkeypatch, one_query):
    plan = _plan()
    llm = FakeClient(EDIT_RESPONSE, timeout=10.0)
    gac, are, calls = _n_attempt_hooks(key_before=(0.5, 0.5, 1, 0), n_rounds_before_accept=99)
    # loop_start=0.0, then round 2's deadline check reads 25.0 -- 30-25=5s remains, less than the
    # 10s client timeout, so the loop must stop after round 1 rather than starting round 2.
    ticks = iter([0.0, 25.0])
    monkeypatch.setattr(O.time, "perf_counter", lambda: next(ticks))
    out, info = O.llm_refine(plan, one_query, llm, 30.0, gac, are, max_attempts=6)
    assert out is plan
    assert info["improve_second_attempt_skip_reason"] == "skipped_deadline"
    assert info["improve_attempts"] == 1
    assert len(llm.calls) == 1
