"""Focused tests for P25's opt-in cross-day timed-window relocation."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for path in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if path not in sys.path:
        sys.path.insert(0, path)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent  # noqa: E402

QUERY = {"target_city": "TestCity", "people_number": 1}
WINDOW = {"location": "Museum", "earliest": "08:10", "end_before": "09:30",
          "activity_types": ["attraction"]}
CONSTRAINTS = {"activity_time_windows": [WINDOW]}


class _Pool:
    def select(self, city, column, predicate):
        return [{"name": "Museum", "opentime": "08:00", "endtime": "22:00", "price": 10,
                 "cost": 10, "tickets": 1, "type": "Art museum"}]


class _Env:
    attractions = _Pool()
    restaurants = _Pool()


def _bare_agent():
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent.env = _Env()
    # Instant, always-grounded travel: every leg is a same-instant hop, so the plans below are
    # only about *time windows and day structure*, never routing feasibility.
    agent._get_transport = lambda env, city, frm, to, depart, people: ([], depart)
    return agent


def _plan(museum_day1=(14, 0, 15, 0), gallery_start="10:00", second_day_museum=None):
    """Day 1: breakfast at Inn, then Museum outside its 08:10-09:30 window.
    Day 2: breakfast at Inn, then Gallery at ``gallery_start`` (the day's only other movable
    slot, so the gap between breakfast and Gallery is day 2's only candidate free span)."""
    mh1, mm1, mh2, mm2 = museum_day1
    day1_activities = [
        {"type": "breakfast", "position": "Inn", "start_time": "07:30", "end_time": "08:00",
         "price": 0, "cost": 0, "tickets": 0, "transports": []},
        {"type": "attraction", "position": "Museum",
         "start_time": f"{mh1:02d}:{mm1:02d}", "end_time": f"{mh2:02d}:{mm2:02d}",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
    ]
    day2_activities = [
        {"type": "breakfast", "position": "Inn", "start_time": "07:30", "end_time": "08:00",
         "price": 0, "cost": 0, "tickets": 0, "transports": []},
        {"type": "attraction", "position": "Gallery", "start_time": gallery_start,
         "end_time": f"{int(gallery_start[:2]) + 1:02d}:{gallery_start[3:]}",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
    ]
    if second_day_museum is not None:
        sh1, sm1, sh2, sm2 = second_day_museum
        day2_activities.append({
            "type": "attraction", "position": "Museum",
            "start_time": f"{sh1:02d}:{sm1:02d}", "end_time": f"{sh2:02d}:{sm2:02d}",
            "price": 0, "cost": 0, "tickets": 1, "transports": []})
    return {"itinerary": [{"activities": day1_activities}, {"activities": day2_activities}]}


def _check(plan):
    for day in plan["itinerary"]:
        for activity in day["activities"]:
            if activity.get("position") == "Museum" and activity["start_time"] >= "08:10" \
                    and activity["end_time"] <= "09:30":
                return (1, 1)
    return (0, 1)


def test_relocates_a_present_but_window_missed_poi_to_a_day_with_a_free_span():
    """Shape: the window has already "passed" on the day the POI is scheduled (day 1's Museum
    visit ends well after ``end_before``), but day 2 has a free span between its breakfast and
    Gallery that fully contains the window."""
    agent = _bare_agent()
    plan = _plan(museum_day1=(14, 0, 15, 0), gallery_start="10:00")

    assert agent._relocate_timed_windows_across_days(plan, QUERY, CONSTRAINTS, _check)
    assert _check(plan) == (1, 1)
    day1_positions = [a["position"] for a in plan["itinerary"][0]["activities"]]
    day2_positions = [a["position"] for a in plan["itinerary"][1]["activities"]]
    assert "Museum" not in day1_positions
    assert day2_positions.count("Museum") == 1
    museum = next(a for a in plan["itinerary"][1]["activities"] if a["position"] == "Museum")
    assert museum["start_time"] >= "08:10" and museum["end_time"] <= "09:30"


def _tight_gap_day():
    """One day whose only free span (breakfast -> Gallery) is too short for the window's dwell --
    the ``before_first``/``after_last`` insertion helpers must have a real reason to decline too
    (a resolvable hotel anchor, and a day that is not the itinerary's last), or a pass here would
    prove nothing about the gap itself."""
    return {"activities": [
        {"type": "breakfast", "position": "Inn", "start_time": "07:30", "end_time": "08:00",
         "price": 0, "cost": 0, "tickets": 0, "transports": []},
        {"type": "attraction", "position": "Gallery", "start_time": "08:05", "end_time": "09:05",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
        {"type": "accommodation", "position": "Hotel2", "start_time": "20:00", "end_time": "24:00",
         "price": 100, "cost": 100, "tickets": 1, "transports": []},
    ]}


def _no_free_span_plan():
    """Three days, none with room for the Museum window: day 1 has the wrong-time Museum visit;
    day 2 and day 3 each reuse ``_tight_gap_day`` -- a resolvable hotel anchor (from day 1's own
    accommodation) rules out "no hotel" as the reason ``before_first`` declines, and day 2 is not
    the itinerary's last day, ruling out "last day" as the reason ``after_last`` declines. The
    only thing left to block every attempt is the gap itself being too short."""
    return {"itinerary": [
        {"activities": [
            {"type": "breakfast", "position": "Inn", "start_time": "07:30", "end_time": "08:00",
             "price": 0, "cost": 0, "tickets": 0, "transports": []},
            {"type": "attraction", "position": "Museum", "start_time": "14:00", "end_time": "15:00",
             "price": 0, "cost": 0, "tickets": 1, "transports": []},
            {"type": "accommodation", "position": "Hotel1", "start_time": "20:00", "end_time": "24:00",
             "price": 100, "cost": 100, "tickets": 1, "transports": []},
        ]},
        _tight_gap_day(),
        _tight_gap_day(),
    ]}


def test_no_relocation_when_no_day_has_a_free_span():
    """Shape: every other day's only free span (breakfast -> Gallery) is too short for the
    window's dwell, so no day has room -- the move must refuse rather than corrupt a day."""
    agent = _bare_agent()
    plan = _no_free_span_plan()
    before = _no_free_span_plan()

    assert agent._relocate_timed_windows_across_days(plan, QUERY, CONSTRAINTS, _check) is False
    assert plan == before


def test_no_relocation_when_it_would_duplicate_the_poi():
    """Shape: a second (also window-missing) Museum copy already sits on the only other day --
    every candidate target already carries this POI, so relocating would create the duplicate
    the repeated-attraction commonsense rule rejects. Must refuse rather than add a second copy."""
    agent = _bare_agent()
    plan = _plan(museum_day1=(14, 0, 15, 0), gallery_start="10:00",
                 second_day_museum=(16, 0, 17, 0))
    before = _plan(museum_day1=(14, 0, 15, 0), gallery_start="10:00",
                   second_day_museum=(16, 0, 17, 0))

    assert agent._relocate_timed_windows_across_days(plan, QUERY, CONSTRAINTS, _check) is False
    assert plan == before


def test_relocation_is_atomic_never_deletes_without_a_committed_insertion():
    """The roadmap's own trap: relocation is move-then-delete, and the two halves must commit
    together or not at all. An always-failing checker means every insertion attempt on every
    candidate day is refused, so the removal half must never reach the real ``plan`` either --
    Museum stays exactly where it started, on day 1."""
    agent = _bare_agent()
    plan = _plan(museum_day1=(14, 0, 15, 0), gallery_start="10:00")
    before = _plan(museum_day1=(14, 0, 15, 0), gallery_start="10:00")
    always_fails = lambda _plan: (0, 1)  # noqa: E731

    assert agent._relocate_timed_windows_across_days(plan, QUERY, CONSTRAINTS, always_fails) is False
    assert plan == before


def test_no_relocation_when_poi_is_absent_entirely():
    """An absent POI is P9's job (_insert_absent_timed_window_pois), not this move's -- this pass
    must not fire at all when nothing in the plan matches the window's location."""
    agent = _bare_agent()
    plan = {"itinerary": [
        {"activities": [
            {"type": "breakfast", "position": "Inn", "start_time": "07:30", "end_time": "08:00",
             "price": 0, "cost": 0, "tickets": 0, "transports": []}]},
        {"activities": [
            {"type": "attraction", "position": "Gallery", "start_time": "10:00", "end_time": "11:00",
             "price": 0, "cost": 0, "tickets": 1, "transports": []}]},
    ]}
    assert agent._relocate_timed_windows_across_days(plan, QUERY, CONSTRAINTS, _check) is False


def test_no_relocation_on_a_single_day_itinerary():
    agent = _bare_agent()
    plan = {"itinerary": [{"activities": [
        {"type": "attraction", "position": "Museum", "start_time": "14:00", "end_time": "15:00",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
    ]}]}
    assert agent._relocate_timed_windows_across_days(plan, QUERY, CONSTRAINTS, _check) is False


def test_no_relocation_when_already_satisfied_on_some_day():
    """If any existing copy already sits in the window, there is nothing to fix."""
    agent = _bare_agent()
    plan = _plan(museum_day1=(8, 20, 9, 0), gallery_start="10:00")
    before = _plan(museum_day1=(8, 20, 9, 0), gallery_start="10:00")
    assert agent._relocate_timed_windows_across_days(plan, QUERY, CONSTRAINTS, _check) is False
    assert plan == before


def test_window_relocate_day_flag_is_off_by_default_and_reached_only_when_enabled(monkeypatch):
    agent = _bare_agent()
    agent._sanitize_plan_for_grounding = lambda plan, query: plan
    agent._pin_windows_enabled = lambda: False
    agent._repair_transport_gaps_enabled = lambda: False
    agent._repair_intercity_enabled = lambda: False
    agent._repair_drop_trailing_stay_enabled = lambda: False
    agent._window_anchor_enabled = lambda: False
    agent._window_push_enabled = lambda: False
    agent._window_insert_enabled = lambda: False
    agent._set_transport_context = lambda constraints: None
    calls = {"relocate": 0}
    agent._relocate_timed_windows_across_days = lambda *args: calls.__setitem__(
        "relocate", calls["relocate"] + 1)

    monkeypatch.delenv("TPC_WINDOW_RELOCATE_DAY", raising=False)
    agent._pack_plan(_plan(), QUERY, {}, lambda p: (0, 1), {})
    assert calls["relocate"] == 0
    monkeypatch.setenv("TPC_WINDOW_RELOCATE_DAY", "1")
    agent._pack_plan(_plan(), QUERY, {}, lambda p: (0, 1), {})
    assert calls["relocate"] == 1


def test_remove_movable_activity_restitches_neighbours_without_disturbing_an_early_tail():
    agent = _bare_agent()
    trial = {"itinerary": [{"activities": [
        {"type": "breakfast", "position": "Inn", "start_time": "07:30", "end_time": "08:00",
         "price": 0, "cost": 0, "tickets": 0, "transports": []},
        {"type": "attraction", "position": "Museum", "start_time": "14:00", "end_time": "15:00",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
        {"type": "accommodation", "position": "Hotel", "start_time": "20:00", "end_time": "24:00",
         "price": 100, "cost": 100, "tickets": 1, "transports": []},
    ]}]}
    assert agent._remove_movable_activity(trial, 0, 1, "TestCity", 1)
    positions = [a["position"] for a in trial["itinerary"][0]["activities"]]
    assert positions == ["Inn", "Hotel"]
    hotel = trial["itinerary"][0]["activities"][1]
    # The stub grounds an instant hop departing at the breakfast's own end_time (08:00), well
    # before the accommodation's originally-scheduled 20:00 -- arriving early needs no retime.
    assert hotel["start_time"] == "20:00"
    assert hotel["transports"] == []


def test_remove_movable_activity_pulls_an_overnight_stay_tail_earlier_when_it_arrives_late():
    agent = _bare_agent()
    trial = {"itinerary": [{"activities": [
        {"type": "breakfast", "position": "Inn", "start_time": "07:30", "end_time": "08:00",
         "price": 0, "cost": 0, "tickets": 0, "transports": []},
        {"type": "attraction", "position": "Museum", "start_time": "14:00", "end_time": "15:00",
         "price": 0, "cost": 0, "tickets": 1, "transports": []},
        # Deliberately scheduled earlier than the direct predecessor->tail hop can now arrive, so
        # removal must pull it later -- mirrors _relayout_movable_block's retime_stay_tail rule.
        {"type": "accommodation", "position": "Hotel", "start_time": "07:45", "end_time": "24:00",
         "price": 100, "cost": 100, "tickets": 1, "transports": []},
    ]}]}
    assert agent._remove_movable_activity(trial, 0, 1, "TestCity", 1)
    hotel = trial["itinerary"][0]["activities"][1]
    assert hotel["start_time"] == "08:00"


def test_remove_movable_activity_refuses_a_non_movable_index():
    agent = _bare_agent()
    trial = {"itinerary": [{"activities": [
        {"type": "accommodation", "position": "Hotel", "start_time": "20:00", "end_time": "24:00",
         "price": 100, "cost": 100, "tickets": 1, "transports": []},
    ]}]}
    assert agent._remove_movable_activity(trial, 0, 0, "TestCity", 1) is False
