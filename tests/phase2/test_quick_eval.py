"""Unit tests for the quick A/B screen verdict logic (scripts/phase2_quick_eval.py).

Only the pure ``decide_verdict`` reconciliation is unit-tested here -- it is the piece that turns
paired metric deltas + the monotonic gate into a go/no-go, and it must stay honest about the
timeout caveat. Running an actual solve is an integration concern (covered by the worked example in
docs/tpc_phase2_eval.md, "Quick A/B screen"), not a unit test.
"""

from __future__ import annotations

import phase2_quick_eval as qe
from phase2_gate import check_gate


def _metrics(fpr, cs, timeouts=0, parse_failures=0):
    return {
        "fpr": fpr,
        "continuous_score": cs,
        "timeouts": timeouts,
        "parse_failures": parse_failures,
    }


def _verdict(baseline, candidate, flag="TPC_PIN_TIMED_WINDOWS"):
    gate = check_gate(baseline, candidate)
    return qe.decide_verdict(baseline, candidate, gate, flag)


def test_clean_improvement_is_green_light():
    base = _metrics(20.0, 43.9, timeouts=7)
    cand = _metrics(26.7, 49.9, timeouts=7)  # FPR up, no extra timeouts
    v = _verdict(base, cand)
    assert v.startswith("GREEN LIGHT:")


def test_improvement_with_only_timeout_block_is_green_with_caveat():
    # The real TPC_PIN_TIMED_WINDOWS screen: FPR + pref up, but +2 recovered timeouts trip the gate.
    base = _metrics(20.0, 43.88, timeouts=7)
    cand = _metrics(26.67, 49.88, timeouts=9)
    gate = check_gate(base, cand)
    assert gate["passed"] is False  # strict gate blocks on the timeout increase
    v = qe.decide_verdict(base, cand, gate, "TPC_PIN_TIMED_WINDOWS")
    assert v.startswith("GREEN LIGHT (with caveat)")
    assert "+2 timeouts" in v


def test_fpr_regression_is_red_even_if_timeouts_improve():
    base = _metrics(23.3, 46.0, timeouts=9)
    cand = _metrics(20.0, 46.0, timeouts=6)  # fewer timeouts but FPR dropped
    v = _verdict(base, cand)
    assert v.startswith("RED:")


def test_new_parse_failure_is_red():
    base = _metrics(20.0, 43.9, timeouts=7, parse_failures=0)
    cand = _metrics(26.0, 48.0, timeouts=7, parse_failures=1)
    v = _verdict(base, cand)
    assert v.startswith("RED:")


def test_no_delta_is_neutral():
    base = _metrics(20.0, 43.9, timeouts=7)
    cand = _metrics(20.0, 43.9, timeouts=7)
    v = _verdict(base, cand)
    assert v.startswith("NEUTRAL:")


def test_sub_noise_pref_drop_is_not_red():
    # The real TPC_P2_LLM_REFINE screen: FPR held, overall_true -0.02 (pure noise), +8 timeouts,
    # zero commits. A -0.02 must NOT read as a RED correctness regression; the added cost with no
    # benefit is a NO BENEFIT thumbs-down instead.
    base = _metrics(20.0, 47.38, timeouts=11)
    cand = _metrics(20.0, 47.35, timeouts=19)
    v = _verdict(base, cand, flag="TPC_P2_LLM_REFINE")
    assert v.startswith("NO BENEFIT")
    assert not v.startswith("RED")


def test_pref_drop_beyond_noise_is_red():
    # The real TPC_P2_LLM_PARSE screen at timeout=15 (audit actually firing): overall_true -3.20.
    base = _metrics(20.0, 47.38, timeouts=11)
    cand = _metrics(20.0, 44.18, timeouts=11)
    v = _verdict(base, cand, flag="TPC_P2_LLM_PARSE")
    assert v.startswith("RED:")


def test_flat_quality_with_added_cost_is_no_benefit_not_neutral():
    base = _metrics(20.0, 43.9, timeouts=7)
    cand = _metrics(20.0, 43.9, timeouts=10)  # identical quality, more timeouts
    v = _verdict(base, cand)
    assert v.startswith("NO BENEFIT")


def test_converge_target_is_timeouts_at_held_fpr():
    # The real TPC_SOLVE_CONVERGE_PATIENCE screen: FPR held, a timeout shaved -> green for this flag.
    base = _metrics(20.0, 43.88, timeouts=7)
    cand = _metrics(20.0, 46.16, timeouts=6)
    v = _verdict(base, cand, flag="TPC_SOLVE_CONVERGE_PATIENCE")
    assert v.startswith("GREEN LIGHT:")


def test_converge_fewer_timeouts_but_fpr_drop_is_red():
    # Shaving a timeout does not license an FPR regression, even for the convergence flag.
    base = _metrics(20.0, 43.88, timeouts=7)
    cand = _metrics(16.0, 43.88, timeouts=5)
    v = _verdict(base, cand, flag="TPC_SOLVE_CONVERGE_PATIENCE")
    assert v.startswith("RED:")


def test_pref_only_improvement_at_flat_fpr_is_green():
    # FPR flat, preference up, no gate block -> still a green (overall_true is a correctness signal).
    base = _metrics(20.0, 43.0, timeouts=7)
    cand = _metrics(20.0, 45.0, timeouts=7)
    v = _verdict(base, cand)
    assert v.startswith("GREEN LIGHT:")
