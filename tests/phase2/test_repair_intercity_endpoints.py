"""Unit tests for the opt-in intercity endpoint grounding repair pass.

These tests use a bare ``TPCAgent`` instance (``__new__``, no WorldEnv) with a stubbed
``env.intercitytransport.select`` table and a deterministic inner-city transport stub, so they
exercise only the endpoint re-grounding logic in ``_repair_intercity_endpoints``.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent  # noqa: E402


class _FakeIntercityTransport:
    def __init__(self, rows_by_route):
        self._rows = rows_by_route

    def select(self, start_city, end_city, intercity_type, earliest_leave_time="00:00"):
        rows = list(self._rows.get((start_city, end_city, intercity_type), []))
        filtered = [
            r for r in rows if str(r.get("BeginTime", "00:00")) >= str(earliest_leave_time)
        ]
        filtered.sort(key=lambda r: str(r.get("BeginTime", "00:00")))
        return pd.DataFrame(filtered)


class _FakeEnv:
    def __init__(self, rows_by_route):
        self.intercitytransport = _FakeIntercityTransport(rows_by_route)


def _leg(frm, to, depart):
    return [{
        "start": frm,
        "end": to,
        "mode": "taxi",
        "start_time": depart,
        "end_time": depart,
        "distance": 1.0,
        "price": 10,
        "cost": 10,
    }]


def _zero_time_transport(env, city, frm, to, depart, people):
    if frm == to:
        return [], depart
    return _leg(frm, to, depart), depart


def _bare_agent(rows_by_route):
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent.env = _FakeEnv(rows_by_route)
    agent._get_transport = _zero_time_transport
    agent.solve_budget_sec = 1.0
    agent.start_clock = 0.0
    return agent


def _matches_row(activity, row, mode):
    if mode == "airplane":
        rid = "FlightID"
    else:
        rid = "TrainID"
    try:
        row_price = float(row.get("Cost"))
        activity_price = float(activity.get("price"))
        tickets = float(activity.get("tickets"))
        activity_cost = float(activity.get("cost"))
    except (TypeError, ValueError):
        return False
    return (
        activity.get("type") == mode
        and activity.get(rid) == row.get(rid)
        and activity.get("start") == row.get("From")
        and activity.get("end") == row.get("To")
        and activity.get("start_time") == row.get("BeginTime")
        and activity.get("end_time") == row.get("EndTime")
        and activity_price == row_price
        and activity_cost == row_price * tickets
    )


def _endpoint_checker(rows_by_route):
    def _row_for(route_from, route_to, activity):
        mode = activity.get("type")
        if mode not in ("airplane", "train"):
            return None
        rows = rows_by_route.get((route_from, route_to, mode), [])
        for row in rows:
            if _matches_row(activity, row, mode):
                return row
        return None

    def check(plan):
        itinerary = plan.get("itinerary", []) or []
        if not itinerary:
            return (0, 1)
        first_acts = (itinerary[0] or {}).get("activities", []) or []
        last_acts = (itinerary[-1] or {}).get("activities", []) or []
        if not first_acts or not last_acts:
            return (0, 1)

        first = first_acts[0]
        last = last_acts[-1]
        if _row_for("A", "B", first) is None:
            return (0, 1)
        if _row_for("B", "A", last) is None:
            return (0, 1)

        if len(first_acts) > 1 and first_acts[1].get("type") not in ("airplane", "train"):
            if first.get("end_time", "99:99") > first_acts[1].get("start_time", "00:00"):
                return (0, 1)
        if len(last_acts) > 1 and last_acts[-2].get("type") not in ("airplane", "train"):
            if last.get("start_time", "00:00") < last_acts[-2].get("end_time", "99:99"):
                return (0, 1)
        return (1, 1)

    return check


ROWS = {
    ("A", "B", "train"): [
        {
            "TrainID": "T_GO_1",
            "From": "A Station",
            "To": "B Station",
            "BeginTime": "06:30",
            "EndTime": "08:00",
            "Cost": 120,
        }
    ],
    ("B", "A", "train"): [
        {
            "TrainID": "T_BACK_1",
            "From": "B Station",
            "To": "A Station",
            "BeginTime": "16:30",
            "EndTime": "18:00",
            "Cost": 130,
        }
    ],
}


QUERY = {"start_city": "A", "target_city": "B", "people_number": 2}


def _base_plan():
    return {
        "itinerary": [
            {
                "activities": [
                    {
                        "type": "train",
                        "TrainID": "WRONG_GO",
                        "start": "A Station",
                        "end": "B Station",
                        "start_time": "06:30",
                        "end_time": "08:00",
                        "price": 999,
                        "cost": 1998,
                        "tickets": 2,
                        "transports": [],
                    },
                    {
                        "type": "breakfast",
                        "position": "Hotel B",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "price": 0,
                        "cost": 0,
                        "tickets": 0,
                        "transports": [],
                    },
                ]
            },
            {
                "activities": [
                    {
                        "type": "lunch",
                        "position": "Downtown",
                        "start_time": "12:00",
                        "end_time": "13:00",
                        "price": 20,
                        "cost": 40,
                        "tickets": 2,
                        "transports": [],
                    },
                    {
                        "type": "train",
                        "TrainID": "T_BACK_1",
                        "start": "B Station",
                        "end": "A Station",
                        "start_time": "16:30",
                        "end_time": "18:00",
                        "price": 130,
                        "cost": 260,
                        "tickets": 2,
                        "transports": [],
                    },
                ]
            },
        ]
    }


def test_flag_off_by_default():
    assert _bare_agent(ROWS)._repair_intercity_enabled() is False


def test_flag_reads_env(monkeypatch):
    monkeypatch.setenv("TPC_REPAIR_INTERCITY", "1")
    assert _bare_agent(ROWS)._repair_intercity_enabled() is True


def test_flag_off_pack_plan_is_byte_identical_and_pass_not_invoked(monkeypatch):
    monkeypatch.delenv("TPC_REPAIR_INTERCITY", raising=False)
    agent = _bare_agent(ROWS)
    plan = _base_plan()
    snapshot = deepcopy(plan)

    def _boom(*args, **kwargs):
        raise AssertionError("_repair_intercity_endpoints should not run when flag is off")

    agent._repair_intercity_endpoints = _boom
    packed = agent._pack_plan(plan, QUERY, {}, lambda p: (0, 1), {})
    assert packed == snapshot


def test_missing_return_endpoint_is_repaired_and_committed():
    agent = _bare_agent(ROWS)
    plan = _base_plan()
    plan["itinerary"][1]["activities"].pop()  # drop return endpoint
    check = _endpoint_checker(ROWS)
    assert agent._accepted(*check(plan)) is False

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    last = plan["itinerary"][-1]["activities"][-1]
    assert last.get("TrainID") == "T_BACK_1"
    assert last.get("start_time") == "16:30"
    assert agent._accepted(*check(plan)) is True


def test_mismatched_endpoint_is_regrounded_to_real_row():
    agent = _bare_agent(ROWS)
    plan = _base_plan()
    plan["itinerary"][-1]["activities"][-1]["price"] = 999
    plan["itinerary"][-1]["activities"][-1]["cost"] = 1998
    check = _endpoint_checker(ROWS)
    assert agent._accepted(*check(plan)) is False

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    last = plan["itinerary"][-1]["activities"][-1]
    assert last.get("TrainID") == "T_BACK_1"
    assert last.get("price") == 130
    assert last.get("cost") == 260
    assert agent._accepted(*check(plan)) is True


def test_price_match_with_wrong_total_cost_is_regrounded():
    agent = _bare_agent(ROWS)
    plan = _base_plan()
    plan["itinerary"][-1]["activities"][-1]["price"] = 130
    plan["itinerary"][-1]["activities"][-1]["cost"] = 130
    check = _endpoint_checker(ROWS)
    assert agent._accepted(*check(plan)) is False

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    last = plan["itinerary"][-1]["activities"][-1]
    assert last.get("TrainID") == "T_BACK_1"
    assert last.get("price") == 130
    assert last.get("cost") == 260
    assert agent._accepted(*check(plan)) is True


def test_no_feasible_return_row_declines_and_leaves_plan_unchanged():
    rows = deepcopy(ROWS)
    rows[("B", "A", "train")] = [
        {
            "TrainID": "T_BACK_TOO_EARLY",
            "From": "B Station",
            "To": "A Station",
            "BeginTime": "08:00",
            "EndTime": "09:00",
            "Cost": 99,
        }
    ]
    agent = _bare_agent(rows)
    plan = _base_plan()
    plan["itinerary"][1]["activities"].pop()  # missing return; only early option exists
    snapshot = deepcopy(plan)

    agent._repair_intercity_endpoints(plan, QUERY, {}, _endpoint_checker(rows))
    assert plan == snapshot


def test_broken_outbound_endpoint_is_repaired_symmetrically():
    agent = _bare_agent(ROWS)
    plan = _base_plan()
    plan["itinerary"][0]["activities"].pop(0)  # first activity is now a breakfast, no outbound
    check = _endpoint_checker(ROWS)
    assert agent._accepted(*check(plan)) is False

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    first = plan["itinerary"][0]["activities"][0]
    second = plan["itinerary"][0]["activities"][1]
    assert first.get("TrainID") == "T_GO_1"
    assert first.get("start") == "A Station"
    assert second.get("transports") == _leg("B Station", "Hotel B", "08:00")
    assert agent._accepted(*check(plan)) is True


# --- unaccepted-plan commit rule (TPC_COMMONSENSE_FIRST) --------------------------------------
#
# 3 of the 21 failing end-to-end plans on the promoted row fail all four intercity commonsense
# columns at once ("Intercity transportation events must occur" and friends). Those plans are also
# unaccepted, so the legacy `if not self._accepted(*check(trial)): return` guard discarded the
# re-grounding every time -- see docs/archive/agents/final_night_commonsense_first.md.


def _endpoints_grounded(plan):
    """Mirror of the endpoint checker's verdict, used as the stubbed commonsense verdict."""
    return _endpoint_checker(ROWS)(plan) == (1, 1)


def _never_accepted_endpoint_check(plan):
    """Grounded endpoints raise the parsed-pass count but one clause always fails."""
    passed, _ = _endpoint_checker(ROWS)(plan)
    return (passed, 2)


def _unaccepted_agent(*, schema_ok=True, commonsense_from_endpoints=True):
    agent = _bare_agent(ROWS)
    agent._schema_ok = lambda query, plan: schema_ok
    if commonsense_from_endpoints:
        agent._commonsense_ok = lambda query, plan: _endpoints_grounded(plan)
    else:
        agent._commonsense_ok = lambda query, plan: False
    return agent


def test_unaccepted_plan_untouched_when_umbrella_flag_off(monkeypatch):
    monkeypatch.delenv("TPC_COMMONSENSE_FIRST", raising=False)
    monkeypatch.setenv("TPC_REPAIR_INTERCITY", "1")
    agent = _unaccepted_agent()
    plan = _base_plan()
    snapshot = deepcopy(plan)

    agent._repair_intercity_endpoints(plan, QUERY, {}, _never_accepted_endpoint_check)

    assert plan == snapshot  # byte-identical floor without the umbrella


def test_unaccepted_plan_regrounded_under_commonsense_first(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent = _unaccepted_agent()
    plan = _base_plan()
    assert _endpoints_grounded(plan) is False

    agent._repair_intercity_endpoints(plan, QUERY, {}, _never_accepted_endpoint_check)

    first = plan["itinerary"][0]["activities"][0]
    assert first["TrainID"] == "T_GO_1"
    assert first["price"] == 120
    assert first["cost"] == 240  # 120 x 2 tickets
    assert _endpoints_grounded(plan) is True


def test_unaccepted_commit_refused_when_commonsense_stays_invalid(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent = _unaccepted_agent(commonsense_from_endpoints=False)
    plan = _base_plan()
    snapshot = deepcopy(plan)

    agent._repair_intercity_endpoints(plan, QUERY, {}, _never_accepted_endpoint_check)

    assert plan == snapshot


def test_unaccepted_commit_refused_when_parsed_passes_drop(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent = _unaccepted_agent()
    plan = _base_plan()
    snapshot = deepcopy(plan)

    def check(p):
        # The grounded endpoint breaks one parsed clause (e.g. an intercity budget cap).
        return (1, 3) if _endpoints_grounded(p) else (2, 3)

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    assert plan == snapshot


# --- TPC_REPAIR_DROP_TRAILING_STAY ------------------------------------------------------------
#
# A 1-day trip whose last activity is an overnight accommodation running to 24:00 floors the
# return-departure search at 24:00, so no row can ever clear it and the endpoint repair silently
# declines (docs/tpc_shortcomings_and_plan.md W5).


def _single_day_plan():
    return {
        "itinerary": [
            {
                "activities": [
                    {
                        "type": "train",
                        "TrainID": "T_GO_1",
                        "start": "A Station",
                        "end": "B Station",
                        "start_time": "06:30",
                        "end_time": "08:00",
                        "price": 120,
                        "cost": 240,
                        "tickets": 2,
                        "transports": [],
                    },
                    {
                        "type": "breakfast",
                        "position": "Hotel B",
                        "start_time": "09:00",
                        "end_time": "10:00",
                        "price": 0,
                        "cost": 0,
                        "tickets": 0,
                        "transports": [],
                    },
                    {
                        "type": "accommodation",
                        "position": "Hotel B",
                        "start_time": "18:00",
                        "end_time": "24:00",
                        "price": 100,
                        "cost": 200,
                        "rooms": 1,
                        "tickets": 2,
                        "transports": [],
                    },
                ]
            }
        ]
    }


def test_drop_trailing_stay_flag_off_by_default():
    assert _bare_agent(ROWS)._repair_drop_trailing_stay_enabled() is False


def test_flag_off_single_day_trailing_stay_untouched(monkeypatch):
    monkeypatch.delenv("TPC_REPAIR_DROP_TRAILING_STAY", raising=False)
    monkeypatch.delenv("TPC_COMMONSENSE_FIRST", raising=False)
    agent = _bare_agent(ROWS)
    plan = _single_day_plan()
    snapshot = deepcopy(plan)
    check = _endpoint_checker(ROWS)
    assert agent._accepted(*check(plan)) is False

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    assert plan == snapshot


def test_flag_on_drops_trailing_stay_and_commits_return_leg(monkeypatch):
    monkeypatch.setenv("TPC_REPAIR_DROP_TRAILING_STAY", "1")
    agent = _bare_agent(ROWS)
    plan = _single_day_plan()
    check = _endpoint_checker(ROWS)
    assert agent._accepted(*check(plan)) is False

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    activities = plan["itinerary"][-1]["activities"]
    assert all(a.get("type") != "accommodation" for a in activities)
    last = activities[-1]
    assert last.get("TrainID") == "T_BACK_1"
    assert last.get("start_time") == "16:30"
    assert agent._accepted(*check(plan)) is True


def test_flag_on_two_day_trailing_stay_untouched(monkeypatch):
    monkeypatch.setenv("TPC_REPAIR_DROP_TRAILING_STAY", "1")
    agent = _bare_agent(ROWS)
    plan = _base_plan()
    # Replace the return train with a trailing overnight stay -- multi-day, must never be dropped.
    plan["itinerary"][-1]["activities"][-1] = {
        "type": "accommodation",
        "position": "Hotel B",
        "start_time": "18:00",
        "end_time": "24:00",
        "price": 100,
        "cost": 200,
        "rooms": 1,
        "tickets": 2,
        "transports": [],
    }
    snapshot = deepcopy(plan)
    check = _endpoint_checker(ROWS)
    assert agent._accepted(*check(plan)) is False

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    assert plan == snapshot


def test_flag_on_no_feasible_return_after_drop_leaves_plan_unchanged(monkeypatch):
    monkeypatch.setenv("TPC_REPAIR_DROP_TRAILING_STAY", "1")
    rows = deepcopy(ROWS)
    rows[("B", "A", "train")] = [
        {
            "TrainID": "T_BACK_TOO_EARLY",
            "From": "B Station",
            "To": "A Station",
            "BeginTime": "08:00",
            "EndTime": "09:00",
            "Cost": 99,
        }
    ]
    agent = _bare_agent(rows)
    plan = _single_day_plan()
    snapshot = deepcopy(plan)
    check = _endpoint_checker(rows)

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    assert plan == snapshot


def test_drop_trailing_stay_umbrella_on_by_commonsense_first(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    monkeypatch.delenv("TPC_REPAIR_DROP_TRAILING_STAY", raising=False)
    agent = _bare_agent(ROWS)
    assert agent._repair_drop_trailing_stay_enabled() is True
    plan = _single_day_plan()
    check = _endpoint_checker(ROWS)

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    activities = plan["itinerary"][-1]["activities"]
    assert all(a.get("type") != "accommodation" for a in activities)
    assert agent._accepted(*check(plan)) is True


def test_drop_trailing_stay_explicit_zero_overrides_umbrella(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    monkeypatch.setenv("TPC_REPAIR_DROP_TRAILING_STAY", "0")
    agent = _bare_agent(ROWS)
    assert agent._repair_drop_trailing_stay_enabled() is False
    plan = _single_day_plan()
    snapshot = deepcopy(plan)
    check = _endpoint_checker(ROWS)

    agent._repair_intercity_endpoints(plan, QUERY, {}, check)

    assert plan == snapshot
