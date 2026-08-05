"""Unit tests for the opt-in window-anchored day relayout (roadmap P1, ``TPC_WINDOW_ANCHOR``).

Same harness as ``test_cascade_timed_windows.py``: a bare ``TPCAgent`` (``__new__``, no WorldEnv)
with a zero-travel ``_get_transport`` stub, so the tests reason about absolute clock times.

The two mechanisms under test were each chosen from a measured classification of the
``timed_visit_named_poi`` residual by shape (``scripts/phase2_timed_window_shapes.py``):

1. ``_resolve_slot_windows`` -- type-aware and *intersecting*, so a hotel's meal window and its
   overnight-stay window stop colliding on the shared POI name (11 of 80 familiar-100 val queries
   carry such a pair) and two windows on one POI are both honoured.
2. ``retime_stay_tail`` -- a ripple that pushes the day later may also push the overnight
   ``accommodation`` tail later (25 of 29 tail rejections in the residual), but never an intercity
   departure.

Plus the floor: with the flag off, ``_pack_plan`` must not reach the pass at all.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent  # noqa: E402

QUERY = {"target_city": "TestCity", "people_number": 1}


def _bare_agent():
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent.env = None
    # Zero travel time: arrival == requested departure clock.
    agent._get_transport = lambda env, city, frm, to, depart, people: ([], depart)
    return agent


def _win(location, earliest=None, end_before=None, activity_types=None):
    return {"location": location, "earliest": earliest, "latest": None,
            "end_after": None, "end_before": end_before, "activity_types": activity_types}


MEALS = ["breakfast", "lunch", "dinner"]


def _hotel_day_plan(*, stay_start="20:00", stay_type="accommodation"):
    """A day whose hotel breakfast is 07:30-08:30 (60 min) against a 55-min window, followed by an
    attraction and the overnight stay. The same hotel name also carries a *stay* window."""
    return {
        "itinerary": [
            {
                "activities": [
                    {"type": "breakfast", "position": "Inn", "start_time": "07:30",
                     "end_time": "08:30", "price": 0, "cost": 0, "tickets": 0, "transports": []},
                    {"type": "attraction", "position": "Museum", "start_time": "08:30",
                     "end_time": "09:30", "price": 0, "cost": 0, "tickets": 1, "transports": []},
                    {"type": stay_type, "position": "Inn", "start_time": stay_start,
                     "end_time": "24:00", "price": 100, "cost": 100, "rooms": 1, "room_type": 2,
                     "tickets": 1, "transports": []},
                ]
            }
        ]
    }


def _breakfast_window_checker(lo="07:50", hi="08:45"):
    """Accepts only when a breakfast at ``Inn`` sits inside ``[lo, hi]``."""
    def check(plan):
        for day in plan.get("itinerary", []):
            for activity in day.get("activities", []):
                if activity.get("type") == "breakfast" and activity.get("position") == "Inn":
                    if lo <= activity.get("start_time", "") and activity.get("end_time", "") <= hi:
                        return (1, 1)
        return (0, 1)
    return check


# --- _resolve_slot_windows -------------------------------------------------------------------


def test_resolve_slot_windows_is_type_aware():
    """A stay window on the hotel name must not land on that hotel's breakfast."""
    agent = _bare_agent()
    activities = _hotel_day_plan()["itinerary"][0]["activities"]
    windows = [
        _win("Inn", earliest="20:10", end_before="24:00", activity_types=["accommodation"]),
        _win("Inn", earliest="07:50", end_before="08:45", activity_types=MEALS),
    ]
    resolved = agent._resolve_slot_windows(activities, windows)
    # Slot 0 is the breakfast: it gets the meal window (470-525), not the 20:10 stay window.
    assert resolved == {0: (7 * 60 + 50, 8 * 60 + 45)}


def test_resolve_slot_windows_intersects_multiple_windows():
    """Two clauses on one POI must both hold, so the effective bound is the intersection."""
    agent = _bare_agent()
    activities = _hotel_day_plan()["itinerary"][0]["activities"]
    windows = [
        _win("Inn", earliest="07:45", end_before="08:40", activity_types=MEALS),
        _win("Inn", earliest="07:50", end_before="08:35", activity_types=MEALS),
    ]
    assert agent._resolve_slot_windows(activities, windows) == {0: (7 * 60 + 50, 8 * 60 + 35)}


def test_resolve_slot_windows_drops_an_empty_intersection():
    agent = _bare_agent()
    activities = _hotel_day_plan()["itinerary"][0]["activities"]
    windows = [
        _win("Inn", earliest="07:45", end_before="08:00", activity_types=MEALS),
        _win("Inn", earliest="09:00", end_before="09:30", activity_types=MEALS),
    ]
    assert agent._resolve_slot_windows(activities, windows) == {}


def test_resolve_slot_windows_without_types_stays_type_agnostic():
    """A window that names no types keeps the previous reading: any activity at that position."""
    agent = _bare_agent()
    activities = _hotel_day_plan()["itinerary"][0]["activities"]
    windows = [_win("Inn", earliest="07:50", end_before="08:45")]
    assert agent._resolve_slot_windows(activities, windows) == {0: (7 * 60 + 50, 8 * 60 + 45)}


# --- _anchor_timed_windows ------------------------------------------------------------------


def test_anchor_shortens_dwell_and_ripples_forward():
    """The dominant residual sub-shape: a 60-min breakfast against a 55-min window, 20 min early."""
    agent = _bare_agent()
    plan = _hotel_day_plan()
    constraints = {"activity_time_windows": [
        _win("Inn", earliest="20:10", end_before="24:00", activity_types=["accommodation"]),
        _win("Inn", earliest="07:50", end_before="08:45", activity_types=MEALS),
    ]}
    check = _breakfast_window_checker()
    assert agent._accepted(*check(plan)) is False

    assert agent._anchor_timed_windows(plan, QUERY, constraints, check) is True

    acts = plan["itinerary"][0]["activities"]
    assert (acts[0]["start_time"], acts[0]["end_time"]) == ("07:50", "08:45")  # clamped + shortened
    assert (acts[1]["start_time"], acts[1]["end_time"]) == ("08:45", "09:45")  # rippled, dwell kept
    assert agent._accepted(*check(plan)) is True


def test_anchor_retimes_the_overnight_stay_tail():
    """The ripple pushes the day past the stay's recorded check-in, which is not a real deadline."""
    agent = _bare_agent()
    plan = _hotel_day_plan(stay_start="09:00")
    constraints = {"activity_time_windows": [_win("Inn", earliest="07:50", end_before="08:45",
                                                  activity_types=MEALS)]}
    check = _breakfast_window_checker()

    assert agent._anchor_timed_windows(plan, QUERY, constraints, check) is True

    acts = plan["itinerary"][0]["activities"]
    assert acts[1]["end_time"] == "09:45"
    assert acts[2]["start_time"] == "09:45"  # stay simply starts when the traveller arrives
    assert acts[2]["end_time"] == "24:00"


def test_anchor_never_moves_an_intercity_tail():
    """A train cannot be missed: the same ripple must be rejected outright, leaving the plan alone."""
    agent = _bare_agent()
    plan = _hotel_day_plan(stay_start="09:00", stay_type="train")
    plan["itinerary"][0]["activities"][2].update(
        {"start": "TestCity Station", "end": "Home Station", "position": None})
    constraints = {"activity_time_windows": [_win("Inn", earliest="07:50", end_before="08:45",
                                                  activity_types=MEALS)]}
    check = _breakfast_window_checker()

    assert agent._anchor_timed_windows(plan, QUERY, constraints, check) is False

    acts = plan["itinerary"][0]["activities"]
    assert (acts[0]["start_time"], acts[0]["end_time"]) == ("07:30", "08:30")  # untouched
    assert acts[2]["start_time"] == "09:00"


def test_anchor_never_retimes_a_stay_past_midnight():
    agent = _bare_agent()
    plan = _hotel_day_plan(stay_start="20:00")
    # A 6-hour attraction pushes the day's end past 24:00 once the breakfast is clamped.
    plan["itinerary"][0]["activities"][1]["end_time"] = "14:30"
    constraints = {"activity_time_windows": [_win("Inn", earliest="20:30", end_before="23:00",
                                                  activity_types=MEALS)]}

    def check(plan_):
        acts_ = plan_["itinerary"][0]["activities"]
        return (1, 1) if acts_[0]["start_time"] >= "20:30" else (0, 1)

    assert agent._anchor_timed_windows(plan, QUERY, constraints, check) is False
    assert plan["itinerary"][0]["activities"][0]["start_time"] == "07:30"


def test_anchor_skips_a_day_already_inside_its_windows():
    agent = _bare_agent()
    plan = _hotel_day_plan()
    plan["itinerary"][0]["activities"][0].update({"start_time": "07:50", "end_time": "08:40"})
    constraints = {"activity_time_windows": [_win("Inn", earliest="07:50", end_before="08:45",
                                                  activity_types=MEALS)]}
    assert agent._anchor_timed_windows(plan, QUERY, constraints, _breakfast_window_checker()) is False
    assert plan["itinerary"][0]["activities"][0]["end_time"] == "08:40"  # not re-cut


def test_anchor_noop_without_windows():
    agent = _bare_agent()
    plan = _hotel_day_plan()
    assert agent._anchor_timed_windows(plan, QUERY, {}, _breakfast_window_checker()) is False
    assert plan["itinerary"][0]["activities"][0]["start_time"] == "07:30"


def test_anchor_reverts_when_the_checker_still_rejects():
    """Acceptance-first: a structurally valid relayout that the checker rejects is not committed."""
    agent = _bare_agent()
    plan = _hotel_day_plan()
    constraints = {"activity_time_windows": [_win("Inn", earliest="07:50", end_before="08:45",
                                                  activity_types=MEALS)]}
    assert agent._anchor_timed_windows(plan, QUERY, constraints, lambda p: (0, 1)) is False
    acts = plan["itinerary"][0]["activities"]
    assert (acts[0]["start_time"], acts[0]["end_time"]) == ("07:30", "08:30")


def test_anchor_keeps_an_accepted_plans_preference_key():
    """An already-accepted input keeps the strict legacy rule: no preference regression."""
    agent = _bare_agent()
    plan = _hotel_day_plan()
    constraints = {"activity_time_windows": [_win("Inn", earliest="07:50", end_before="08:45",
                                                  activity_types=MEALS)]}
    calls = {"n": 0}

    def always_accept(_plan):
        return (1, 1)

    # Report a *worse* key for any trial than for the incumbent, so the guard must bite.
    def key(_plan):
        calls["n"] += 1
        return 100.0 if calls["n"] == 1 else 0.0

    agent._accepted_eval_key = key
    assert agent._anchor_timed_windows(plan, QUERY, constraints, always_accept) is False
    assert plan["itinerary"][0]["activities"][0]["start_time"] == "07:30"


# --- the flag gate / byte-identical floor ----------------------------------------------------


def test_flag_default_off_and_pack_plan_skips_the_pass(monkeypatch):
    monkeypatch.delenv("TPC_WINDOW_ANCHOR", raising=False)
    agent = _bare_agent()
    assert agent._window_anchor_enabled() is False

    calls = {"n": 0}
    agent._anchor_timed_windows = lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
    agent._pin_windows_enabled = lambda: False
    agent._repair_transport_gaps_enabled = lambda: False
    agent._repair_intercity_enabled = lambda: False
    agent._repair_drop_trailing_stay_enabled = lambda: False
    agent._sanitize_plan_for_grounding = lambda plan, query: plan

    plan = _hotel_day_plan()
    agent._pack_plan(plan, QUERY, {}, lambda p: (0, 1), {})
    assert calls["n"] == 0


def test_flag_on_reaches_the_pass_from_pack_plan(monkeypatch):
    monkeypatch.setenv("TPC_WINDOW_ANCHOR", "1")
    agent = _bare_agent()
    assert agent._window_anchor_enabled() is True

    calls = {"n": 0}
    agent._anchor_timed_windows = lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
    agent._pin_windows_enabled = lambda: False
    agent._repair_transport_gaps_enabled = lambda: False
    agent._repair_intercity_enabled = lambda: False
    agent._repair_drop_trailing_stay_enabled = lambda: False
    agent._sanitize_plan_for_grounding = lambda plan, query: plan
    agent._set_transport_context = lambda constraints: None

    plan = _hotel_day_plan()
    agent._pack_plan(plan, QUERY, {}, lambda p: (0, 1), {})
    assert calls["n"] == 1


def test_relayout_defaults_are_byte_identical_for_existing_callers():
    """``_relayout_movable_block`` without the new kwargs must behave exactly as before: the
    overnight stay's start_time is a hard bound and windows resolve by position only."""
    agent = _bare_agent()
    plan = _hotel_day_plan(stay_start="09:00")
    trial = {"itinerary": [{"activities": [dict(a) for a in plan["itinerary"][0]["activities"]]}]}
    windows = [_win("Inn", earliest="07:50", end_before="08:45", activity_types=MEALS)]
    # Clamping the breakfast ripples the attraction to 09:45, past the 09:00 stay -- and without
    # retime_stay_tail that is a rejection, not a retiming.
    assert agent._relayout_movable_block(trial, 0, [0, 1], [0, 1], "TestCity", 1,
                                         windows=windows) is False


def test_relayout_still_clamps_the_day_end_for_existing_callers():
    """The 24:00 overflow rejection is new-path only: an existing caller keeps ``minutes_to_time``'s
    23:59 clamp, so its behaviour on an overflowing ripple is unchanged.

    The day here has no fixed tail, so the clamp is observable on its own rather than masked by the
    tail-reachability guard.
    """
    agent = _bare_agent()
    activities = _hotel_day_plan()["itinerary"][0]["activities"][:2]
    activities[1]["end_time"] = "14:30"   # a 6-hour attraction
    trial = {"itinerary": [{"activities": [dict(a) for a in activities]}]}
    windows = [_win("Inn", earliest="20:30", end_before="23:00", activity_types=MEALS)]

    assert agent._relayout_movable_block(trial, 0, [0, 1], [0, 1], "TestCity", 1,
                                         windows=windows) is True
    assert trial["itinerary"][0]["activities"][1]["end_time"] == "23:59"  # clamped, as before

    # The same layout on the anchored path is rejected instead of silently truncated.
    trial2 = {"itinerary": [{"activities": [dict(a) for a in activities]}]}
    assert agent._relayout_movable_block(
        trial2, 0, [0, 1], [0, 1], "TestCity", 1,
        slot_windows={0: (20 * 60 + 30, 23 * 60)}, retime_stay_tail=True) is False


def test_pack_plan_output_is_byte_identical_with_the_flag_off(monkeypatch):
    """The ship-bar floor test: run the real ``_pack_plan`` on a window-failing plan with the flag
    unset and with it explicitly ``0``, and require the emitted plan to equal the untouched input.

    Every other window flag is held off too, so this isolates ``TPC_WINDOW_ANCHOR``: if the new pass
    ever mutated a plan without its flag, this fails.
    """
    for value in (None, "0", "false", ""):
        if value is None:
            monkeypatch.delenv("TPC_WINDOW_ANCHOR", raising=False)
        else:
            monkeypatch.setenv("TPC_WINDOW_ANCHOR", value)
        for other in ("TPC_PIN_TIMED_WINDOWS", "TPC_CASCADE_TIMED_WINDOWS", "TPC_COMMONSENSE_FIRST",
                      "TPC_REPAIR_TRANSPORT_GAPS", "TPC_REPAIR_INTERCITY",
                      "TPC_REPAIR_DROP_TRAILING_STAY"):
            monkeypatch.delenv(other, raising=False)

        agent = _bare_agent()
        agent._sanitize_plan_for_grounding = lambda plan, query: plan
        plan = _hotel_day_plan()
        snapshot = _hotel_day_plan()
        constraints = {"activity_time_windows": [
            _win("Inn", earliest="07:50", end_before="08:45", activity_types=MEALS)]}

        out = agent._pack_plan(plan, QUERY, constraints, _breakfast_window_checker(), {})

        assert out == snapshot, f"TPC_WINDOW_ANCHOR={value!r} mutated the floor"
        assert plan == snapshot, f"TPC_WINDOW_ANCHOR={value!r} mutated the input plan"


def test_pack_plan_applies_the_pass_with_the_flag_on(monkeypatch):
    """The same input, same everything, with only ``TPC_WINDOW_ANCHOR=1`` -- the plan must change."""
    monkeypatch.setenv("TPC_WINDOW_ANCHOR", "1")
    for other in ("TPC_PIN_TIMED_WINDOWS", "TPC_CASCADE_TIMED_WINDOWS", "TPC_COMMONSENSE_FIRST",
                  "TPC_REPAIR_TRANSPORT_GAPS", "TPC_REPAIR_INTERCITY",
                  "TPC_REPAIR_DROP_TRAILING_STAY"):
        monkeypatch.delenv(other, raising=False)

    agent = _bare_agent()
    agent._sanitize_plan_for_grounding = lambda plan, query: plan
    agent._set_transport_context = lambda constraints: None
    plan = _hotel_day_plan()
    constraints = {"activity_time_windows": [
        _win("Inn", earliest="07:50", end_before="08:45", activity_types=MEALS)]}
    check = _breakfast_window_checker()

    out = agent._pack_plan(plan, QUERY, constraints, check, {})

    assert (out["itinerary"][0]["activities"][0]["start_time"],
            out["itinerary"][0]["activities"][0]["end_time"]) == ("07:50", "08:45")
    assert agent._accepted(*check(out)) is True


# --- the two-layer promotion contract (R8, 2026-08-05) ----------------------------------------


def test_harness_promotes_the_flag_while_the_library_default_stays_off(monkeypatch):
    """R8 gated the pass GREEN, so the *harness* runs it by default while the *library* does not.

    Both halves matter and they are easy to break independently: if the library default ever flips,
    the byte-identical floor tests above stop describing the shipped floor; if the harness promotion
    is dropped, the submission silently reverts to R7's ``FPR 32.0``.
    """
    import solve_phase2 as runner

    # Every var the promotion touches is delenv'd through monkeypatch, so pytest's teardown removes
    # whatever the call sets and no later test inherits a promoted flag.
    for name in ("TPC_WINDOW_ANCHOR", "TPC_PIN_TIMED_WINDOWS", "TPC_SOLVE_CONVERGE_PATIENCE",
                 "TPC_COMMONSENSE_FIRST"):
        monkeypatch.delenv(name, raising=False)
    assert _bare_agent()._window_anchor_enabled() is False, "library default must stay off"

    runner.apply_deterministic_solver_defaults()

    assert os.environ["TPC_WINDOW_ANCHOR"] == "1"
    assert _bare_agent()._window_anchor_enabled() is True
    # The pass is only meaningful with the pin that puts the named POI in the plan, and R8 measured
    # the pair -- so the pair has to be what the harness turns on.
    assert os.environ["TPC_PIN_TIMED_WINDOWS"] == "1"
