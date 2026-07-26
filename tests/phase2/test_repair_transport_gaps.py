"""Unit tests for the opt-in commonsense-transport repair pass (roadmap step 4).

These use a bare ``TPCAgent`` instance (``__new__``, no WorldEnv) and a stubbed
``_get_transport_resilient`` (the lookup ``_fix_transport_leg_if_broken`` actually calls) so the
tests exercise only the pure leg-recomputation/commit logic in ``_repair_transport_gaps``,
matching the pattern of ``test_pin_timed_windows.py``. ``_get_transport_resilient`` itself and the
``_format_transport_segments`` extraction it shares with ``_get_transport`` are covered separately
below, against a fake ``env.transportation.goto``.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# TPCAgent uses internal ``from agent.base import ...`` imports, which require the ``chinatravel``
# directory on sys.path.
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent  # noqa: E402


def _bare_agent(get_transport=None):
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent.env = None
    if get_transport is not None:
        agent._get_transport_resilient = get_transport
    return agent


def _leg(frm, to, depart):
    return [{"start": frm, "end": to, "mode": "taxi", "start_time": depart, "end_time": depart,
             "distance": 1.0, "price": 10, "cost": 10}]


def _zero_time_transport(env, city, frm, to, depart, people):
    """Zero travel time: arrival == requested departure clock."""
    return _leg(frm, to, depart), depart


def _no_route_transport(env, city, frm, to, depart, people):
    return None, None


def _broken_plan():
    # Day 0: an attraction (first activity, no prev -> never touched), then a lunch at a
    # different position with an empty (broken) inbound leg.
    return {
        "itinerary": [
            {
                "activities": [
                    {"type": "attraction", "position": "Park", "start_time": "09:00",
                     "end_time": "10:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                    {"type": "lunch", "position": "Restaurant", "start_time": "10:30",
                     "end_time": "11:30", "price": 20, "cost": 20, "tickets": 1, "transports": []},
                ]
            }
        ]
    }


def _space_checker():
    """Stub full-checker mirroring Is_space_correct: accepted iff every non-first activity's
    inbound leg connects the previous activity's position to its own."""
    def check(plan):
        prev_pos = None
        for day in plan.get("itinerary", []):
            for a in day.get("activities", []):
                pos = a.get("position") or a.get("end") or a.get("start")
                if prev_pos is not None and pos != prev_pos:
                    legs = a.get("transports") or []
                    if not legs or legs[0]["start"] != prev_pos or legs[-1]["end"] != pos:
                        return (0, 1)
                prev_pos = pos
        return (1, 1)
    return check


QUERY = {"target_city": "Shenzhen", "people_number": 1}


def test_flag_off_by_default():
    assert _bare_agent()._repair_transport_gaps_enabled() is False


def test_flag_reads_env(monkeypatch):
    monkeypatch.setenv("TPC_REPAIR_TRANSPORT_GAPS", "1")
    assert _bare_agent()._repair_transport_gaps_enabled() is True


def test_repair_fixes_broken_leg_and_flips_acceptance():
    agent = _bare_agent(_zero_time_transport)
    plan = _broken_plan()
    check = _space_checker()
    assert agent._accepted(*check(plan)) is False
    agent._repair_transport_gaps(plan, QUERY, {}, check)
    lunch = plan["itinerary"][0]["activities"][1]
    # Departs from the previous activity's end_time (09:00-10:00 attraction), not the lunch's own
    # start_time -- the stub's zero travel time means arrival == that departure clock.
    assert lunch["transports"] == _leg("Park", "Restaurant", "10:00")
    assert agent._accepted(*check(plan)) is True


def test_repair_batches_multiple_broken_legs_together():
    # Both legs must be fixed simultaneously for the checker to accept -- a per-leg trial that
    # required full acceptance to commit each step would never commit either one.
    agent = _bare_agent(_zero_time_transport)
    plan = {
        "itinerary": [
            {"activities": [
                {"type": "attraction", "position": "Park", "start_time": "09:00", "end_time": "10:00",
                 "price": 0, "cost": 0, "tickets": 1, "transports": []},
                {"type": "lunch", "position": "Restaurant", "start_time": "10:30", "end_time": "11:30",
                 "price": 20, "cost": 20, "tickets": 1, "transports": []},
                {"type": "attraction", "position": "Museum", "start_time": "12:00", "end_time": "13:00",
                 "price": 0, "cost": 0, "tickets": 1, "transports": []},
            ]}
        ]
    }
    check = _space_checker()
    assert agent._accepted(*check(plan)) is False
    agent._repair_transport_gaps(plan, QUERY, {}, check)
    lunch, museum = plan["itinerary"][0]["activities"][1], plan["itinerary"][0]["activities"][2]
    assert lunch["transports"] == _leg("Park", "Restaurant", "10:00")
    assert museum["transports"] == _leg("Restaurant", "Museum", "11:30")
    assert agent._accepted(*check(plan)) is True


def test_repair_noop_when_no_route_found():
    agent = _bare_agent(_no_route_transport)
    plan = _broken_plan()
    snapshot = _broken_plan()
    agent._repair_transport_gaps(plan, QUERY, {}, _space_checker())
    assert plan == snapshot


def test_repair_does_not_shift_timing_when_arrival_too_late():
    def late_transport(env, city, frm, to, depart, people):
        return _leg(frm, to, depart), "23:00"  # arrives long after the activity's own start_time

    agent = _bare_agent(late_transport)
    plan = _broken_plan()
    snapshot = _broken_plan()
    agent._repair_transport_gaps(plan, QUERY, {}, _space_checker())
    assert plan == snapshot


def test_repair_reverts_when_check_still_rejects():
    # Even though the leg gets fixed, an unrelated always-failing checker must leave the plan
    # untouched -- no partial commit.
    agent = _bare_agent(_zero_time_transport)
    plan = _broken_plan()
    snapshot = _broken_plan()
    agent._repair_transport_gaps(plan, QUERY, {}, lambda p: (0, 1))
    assert plan == snapshot


def test_repair_skips_first_activity_and_intercity():
    agent = _bare_agent(_zero_time_transport)
    plan = {
        "itinerary": [
            {"activities": [
                # First activity of the whole plan: no prior position, never touched.
                {"type": "attraction", "position": "Park", "start_time": "09:00", "end_time": "10:00",
                 "price": 0, "cost": 0, "tickets": 1, "transports": []},
                # Intercity leg: its own inbound shape is out of scope for this move.
                {"type": "train", "start": "Park", "end": "Other City Station",
                 "start_time": "11:00", "end_time": "13:00", "price": 100, "cost": 100,
                 "tickets": 1, "transports": [], "TrainID": "T1"},
            ]}
        ]
    }
    snapshot_first = dict(plan["itinerary"][0]["activities"][0])
    snapshot_train = dict(plan["itinerary"][0]["activities"][1])
    agent._repair_transport_gaps(plan, QUERY, {}, _space_checker())
    assert plan["itinerary"][0]["activities"][0] == snapshot_first
    assert plan["itinerary"][0]["activities"][1] == snapshot_train


def test_repair_gap_detection_uses_normalize_poi_name_not_raw_strings():
    """Two alias-equivalent POI names (see concept_func._POI_NAME_ALIASES: "Bistro Sola" <->
    "Sola Bistro") are the *same* position to Is_space_correct's own normalize_poi_name-based
    comparison -- the repair pass must not attempt (and cost) a leg between them just because the
    raw strings differ (Copilot review on PR #29)."""
    def boom(env, city, frm, to, depart, people):
        raise AssertionError("must not attempt a transport fix between alias-equivalent positions")

    agent = _bare_agent(boom)
    plan = {
        "itinerary": [
            {"activities": [
                {"type": "attraction", "position": "Sola Bistro", "start_time": "09:00",
                 "end_time": "10:00", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                {"type": "lunch", "position": "Bistro Sola", "start_time": "10:30",
                 "end_time": "11:30", "price": 20, "cost": 20, "tickets": 1, "transports": []},
            ]}
        ]
    }
    agent._repair_transport_gaps(plan, QUERY, {}, lambda p: (1, 1))
    assert plan["itinerary"][0]["activities"][1]["transports"] == []


def test_repair_is_noop_when_nothing_broken():
    agent = _bare_agent(_zero_time_transport)
    plan = _broken_plan()
    plan["itinerary"][0]["activities"][1]["transports"] = _leg("Park", "Restaurant", "10:30")
    check = _space_checker()
    assert agent._accepted(*check(plan)) is True
    before = plan["itinerary"][0]["activities"][1]["transports"]
    agent._repair_transport_gaps(plan, QUERY, {}, check)
    assert plan["itinerary"][0]["activities"][1]["transports"] == before


# --- _get_transport_resilient: per-mode exception resilience ------------------------------------
#
# ``_get_transport`` wraps its *whole* mode-order loop in one try/except, so a single mode raising
# (an observed ``env.transportation.goto`` edge case on some metro routes) silently aborts the
# entire lookup even when a later mode would have succeeded -- the root cause behind some
# "Invalid Transport information across positions" cases. ``_get_transport_resilient`` tries each
# mode independently instead.

class _FakeTransportation:
    def __init__(self, goto_fn):
        self.goto = goto_fn


class _FakeEnv:
    def __init__(self, goto_fn):
        self.transportation = _FakeTransportation(goto_fn)


def _goto_metro_raises_taxi_succeeds(city, frm, to, start_time, mode):
    if mode == "metro":
        raise TypeError("string indices must be integers, not 'str'")
    if mode == "walk":
        return []
    return [{"start": frm, "end": to, "mode": "taxi", "start_time": start_time,
             "end_time": "09:19", "distance": 5.0, "cost": 20}]


def _resilient_agent():
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent._active_timing_constraints = []
    agent._transport_constraints = {"excluded_inner_transport": [], "conditional_transport": None,
                                     "taxi_cars_equals": None}
    return agent


def test_get_transport_resilient_falls_through_a_raising_mode():
    agent = _resilient_agent()
    env = _FakeEnv(_goto_metro_raises_taxi_succeeds)
    transports, arrival = agent._get_transport_resilient(env, "Chongqing", "Hotel", "Park", "08:30", 3)
    assert arrival == "09:19"
    assert transports[0]["mode"] == "taxi"
    assert transports[0]["cars"] == 1  # ceil(3/4) = 1 car
    assert transports[0]["cost"] == 20 * 1


def test_get_transport_plain_aborts_on_first_raising_mode():
    """Documents the existing ``_get_transport`` behavior this repair works around: it returns
    ``(None, None)`` as soon as the first tried mode raises, never reaching walk/taxi."""
    agent = _resilient_agent()
    agent._budget_limits = {}
    agent._forced_inner_mode = None
    env = _FakeEnv(_goto_metro_raises_taxi_succeeds)
    transports, arrival = agent._get_transport(env, "Chongqing", "Hotel", "Park", "08:30", 3)
    assert (transports, arrival) == (None, None)


def test_get_transport_resilient_respects_real_exclusions():
    agent = _resilient_agent()
    agent._transport_constraints["excluded_inner_transport"] = ["taxi"]

    def goto_walk_only(city, frm, to, start_time, mode):
        if mode == "walk":
            return [{"start": frm, "end": to, "mode": "walk", "start_time": start_time,
                     "end_time": "09:00", "distance": 1.0, "cost": 0}]
        return []

    env = _FakeEnv(goto_walk_only)
    transports, arrival = agent._get_transport_resilient(env, "Chongqing", "Hotel", "Park", "08:30", 1)
    assert arrival == "09:00"
    assert transports[0]["mode"] == "walk"


def test_get_transport_resilient_none_when_every_mode_fails():
    agent = _resilient_agent()
    env = _FakeEnv(lambda city, frm, to, start_time, mode: [])
    assert agent._get_transport_resilient(env, "Chongqing", "Hotel", "Park", "08:30", 1) == (None, None)


def test_get_transport_resilient_same_position_short_circuits():
    agent = _resilient_agent()
    assert agent._get_transport_resilient(None, "Chongqing", "Hotel", "Hotel", "08:30", 1) == ([], "08:30")


# --- unaccepted-plan commit rule (TPC_COMMONSENSE_FIRST) --------------------------------------
#
# The regime the legacy rule could never reach. An emitted plan that fails some parsed logical
# constraint is unaccepted by definition, so `if not self._accepted(*check(trial)): return` threw
# away a transport repair on exactly the plans whose commonsense failure zeroes their C-LPR (scored
# conditionally on the commonsense pass) and their EPR-macro point. 13 of the 21 failing end-to-end
# plans on the promoted row fail "Invalid Transport information across positions".


def _legs_connected(plan):
    """True when every non-first activity's inbound leg connects the previous position to its own."""
    prev_pos = None
    for day in plan.get("itinerary", []):
        for a in day.get("activities", []):
            pos = a.get("position") or a.get("end") or a.get("start")
            if prev_pos is not None and pos != prev_pos:
                legs = a.get("transports") or []
                if not legs or legs[0]["start"] != prev_pos or legs[-1]["end"] != pos:
                    return False
            prev_pos = pos
    return True


def _unaccepted_agent(*, commonsense_from_legs=True, schema_ok=True):
    """Bare agent whose commonsense verdict tracks leg connectivity, never fully accepted."""
    agent = _bare_agent(_zero_time_transport)
    agent._schema_ok = lambda query, plan: schema_ok
    if commonsense_from_legs:
        agent._commonsense_ok = lambda query, plan: _legs_connected(plan)
    else:
        agent._commonsense_ok = lambda query, plan: False
    return agent


def _never_accepted_check(plan):
    """One parsed constraint always fails, so ``_accepted`` is False before and after the repair."""
    return (1, 2)


def test_unaccepted_plan_untouched_when_umbrella_flag_off(monkeypatch):
    monkeypatch.delenv("TPC_COMMONSENSE_FIRST", raising=False)
    monkeypatch.setenv("TPC_REPAIR_TRANSPORT_GAPS", "1")
    agent = _unaccepted_agent()
    plan = _broken_plan()
    snapshot = _broken_plan()

    agent._repair_transport_gaps(plan, QUERY, {}, _never_accepted_check)

    assert plan == snapshot  # byte-identical floor: no commit without the umbrella


def test_unaccepted_plan_repaired_under_commonsense_first(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent = _unaccepted_agent()
    plan = _broken_plan()
    assert agent._commonsense_ok(QUERY, plan) is False

    agent._repair_transport_gaps(plan, QUERY, {}, _never_accepted_check)

    assert plan["itinerary"][0]["activities"][1]["transports"] == _leg("Park", "Restaurant", "10:00")
    assert agent._commonsense_ok(QUERY, plan) is True


def test_unaccepted_commit_refused_when_parsed_passes_drop(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent = _unaccepted_agent()
    plan = _broken_plan()
    snapshot = _broken_plan()

    def check(p):
        # The repaired trial (connected legs) satisfies one fewer parsed constraint, e.g. a
        # transport-cost budget clause the grounded leg now breaks.
        return (1, 3) if _legs_connected(p) else (2, 3)

    agent._repair_transport_gaps(plan, QUERY, {}, check)

    assert plan == snapshot


def test_unaccepted_commit_refused_when_commonsense_stays_invalid(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent = _unaccepted_agent(commonsense_from_legs=False)
    plan = _broken_plan()
    snapshot = _broken_plan()

    agent._repair_transport_gaps(plan, QUERY, {}, _never_accepted_check)

    assert plan == snapshot


def test_unaccepted_commit_refused_when_schema_breaks(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent = _unaccepted_agent(schema_ok=False)
    plan = _broken_plan()
    snapshot = _broken_plan()

    agent._repair_transport_gaps(plan, QUERY, {}, _never_accepted_check)

    assert plan == snapshot


def test_already_commonsense_valid_unaccepted_plan_is_not_touched(monkeypatch):
    """Nothing to gain: the plan already passes commonsense, so the repair must not spend cost."""
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent = _bare_agent(_zero_time_transport)
    agent._schema_ok = lambda query, plan: True
    agent._commonsense_ok = lambda query, plan: True
    plan = _broken_plan()
    snapshot = _broken_plan()

    agent._repair_transport_gaps(plan, QUERY, {}, _never_accepted_check)

    assert plan == snapshot


def test_accepted_input_keeps_legacy_strict_rule(monkeypatch):
    """An accepted plan must still be judged by acceptance + preference non-regression only."""
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent = _unaccepted_agent()
    plan = _broken_plan()
    snapshot = _broken_plan()

    # Input reads as accepted, and the repaired trial does not: legacy rule must revert.
    def check(p):
        return (0, 1) if _legs_connected(p) else (1, 1)

    agent._repair_transport_gaps(plan, QUERY, {}, check)

    assert plan == snapshot


# --- umbrella flag wiring ---------------------------------------------------------------------


def test_umbrella_flag_enables_both_repair_passes(monkeypatch):
    monkeypatch.delenv("TPC_REPAIR_TRANSPORT_GAPS", raising=False)
    monkeypatch.delenv("TPC_REPAIR_INTERCITY", raising=False)
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    agent = _bare_agent()
    assert agent._commonsense_first_enabled() is True
    assert agent._repair_transport_gaps_enabled() is True
    assert agent._repair_intercity_enabled() is True


def test_explicit_zero_overrides_umbrella(monkeypatch):
    monkeypatch.setenv("TPC_COMMONSENSE_FIRST", "1")
    monkeypatch.setenv("TPC_REPAIR_TRANSPORT_GAPS", "0")
    agent = _bare_agent()
    assert agent._repair_transport_gaps_enabled() is False
    assert agent._repair_intercity_enabled() is True


def test_umbrella_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("TPC_COMMONSENSE_FIRST", raising=False)
    monkeypatch.delenv("TPC_REPAIR_TRANSPORT_GAPS", raising=False)
    agent = _bare_agent()
    assert agent._commonsense_first_enabled() is False
    assert agent._repair_transport_gaps_enabled() is False
