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
    return (
        activity.get("type") == mode
        and activity.get(rid) == row.get(rid)
        and activity.get("start") == row.get("From")
        and activity.get("end") == row.get("To")
        and activity.get("start_time") == row.get("BeginTime")
        and activity.get("end_time") == row.get("EndTime")
        and activity.get("price") == row.get("Cost")
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