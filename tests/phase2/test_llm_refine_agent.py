"""Unit tests for TPCAgent's Stage 3 LLM refine primitives (ground_and_check,
apply_refine_edits, and the typed _refine_* edit ops).

These use a bare ``TPCAgent`` instance (``__new__``, no WorldEnv) with a stubbed
``_get_transport`` returning zero travel time (same pattern as test_resequence_day.py), so the
tests exercise only the pure grounding/relegging logic, not a real transport graph.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd  # noqa: E402

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent  # noqa: E402


class _FakePool:
    """Minimal WorldEnv attractions/restaurants stand-in exposing just the ``.select`` shape
    ``_lookup_poi_open_bounds`` calls -- enough to test the roadmap Next step 7 bucket-1 fix
    (snapping a proposed shift into a POI's real opening hours) without a real WorldEnv."""

    def __init__(self, rows):
        self._df = pd.DataFrame(rows)

    def select(self, city, key, func):
        return self._df


def _env_with_hours(attractions=None, restaurants=None):
    from types import SimpleNamespace
    return SimpleNamespace(
        attractions=_FakePool(attractions or []),
        restaurants=_FakePool(restaurants or []),
    )


def _bare_agent(zero_travel=True):
    agent = TPCAgent.__new__(TPCAgent)
    # Phase 2's no-oracle path: ground_and_check must route through evaluate_parsed_constraints,
    # not the oracle's hard_logic_py (which these synthetic queries don't carry).
    agent.use_oracle = False
    agent.env = None
    agent.lang = "en"
    agent._last_solve_constraints = None
    agent._injected_variants = None
    if zero_travel:
        agent._get_transport = lambda env, city, frm, to, depart, people: ([], depart)
    return agent


def _day_plan():
    return {
        "itinerary": [
            {
                "day": 1,
                "activities": [
                    {"type": "attraction", "position": "Museum", "start_time": "09:00",
                     "end_time": "10:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                    {"type": "lunch", "position": "Cafe X", "start_time": "12:00",
                     "end_time": "13:00", "price": 20, "cost": 20, "tickets": 1, "transports": []},
                    {"type": "attraction", "position": "Park Y", "start_time": "14:00",
                     "end_time": "15:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                    {"type": "accommodation", "position": "Hotel Z", "start_time": "20:00",
                     "end_time": "24:00", "price": 100, "cost": 100, "rooms": 1, "room_type": 2,
                     "tickets": 1, "transports": []},
                ],
            }
        ]
    }


QUERY = {"target_city": "Shenzhen", "people_number": 1, "uid": "test_uid"}


# --- apply_refine_edits dispatch --------------------------------------------------------------

def test_apply_refine_edits_drops_unknown_op():
    agent = _bare_agent()
    trial, applied, reasons = agent.apply_refine_edits(_day_plan(), QUERY, [{"op": "rewrite_everything"}])
    assert applied == 0
    assert trial == _day_plan()
    assert reasons == [{"op": "rewrite_everything", "committed": False, "reason": "unknown_op"}]


def test_apply_refine_edits_caps_at_max_edits():
    agent = _bare_agent()
    edits = [{"op": "drop_activity", "day": 1, "location": "Museum"}] * 20
    # Each successive attempt after the first drop targets a name no longer present -> only the
    # cap matters here, not whether every attempt individually succeeds.
    trial, applied, reasons = agent.apply_refine_edits(_day_plan(), QUERY, edits)
    assert applied <= agent._REFINE_MAX_EDITS
    assert len(reasons) == agent._REFINE_MAX_EDITS


def test_apply_refine_edits_never_raises_on_malformed_edit():
    agent = _bare_agent()
    trial, applied, reasons = agent.apply_refine_edits(_day_plan(), QUERY, [None, 42, {"op": None}, "x"])
    assert applied == 0
    assert all(r["committed"] is False for r in reasons)


# --- shift_activity_window ---------------------------------------------------------------------

def test_shift_activity_window_retimes_named_activity():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Museum", "start_time": "10:30", "end_time": "11:30"},
        "Shenzhen", 1,
    )
    assert ok is True
    act = plan["itinerary"][0]["activities"][0]
    assert act["start_time"] == "10:30" and act["end_time"] == "11:30"


def test_shift_activity_window_drops_when_location_not_found():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Nonexistent Place", "start_time": "10:30", "end_time": "11:30"},
        "Shenzhen", 1,
    )
    assert ok is False


def test_shift_activity_window_rejects_empty_window():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Museum", "start_time": "11:00", "end_time": "10:00"},
        "Shenzhen", 1,
    )
    assert ok is False


# --- shift_activity_window snapping to real opening hours (roadmap Next step 7, bucket 1) -------
#
# Before this fix, apply_refine_edits never consulted WorldEnv opening hours at all: a proposal
# outside a POI's real hours was either trialed verbatim (and only caught much later by the
# checker's commonsense hours check, landing in "not_accepted_or_regressed") or, if transport
# happened to make it infeasible, dropped for an unrelated reason. Snapping here lets a
# plausible-but-slightly-off-hours proposal still ground and commit.

def _single_activity_day_plan():
    # No neighbours to complicate the transport/next-activity checks -- isolates the
    # opening-hours snap itself from the (unrelated, no-cascading-shift) downstream-conflict path.
    return {"itinerary": [{"day": 1, "activities": [
        {"type": "attraction", "position": "Museum", "start_time": "09:00", "end_time": "10:00",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
    ]}]}


def test_shift_activity_window_snaps_to_poi_opening_hours():
    agent = _bare_agent()
    agent.env = _env_with_hours(attractions=[{"name": "Museum", "opentime": "09:00", "endtime": "18:00"}])
    plan = _single_activity_day_plan()
    diag = []
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Museum", "start_time": "07:00", "end_time": "20:00"},
        "Shenzhen", 1, diag,
    )
    assert ok is True
    assert diag == ["committed"]
    act = plan["itinerary"][0]["activities"][0]
    assert act["start_time"] == "09:00" and act["end_time"] == "18:00"


def test_shift_activity_window_drops_when_poi_closed_during_requested_window():
    agent = _bare_agent()
    agent.env = _env_with_hours(attractions=[{"name": "Museum", "opentime": "09:00", "endtime": "18:00"}])
    plan = _single_activity_day_plan()
    diag = []
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Museum", "start_time": "02:00", "end_time": "03:00"},
        "Shenzhen", 1, diag,
    )
    assert ok is False
    assert diag == ["poi_closed_during_requested_window"]


def test_shift_activity_window_without_env_ignores_hours():
    # No WorldEnv (bare-agent unit tests) -> _lookup_poi_open_bounds returns None -> no snapping,
    # same behavior as before this fix.
    agent = _bare_agent()
    plan = _day_plan()
    diag = []
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Museum", "start_time": "10:30", "end_time": "11:30"},
        "Shenzhen", 1, diag,
    )
    assert ok is True
    assert diag == ["committed"]
    act = plan["itinerary"][0]["activities"][0]
    assert act["start_time"] == "10:30" and act["end_time"] == "11:30"


def test_shift_activity_window_skips_hours_lookup_for_accommodation_based_meal():
    # Hotel breakfast (tickets=0, position=hotel name) must never be looked up against the
    # restaurant pool, even when the hotel's name happens to text-match a restaurant catalog entry
    # (Copilot review finding on this PR) -- it has no tracked hours in this dataset.
    agent = _bare_agent()
    agent.env = _env_with_hours(restaurants=[{"name": "Grand Cafe", "opentime": "09:00", "endtime": "10:00"}])
    plan = {"itinerary": [{"day": 1, "activities": [
        {"type": "breakfast", "position": "Grand Cafe", "start_time": "07:00", "end_time": "08:00",
         "price": 0, "cost": 0, "tickets": 0, "transports": []},
    ]}]}
    diag = []
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Grand Cafe", "start_time": "06:00", "end_time": "10:30"},
        "Shenzhen", 1, diag,
    )
    assert ok is True
    assert diag == ["committed"]
    act = plan["itinerary"][0]["activities"][0]
    # Not snapped to the restaurant's 09:00-10:00 hours -- applied verbatim, same as before this PR.
    assert act["start_time"] == "06:00" and act["end_time"] == "10:30"


def test_lookup_poi_open_bounds_returns_none_for_accommodation_based_meal():
    agent = _bare_agent()
    agent.env = _env_with_hours(restaurants=[{"name": "Grand Cafe", "opentime": "09:00", "endtime": "10:00"}])
    assert agent._lookup_poi_open_bounds("Shenzhen", "Grand Cafe", "breakfast", tickets=0) is None
    assert agent._lookup_poi_open_bounds("Shenzhen", "Grand Cafe", "breakfast", tickets=1) == (540, 600)


def test_lookup_poi_open_bounds_prefers_pool_data_over_select():
    from types import SimpleNamespace

    class _DataOnlyPool:
        def __init__(self, df):
            self.data = {"Shenzhen": df}

        def select(self, city, key, func):
            raise AssertionError("select() should not be called when .data[city] is available")

    agent = _bare_agent()
    df = pd.DataFrame([{"name": "Museum", "opentime": "09:00", "endtime": "18:00"}])
    agent.env = SimpleNamespace(attractions=_DataOnlyPool(df), restaurants=_FakePool([]))
    assert agent._lookup_poi_open_bounds("Shenzhen", "Museum", "attraction") == (540, 1080)


def test_shift_activity_window_records_reason_for_missing_location():
    agent = _bare_agent()
    plan = _day_plan()
    diag = []
    ok = agent._refine_shift_activity(
        plan, {"day": 1, "location": "Nonexistent Place", "start_time": "10:30", "end_time": "11:30"},
        "Shenzhen", 1, diag,
    )
    assert ok is False
    assert diag == ["location_not_found"]


# --- apply_refine_edits per-edit diagnostics (roadmap Next step 7, bucket 1) --------------------

def test_apply_refine_edits_reports_committed_reason():
    agent = _bare_agent()
    agent.env = _env_with_hours(attractions=[{"name": "Museum", "opentime": "09:00", "endtime": "18:00"}])
    trial, applied, reasons = agent.apply_refine_edits(
        _day_plan(), QUERY,
        [{"op": "shift_activity_window", "day": 1, "location": "Museum",
          "start_time": "10:30", "end_time": "11:30"}],
    )
    assert applied == 1
    assert reasons == [{"op": "shift_activity_window", "committed": True, "reason": "committed"}]


def test_apply_refine_edits_reports_failure_reason():
    agent = _bare_agent()
    trial, applied, reasons = agent.apply_refine_edits(
        _day_plan(), QUERY,
        [{"op": "shift_activity_window", "day": 1, "location": "Nowhere",
          "start_time": "10:30", "end_time": "11:30"}],
    )
    assert applied == 0
    assert reasons == [{"op": "shift_activity_window", "committed": False, "reason": "location_not_found"}]


# --- _refine_feasible_windows / ground_and_check wiring (roadmap Next step 7, bucket 1) ---------

def test_refine_feasible_windows_reports_real_opening_hours():
    agent = _bare_agent()
    agent.env = _env_with_hours(attractions=[{"name": "Museum", "opentime": "09:00", "endtime": "18:00"}])
    windows = agent._refine_feasible_windows(QUERY, _day_plan())
    museum = next(w for w in windows if w["position"] == "Museum")
    assert museum["open"] == "09:00" and museum["close"] == "18:00"


def test_ground_and_check_failure_summary_includes_feasible_windows():
    agent = _bare_agent()
    agent.env = _env_with_hours(attractions=[{"name": "Museum", "opentime": "09:00", "endtime": "18:00"}])
    agent._last_solve_constraints = {"required_attractions": ["Not In Plan"]}
    _accepted, _grounded, _key, failure = agent.ground_and_check(_day_plan(), QUERY)
    assert "activity_feasible_windows" in failure
    positions = [w["position"] for w in failure["activity_feasible_windows"]]
    assert "Museum" in positions


def test_ground_and_check_skips_feasible_windows_when_nothing_failed():
    # Computing feasible windows costs a _get_transport lookup per activity (Copilot review
    # finding) -- it must be skipped once nothing failed, not spent and discarded.
    agent = _bare_agent()
    agent.env = _env_with_hours(attractions=[{"name": "Museum", "opentime": "09:00", "endtime": "18:00"}])
    agent._last_solve_constraints = {"required_attractions": ["Museum"]}
    agent._schema_ok = lambda query, plan: True
    agent._commonsense_failure_columns = lambda query, plan: []
    _accepted, _grounded, _key, failure = agent.ground_and_check(_day_plan(), QUERY)
    assert failure["activity_feasible_windows"] == []


def test_describe_check_failure_skips_feasible_windows_without_env():
    agent = _bare_agent()  # env=None
    agent._last_solve_constraints = {"required_attractions": ["Not In Plan"]}
    _accepted, _grounded, _key, failure = agent.ground_and_check(_day_plan(), QUERY)
    assert failure["activity_feasible_windows"] == []


# --- sharper failure_summary: failed_clauses / space_gaps (roadmap Next step 7 bucket 2) --------

def test_describe_failed_clause_items_names_the_specific_missing_poi():
    agent = _bare_agent()
    plan = _day_plan()
    # "Museum" is in the plan (satisfied) -- only the missing name should be reported.
    clauses = agent._describe_failed_clause_items(
        "required_attractions", ["Not In Plan", "Museum"], plan, "Shenzhen")
    assert clauses == [{"family": "required_attractions", "detail": "Not In Plan"}]


def test_describe_failed_clause_items_names_the_specific_unmet_window():
    agent = _bare_agent()
    plan = _day_plan()  # Museum is scheduled 09:00-10:00
    window = {"location": "Museum", "earliest": "11:00"}
    clauses = agent._describe_failed_clause_items("activity_time_windows", [window], plan, "Shenzhen")
    assert clauses == [{"family": "activity_time_windows", "location": "Museum", "item": window}]


def test_describe_failed_clause_items_empty_when_item_is_satisfied():
    agent = _bare_agent()
    plan = _day_plan()
    clauses = agent._describe_failed_clause_items("required_attractions", ["Museum"], plan, "Shenzhen")
    assert clauses == []


def test_describe_failed_clause_items_skips_families_with_no_per_item_name():
    # budgets/room_type/etc. are scalar or dict-shaped -- no single POI/location to name, so they
    # stay family-level only (in failed_constraint_families), never in failed_clauses.
    agent = _bare_agent()
    plan = _day_plan()
    assert agent._describe_failed_clause_items("budgets", {"sightseeing": 0}, plan, "Shenzhen") == []


def test_describe_check_failure_includes_failed_clauses():
    agent = _bare_agent()
    plan = _day_plan()
    failure = agent._describe_check_failure(
        {"target_city": "Shenzhen"}, {"required_attractions": ["Not In Plan"]}, plan)
    assert failure["failed_clauses"] == [{"family": "required_attractions", "detail": "Not In Plan"}]


def test_find_space_gaps_reports_broken_legs_in_plan_order():
    agent = _bare_agent()
    plan = _day_plan()  # Museum -> Cafe X -> Park Y -> Hotel Z, every activity's transports == []
    gaps = agent._find_space_gaps(plan)
    assert [g["position"] for g in gaps] == ["Cafe X", "Park Y", "Hotel Z"]
    assert gaps[0]["expected_from"] == "Museum"
    assert gaps[0]["day"] == 1


def test_find_space_gaps_empty_when_legs_present():
    agent = _bare_agent()
    plan = _day_plan()
    for day in plan["itinerary"]:
        for act in day["activities"]:
            act["transports"] = [{"start": "Museum", "end": act["position"]}]
    # Legs are all self-consistent-looking stand-ins, not real grounded transports, but each one at
    # least starts/ends somewhere -- the point here is _transport_leg_valid only flags an *empty*
    # or mis-anchored leg, not the absence of a real route.
    plan["itinerary"][0]["activities"][0]["transports"] = []  # first activity has no predecessor
    gaps = agent._find_space_gaps(plan)
    # Every non-first activity's leg now starts at "Museum" and ends at its own position, so only
    # legs whose *previous* activity was not Museum would still mismatch -- Cafe X (prev=Museum) is
    # fine, but Park Y/Hotel Z's legs claim to start at Museum while the previous activity ends
    # elsewhere, so they remain gaps.
    assert [g["position"] for g in gaps] == ["Park Y", "Hotel Z"]


def test_describe_check_failure_includes_space_gaps_when_commonsense_flags_it():
    agent = _bare_agent()
    plan = _day_plan()
    agent._commonsense_failure_columns = (
        lambda query, plan: ["Invalid Transport information across positions"])
    agent._schema_ok = lambda query, plan: True
    failure = agent._describe_check_failure(QUERY, {}, plan)
    assert failure["failed_commonsense_checks"] == ["Invalid Transport information across positions"]
    assert [g["position"] for g in failure["space_gaps"]] == ["Cafe X", "Park Y", "Hotel Z"]


def test_describe_check_failure_skips_space_gaps_when_commonsense_ok():
    agent = _bare_agent()
    plan = _day_plan()
    agent._commonsense_failure_columns = lambda query, plan: []
    agent._schema_ok = lambda query, plan: True
    failure = agent._describe_check_failure(QUERY, {}, plan)
    assert failure["space_gaps"] == []


# --- drop_activity -------------------------------------------------------------------------------

def test_drop_activity_removes_named_activity_and_reconnects():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_drop_activity(plan, {"day": 1, "location": "Cafe X"}, "Shenzhen", 1)
    assert ok is True
    positions = [a.get("position") for a in plan["itinerary"][0]["activities"]]
    assert "Cafe X" not in positions
    assert positions == ["Museum", "Park Y", "Hotel Z"]


def test_drop_activity_never_empties_a_day():
    agent = _bare_agent()
    plan = {"itinerary": [{"day": 1, "activities": [
        {"type": "attraction", "position": "Only One", "start_time": "09:00", "end_time": "10:00",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
    ]}]}
    ok = agent._refine_drop_activity(plan, {"day": 1, "location": "Only One"}, "Shenzhen", 1)
    assert ok is False
    assert len(plan["itinerary"][0]["activities"]) == 1


# --- swap_activity -------------------------------------------------------------------------------

def test_swap_activity_swaps_two_named_activities():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_swap_activity(
        plan, {"day": 1, "location_a": "Museum", "location_b": "Park Y"}, "Shenzhen", 1)
    assert ok is True
    positions = [a.get("position") for a in plan["itinerary"][0]["activities"]]
    assert positions[:3] == ["Park Y", "Cafe X", "Museum"]


def test_swap_activity_drops_unknown_location():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_swap_activity(
        plan, {"day": 1, "location_a": "Museum", "location_b": "Nowhere"}, "Shenzhen", 1)
    assert ok is False


# --- reorder_day -----------------------------------------------------------------------------

def test_reorder_day_applies_explicit_order():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_reorder_day(
        plan, {"day": 1, "order": ["Park Y", "Museum", "Cafe X"]}, "Shenzhen", 1)
    assert ok is True
    positions = [a.get("position") for a in plan["itinerary"][0]["activities"]]
    assert positions[:3] == ["Park Y", "Museum", "Cafe X"]
    assert positions[3] == "Hotel Z"  # fixed anchor untouched


def test_reorder_day_noop_when_already_in_order():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_reorder_day(
        plan, {"day": 1, "order": ["Museum", "Cafe X", "Park Y"]}, "Shenzhen", 1)
    assert ok is False


def test_reorder_day_ignores_unmatched_names_but_still_reorders_known_ones():
    agent = _bare_agent()
    plan = _day_plan()
    ok = agent._refine_reorder_day(
        plan, {"day": 1, "order": ["Park Y", "Nonexistent"]}, "Shenzhen", 1)
    assert ok is True
    positions = [a.get("position") for a in plan["itinerary"][0]["activities"]]
    assert positions[0] == "Park Y"


# --- ground_and_check --------------------------------------------------------------------------

def test_ground_and_check_uses_last_solve_constraints_when_present():
    agent = _bare_agent()
    agent._last_solve_constraints = {"required_attractions": ["Museum"]}
    plan = _day_plan()
    accepted, grounded, key, failure = agent.ground_and_check(plan, QUERY)
    assert isinstance(grounded, dict)
    assert isinstance(failure, dict)
    assert "failed_constraint_families" in failure


def test_ground_and_check_reports_failed_family_when_constraint_unmet():
    agent = _bare_agent()
    agent._last_solve_constraints = {"required_attractions": ["Not In Plan"]}
    plan = _day_plan()
    accepted, grounded, key, failure = agent.ground_and_check(plan, QUERY)
    assert accepted is False
    assert "required_attractions" in failure["failed_constraint_families"]


def test_ground_and_check_family_not_failed_when_constraint_met():
    # A synthetic minimal plan won't pass the full schema/commonsense gate (real plans have far
    # more required fields), so this checks the family-level failure summary specifically, not
    # overall `accepted` -- that's covered by the "unmet" case above, which fails outright before
    # schema/commonsense are even consulted.
    agent = _bare_agent()
    agent._last_solve_constraints = {"required_attractions": ["Museum"]}
    plan = _day_plan()
    _accepted, _grounded, _key, failure = agent.ground_and_check(plan, QUERY)
    assert "required_attractions" not in failure["failed_constraint_families"]


def test_ground_and_check_never_raises_on_bad_query():
    agent = _bare_agent()
    accepted, grounded, key, failure = agent.ground_and_check(_day_plan(), {})
    assert accepted in (True, False)


# --- _last_solve_constraints tracking (regression for a Copilot review finding on PR #32) ------
#
# consider() must export _last_solve_constraints from the SAME bucket (best_accepted or best) as
# the plan it hands to _set_timeout_recovery_plan -- not unconditionally from the current call's
# constraints. Otherwise a later variant/candidate that only improves the raw search-key leader
# (best["plan"]), without unseating a higher-ranked best_accepted from an EARLIER variant, would
# overwrite _last_solve_constraints with constraints that don't match the exported best_accepted
# plan, so ground_and_check would re-check that plan against the wrong constraint set.

def test_last_solve_constraints_tracks_exported_best_accepted_not_a_later_candidate():
    import os
    import time

    agent = _bare_agent(zero_travel=False)
    agent.max_restarts = 0
    agent.solve_budget_sec = 60.0
    agent.start_clock = time.time()
    agent.seed_salt = "0"
    agent._transport_constraints = {}

    # Two branch-local variants with distinguishable constraints; both "plans" are accepted by the
    # stubbed checker, but rank oppositely under the raw search key (_eval_proxy, used for `best`)
    # vs. the accepted preference key (_accepted_eval_key, used for `best_accepted`) -- variant 2's
    # plan is the stronger *raw* candidate but the weaker *accepted* one.
    agent._constraint_variants = lambda query: [{"v": 1}, {"v": 2}]
    agent._make_checker = lambda query, constraints: (lambda plan: (1, 1))
    agent._build_plan = lambda query, constraints=None, params=None: {"_v": (constraints or {}).get("v")}
    agent._repair_params = lambda constraints: []
    agent._eval_proxy = lambda plan: 1.0 if plan.get("_v") == 1 else 100.0
    agent._accepted_eval_key = lambda plan: (10.0,) if plan.get("_v") == 1 else (1.0,)
    agent._plan_total_cost = lambda plan: 0.0
    agent._pack_plan = lambda plan, *a, **k: plan  # packing is out of scope for this bookkeeping

    os.environ["TPC_USE_CP_SOLVER"] = "0"
    os.environ["TPC_SOLVE_STOP_AT_ACCEPT"] = "0"
    try:
        result = agent._solve({"uid": "last_solve_constraints_regression"})
    finally:
        os.environ.pop("TPC_USE_CP_SOLVER", None)
        os.environ.pop("TPC_SOLVE_STOP_AT_ACCEPT", None)

    # best_accepted stays variant 1's plan (higher _accepted_eval_key); the recovery plan and the
    # tracked constraints must both describe that same plan, not variant 2's.
    assert result.get("_v") == 1
    assert agent._last_solve_constraints == {"v": 1}
    recovered = agent.get_timeout_recovery_plan()
    assert recovered.get("_v") == 1


# --- insert_activity (roadmap P6) -----------------------------------------------------------------
#
# The one op the other four cannot express: adding a WorldEnv-grounded activity for a POI not yet
# in the plan. Reuses _day_plan()/QUERY -- Museum (09-10) / Cafe X lunch (12-13) / Park Y (14-15) /
# Hotel Z accommodation (20-24), all on day 1.

def test_insert_activity_adds_a_new_poi_between_two_existing_activities():
    agent = _bare_agent()
    agent.env = _env_with_hours(attractions=[
        {"name": "Gallery", "opentime": "08:00", "endtime": "20:00", "price": 15},
    ])
    plan = _day_plan()
    ok = agent._refine_insert_activity(
        plan, {"day": 1, "location": "Gallery", "activity_type": "attraction",
               "start_time": "11:00", "end_time": "11:45"},
        "Shenzhen", 1,
    )
    assert ok is True
    positions = [a.get("position") for a in plan["itinerary"][0]["activities"]]
    assert positions == ["Museum", "Gallery", "Cafe X", "Park Y", "Hotel Z"]
    gallery = plan["itinerary"][0]["activities"][1]
    assert gallery["type"] == "attraction"
    assert gallery["start_time"] == "11:00" and gallery["end_time"] == "11:45"
    # The successor's inbound leg must be recomputed from the new activity, not left stale.
    assert plan["itinerary"][0]["activities"][2]["transports"] == []  # zero-travel stub


def test_insert_activity_drops_when_poi_is_not_in_the_catalog():
    agent = _bare_agent()
    agent.env = _env_with_hours(attractions=[])
    plan = _day_plan()
    diag = []
    ok = agent._refine_insert_activity(
        plan, {"day": 1, "location": "Nonexistent Gallery", "activity_type": "attraction",
               "start_time": "11:00", "end_time": "11:45"},
        "Shenzhen", 1, diag,
    )
    assert ok is False
    assert diag == ["poi_not_found_in_catalog"]
    assert plan == _day_plan()


def test_insert_activity_drops_when_the_poi_is_already_present():
    agent = _bare_agent()
    agent.env = _env_with_hours(attractions=[
        {"name": "Museum", "opentime": "08:00", "endtime": "20:00", "price": 15},
    ])
    plan = _day_plan()
    diag = []
    ok = agent._refine_insert_activity(
        plan, {"day": 1, "location": "Museum", "activity_type": "attraction",
               "start_time": "11:00", "end_time": "11:45"},
        "Shenzhen", 1, diag,
    )
    assert ok is False
    assert diag == ["already_present"]


def test_insert_activity_refuses_appending_after_the_days_final_intercity_departure():
    agent = _bare_agent()
    agent.env = _env_with_hours(attractions=[
        {"name": "Gallery", "opentime": "08:00", "endtime": "20:00", "price": 15},
    ])
    plan = {"itinerary": [{"day": 1, "activities": [
        {"type": "attraction", "position": "Museum", "start_time": "09:00", "end_time": "10:00",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
        {"type": "airplane", "From": "Shenzhen", "To": "Beijing", "start_time": "18:00",
         "end_time": "20:00", "price": 500, "cost": 500, "tickets": 1, "transports": []},
    ]}]}
    diag = []
    ok = agent._refine_insert_activity(
        plan, {"day": 1, "location": "Gallery", "activity_type": "attraction"},
        "Shenzhen", 1, diag,
    )
    assert ok is False
    assert diag == ["cannot_append_after_intercity_departure"]


def test_insert_activity_drops_on_bad_day_or_type():
    agent = _bare_agent()
    plan = _day_plan()
    assert agent._refine_insert_activity(
        plan, {"day": 99, "location": "Gallery", "activity_type": "attraction"}, "Shenzhen", 1) is False
    assert agent._refine_insert_activity(
        plan, {"day": 1, "location": "Gallery", "activity_type": "not_a_real_type"}, "Shenzhen", 1) is False
    assert agent._refine_insert_activity(
        plan, {"day": 1, "location": "", "activity_type": "attraction"}, "Shenzhen", 1) is False


def test_apply_refine_edits_dispatches_insert_activity():
    agent = _bare_agent()
    agent.env = _env_with_hours(restaurants=[
        {"name": "Noodle Place", "opentime": "10:00", "endtime": "22:00", "price": 20},
    ])
    trial, applied, reasons = agent.apply_refine_edits(_day_plan(), QUERY, [
        {"op": "insert_activity", "day": 1, "location": "Noodle Place",
         "activity_type": "dinner", "start_time": "18:00", "end_time": "19:00"},
    ])
    assert applied == 1
    assert reasons == [{"op": "insert_activity", "committed": True, "reason": "committed"}]
    positions = [a.get("position") for a in trial["itinerary"][0]["activities"]]
    assert "Noodle Place" in positions
