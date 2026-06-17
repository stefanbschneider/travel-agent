#!/usr/bin/env python
"""Self-contained tests for the CP-SAT solver tier.

Run: .venv/bin/python scripts/test_solver.py
Exits non-zero on the first failed assertion. No pytest dependency (the repo is
script-based). Tests assert behavior (extraction, oracle-faithful matching,
meal-window feasibility, end-to-end solve), not incidental defaults.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "chinatravel")):
    if p not in sys.path:
        sys.path.insert(0, p)

import parse_constraints
from agent.tpc_agent.solver_constraints import solver_constraint_variants
from agent.tpc_agent import cp_solver as C
from agent.tpc_agent import cp_candidates as CC

DATA = os.path.join(ROOT, "chinatravel/data/en/TPC_IJCAI_2026_phase1_EN")


def _load(uid):
    q = json.load(open(os.path.join(DATA, f"{uid}.json")))
    q.setdefault("uid", uid)
    return q


def test_extractor_branch_locality():
    # Disjunctive query -> two branch-local variants; constraints do not leak across arms.
    q = _load("20250323095147120434")
    v = solver_constraint_variants(q, parse_constraints.parse_query(q), use_oracle=True)
    assert len(v) == 2, f"expected 2 branches, got {len(v)}"
    assert v[0]["budgets"]["sightseeing"] == 500.0, v[0].get("budgets")
    assert v[1]["poi_distance_hotel"][0]["reference"] == "Nellie's Family Center (Chengdu Global Store)", v[1]
    assert v[1]["poi_distance_hotel"][0]["distance_km"] == 6.26461094462571, v[1]
    # branch locality: the hotel-distance arm must not carry the budget arm's cap
    assert "poi_distance_hotel" not in v[0], "branch leak: hotel distance bled into budget arm"


def test_extractor_intercity_and_windows():
    q = _load("20250323003106691638")
    v = solver_constraint_variants(q, parse_constraints.parse_query(q), use_oracle=True)
    assert len(v) == 1, v
    assert v[0]["budgets"]["inner_transport"] == 50.0, v[0]
    assert v[0]["intercity_mode"]["outbound"] == "train", v[0]
    assert v[0]["intercity_mode"]["return"] == "train", v[0]

    q2 = _load("20250322204343211249")
    v2 = solver_constraint_variants(q2, parse_constraints.parse_query(q2), use_oracle=True)
    assert len(v2) == 2, v2
    assert v2[0]["required_hotels"] == ["Asiam International Hotel Chongqing Jiefangbei Hongya Cave"], v2[0]
    w = v2[1]["activity_time_windows"][0]
    assert w["location"] == "Chongqing Haichang Caribbean Water World", v2[1]
    assert w["end_after"] == "14:00", w


def test_exact_case_sensitive_matching():
    # Oracle uses case-sensitive set membership: casefolding would let CP pick a
    # candidate the oracle rejects (e.g. data "Swimming Pool" vs literal "Swimming pool").
    assert C._eq_norm("park", "park") is True
    assert C._eq_norm(" Museum/Memorial Hall ", "Museum/Memorial Hall") is True
    assert C._eq_norm("Swimming pool", "Swimming Pool") is False
    assert C._eq_norm("Hot pot", "hot pot") is False
    assert CC._eq_norm("Hot pot", "hot pot") is False


def test_meal_window_overlap():
    # A 60-min meal need only fit within the overlap, not span the whole window.
    # Restaurant open 12:00-15:00 can host lunch (11:00-14:00) at 12:00-13:00.
    assert C._open_covers(12 * 60, 15 * 60, C.LUNCH_OPEN, C.LUNCH_CLOSE) is True
    # Restaurant open 17:30-23:00 can host dinner (17:00-20:00).
    assert C._open_covers(17 * 60 + 30, 23 * 60, C.DINNER_OPEN, C.DINNER_CLOSE) is True
    # Restaurant closing 11:30 cannot host a 60-min lunch ending by 14:00 within 11:00-.
    assert C._open_covers(8 * 60, 11 * 60 + 30, C.LUNCH_OPEN, C.LUNCH_CLOSE) is False
    # Overnight wrap (e.g. 18:00-02:00) still covers dinner.
    assert C._open_covers(18 * 60, 2 * 60, C.DINNER_OPEN, C.DINNER_CLOSE) is True


def test_required_presence_augmentation():
    aug = C._augment_required_presence({
        "activity_time_windows": [{"location": "A", "earliest": "09:00"}],
        "stay_duration": [{"location": "B", "min_minutes": 120}],
        "position_presence": ["C"],
    })
    for name in ("A", "B", "C"):
        assert name in aug["required_attractions"], (name, aug["required_attractions"])
        assert name in aug["required_restaurants"], (name, aug["required_restaurants"])


def test_end_to_end_cp_solve():
    from chinatravel.environment.world_env import WorldEnv
    from agent.tpc_agent.tpc_agent import TPCAgent

    class _Stub:
        name = "TPCLLM"

    agent = TPCAgent(env=WorldEnv(lang="en"), backbone_llm=_Stub(), lang="en")
    # Two queries the legacy search left unsolved that the CP tier cracks.
    solved = 0
    for uid in ("20250321102210325486", "20250321131454214158"):
        q = _load(uid)
        agent.reset_clock()
        for c in agent._constraint_variants(q):
            check = agent._make_checker(q, c)
            plan = C.solve_with_cp_sat(agent, q, c, check, 20)
            if plan is not None:
                passed, total = check(plan)
                assert passed == total, f"{uid}: returned plan failing check {passed}/{total}"
                solved += 1
                break
    assert solved == 2, f"CP tier solved only {solved}/2 known-solvable queries"


def main():
    tests = [
        test_extractor_branch_locality,
        test_extractor_intercity_and_windows,
        test_exact_case_sensitive_matching,
        test_meal_window_overlap,
        test_required_presence_augmentation,
        test_end_to_end_cp_solve,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
