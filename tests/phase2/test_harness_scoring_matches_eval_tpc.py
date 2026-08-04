"""``evaluate_one``'s per-query score must stay a mirror of ``eval_tpc.py``, never a second opinion.

The harness helper reimplements the official preference snippets and the official weighting
inline, because it scores one query at a time while ``eval_tpc.py`` aggregates a split. That
duplication is load-bearing: ``rehearse_phase2`` feeds ``overall_true`` into
``phase2_record_baseline``, so a recorded ledger row -- the thing that promotes a change through
the gate -- carries this number, not ``eval_tpc.py``'s. If the two ever drift, the gate is
scoring against a private evaluator, which CLAUDE.md's "Upstream evaluator parity" invariant
forbids. These tests fail the moment they disagree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import eval_tpc
import solve_script_with_harness as hb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HARNESS_SOURCE = PROJECT_ROOT / "agent_env" / "scripts" / "solve_script_with_harness.py"


def _local_default_pr_snippets() -> list[str]:
    source = HARNESS_SOURCE.read_text(encoding="utf-8")
    start = source.index("default_pr = [")
    end = source.index("scores: list[float] = []", start)
    return re.findall(r'"""(.*?)"""', source[start:end], re.DOTALL)


def test_local_preference_snippets_are_the_official_ones():
    local = _local_default_pr_snippets()

    assert len(local) == len(eval_tpc.DEFAULT_PR)
    for mine, official in zip(local, eval_tpc.DEFAULT_PR):
        assert mine.strip() == official.strip()


@pytest.fixture
def passing_plan(one_query) -> dict:
    """A small plan with attractions, all three meals, and one innercity transport leg, so
    every preference term evaluates to something other than a degenerate zero."""
    return {
        "people_number": 1,
        "start_city": one_query.get("start_city", "Shanghai"),
        "target_city": one_query.get("target_city", "Beijing"),
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {"type": "breakfast", "position": "A", "start_time": "08:00",
                     "end_time": "09:00", "transports": []},
                    {"type": "attraction", "position": "B", "start_time": "10:00",
                     "end_time": "12:00", "transports": [
                         {"mode": "metro", "start_time": "09:10", "end_time": "09:50",
                          "cost": 5, "distance": 8.0}]},
                    {"type": "lunch", "position": "C", "start_time": "12:30",
                     "end_time": "13:30", "transports": []},
                    {"type": "attraction", "position": "D", "start_time": "14:00",
                     "end_time": "16:00", "transports": []},
                    {"type": "dinner", "position": "E", "start_time": "18:00",
                     "end_time": "19:00", "transports": []},
                ],
            }
        ],
    }


def _harness_pr_scores(plan: dict) -> tuple[float, float, float]:
    """Run the harness's own snippets in the harness's own execution environment.

    ``evaluate_one`` only reaches its inline scorer after a full schema/commonsense/logic pass,
    which needs real environment data, so this reproduces that scorer's environment rather than
    mocking three evaluators. Paired with the snippet-identity test above, it checks the part
    text comparison cannot: that the ``func_dict`` bindings, the clamp, and the
    exception-to-zero fallback yield the same numbers ``eval_tpc.py`` would produce.
    """
    from copy import deepcopy

    from chinatravel.symbol_verification.concept_func import func_dict

    scores = []
    for constraint in _local_default_pr_snippets():
        vars_dict = deepcopy(func_dict)
        vars_dict["plan"] = plan
        try:
            exec(constraint, {"__builtins__": {"set": set}}, vars_dict)
            scores.append(max(0.0, min(1.0, float(vars_dict.get("result", 0.0)))))
        except Exception:
            scores.append(0.0)
    return scores[0] * 100.0, scores[1] * 100.0, scores[2] * 100.0


def test_preference_terms_match_the_official_helper(passing_plan):
    official = eval_tpc._official_default_pr_scores_for_plan(passing_plan)
    dav, att, ddr = _harness_pr_scores(passing_plan)

    assert (dav, att, ddr) == pytest.approx(
        (official[0] * 100.0, official[1] * 100.0, official[2] * 100.0)
    )
    # Guard against a plan that zeroes every term, which would pass vacuously.
    assert max(dav, att, ddr) > 0.0


def test_overall_weighting_matches_eval_tpc():
    """The official aggregate: 0.1 MicEPR + 0.1 MacEPR + 0.25 C-LPR + 0.05 each DAV/ATT/DDR + 0.4 FPR."""
    source = HARNESS_SOURCE.read_text(encoding="utf-8")
    weights = re.findall(
        r"overall_true = \(\s*(.*?)\s*\)", source, re.DOTALL
    )
    assert weights, "evaluate_one no longer computes overall_true"
    terms = [t.strip() for t in weights[0].split("+")]

    assert terms == [
        "0.1 * micro_comm",
        "0.1 * macro_comm",
        "0.25 * conditional_micro_logi",
        "0.05 * dav_true",
        "0.05 * att_true",
        "0.05 * ddr_true",
        "0.4 * fpr_true",
    ]

    eval_tpc_source = (PROJECT_ROOT / "eval_tpc.py").read_text(encoding="utf-8")
    assert (
        "final_score=0.1*micro_comm+0.1*macro_comm+0.25*conditional_micro_logi"
        "+0.05*scores['DAV']+0.05*scores['ATT']+0.05*scores['DDR']+0.4*fpr"
    ) in eval_tpc_source
