"""Unit tests for the opt-in cascading forward-shift move (``_enforce_windows_in_order``) and its
``TPC_CASCADE_TIMED_WINDOWS`` gate inside ``_pin_timed_windows``.

Same harness as ``test_resequence_day.py``: a bare ``TPCAgent`` (``__new__``, no WorldEnv) with a
zero-travel ``_get_transport`` stub (arrival == requested departure), so the tests reason about
absolute clock times without a transport graph. These exercise the case neither
``_try_pin_activity`` (reverts a push onto the next activity) nor ``_resequence_day`` (bails when the
order is already correct) handles: a day in the right order whose windowed activity starts too early,
where clamping it into its window ripples a delay through the following activities.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent  # noqa: E402


def _bare_agent():
    agent = TPCAgent.__new__(TPCAgent)
    agent.use_oracle = True
    agent.env = None
    # Zero travel time: arrival == requested departure clock.
    agent._get_transport = lambda env, city, frm, to, depart, people: ([], depart)
    return agent


# Day 0 is already in the correct order, but the hotel breakfast is slotted 07:30-08:20 -- before
# its required [07:50, 08:40] window -- and the next activity sits right after it, so pushing the
# breakfast into its window forces the following activity later (the cascade _try_pin_activity
# refuses and _resequence_day skips).
def _early_breakfast_plan(museum_end="09:30", tail_start="20:00"):
    return {
        "itinerary": [
            {
                "activities": [
                    {"type": "breakfast", "position": "Inn", "start_time": "07:30",
                     "end_time": "08:20", "price": 0, "cost": 0, "transports": []},
                    {"type": "attraction", "position": "Museum", "start_time": "08:30",
                     "end_time": museum_end, "price": 0, "cost": 0, "tickets": 1, "transports": []},
                    {"type": "accommodation", "position": "Inn", "start_time": tail_start,
                     "end_time": "24:00", "price": 100, "cost": 100, "rooms": 1, "room_type": 2,
                     "tickets": 1, "transports": []},
                ]
            }
        ]
    }


WINDOW = {"location": "Inn", "earliest": "07:50", "latest": None,
          "end_after": None, "end_before": "08:40"}


def _breakfast_window_checker():
    def check(plan):
        for day in plan.get("itinerary", []):
            for a in day.get("activities", []):
                if a.get("type") == "breakfast" and a.get("position") == "Inn":
                    if a.get("start_time", "") >= "07:50" and a.get("end_time", "") <= "08:40":
                        return (1, 1)
        return (0, 1)
    return check


def test_enforce_windows_commits_cascading_forward_shift():
    agent = _bare_agent()
    plan = _early_breakfast_plan()
    constraints = {"activity_time_windows": [WINDOW]}
    check = _breakfast_window_checker()
    assert agent._accepted(*check(plan)) is False

    committed = agent._enforce_windows_in_order(plan, 0, {"target_city": "TestCity"}, constraints, check)

    assert committed is True
    acts = plan["itinerary"][0]["activities"]
    # Breakfast clamped into its window...
    assert acts[0]["start_time"] == "07:50"
    assert acts[0]["end_time"] == "08:40"
    # ...and the delay rippled onto the following (unwindowed) attraction, preserving its 60-min dwell.
    assert acts[1]["start_time"] == "08:40"
    assert acts[1]["end_time"] == "09:40"
    assert agent._accepted(*check(plan)) is True


def test_enforce_windows_reverts_when_ripple_makes_tail_unreachable():
    agent = _bare_agent()
    # A long attraction: clamping the breakfast to 08:40 ripples the attraction to 08:40-12:10,
    # which overruns a fixed downstream activity starting at 12:00 -- the relayout's tail guard must
    # reject, leaving the plan untouched.
    plan = _early_breakfast_plan(museum_end="12:00", tail_start="12:00")
    constraints = {"activity_time_windows": [WINDOW]}
    check = _breakfast_window_checker()

    committed = agent._enforce_windows_in_order(plan, 0, {"target_city": "TestCity"}, constraints, check)

    assert committed is False
    acts = plan["itinerary"][0]["activities"]
    assert acts[0]["start_time"] == "07:30"  # unchanged
    assert acts[0]["end_time"] == "08:20"


def test_enforce_windows_noop_without_windows():
    agent = _bare_agent()
    plan = _early_breakfast_plan()
    check = _breakfast_window_checker()
    assert agent._enforce_windows_in_order(plan, 0, {"target_city": "TestCity"}, {}, check) is False
    assert plan["itinerary"][0]["activities"][0]["start_time"] == "07:30"


def test_pin_flow_gate_off_leaves_early_window_unpinned(monkeypatch):
    """Byte-identical-floor guard: with TPC_CASCADE_TIMED_WINDOWS unset, _pin_timed_windows must not
    reach the cascade fallback -- _try_pin_activity reverts the push and _resequence_day bails, so
    the early breakfast stays put, exactly as before this move existed."""
    monkeypatch.delenv("TPC_CASCADE_TIMED_WINDOWS", raising=False)
    agent = _bare_agent()
    calls = {"cascade": 0}
    real_cascade = agent._enforce_windows_in_order

    def spy(*a, **k):
        calls["cascade"] += 1
        return real_cascade(*a, **k)

    agent._enforce_windows_in_order = spy
    plan = _early_breakfast_plan()
    constraints = {"activity_time_windows": [WINDOW]}
    check = _breakfast_window_checker()

    agent._pin_timed_windows(plan, {"target_city": "TestCity", "people_number": 1}, constraints, check)

    assert calls["cascade"] == 0  # fallback never invoked when the flag is off
    assert plan["itinerary"][0]["activities"][0]["start_time"] == "07:30"  # breakfast unpinned
    assert agent._accepted(*check(plan)) is False


def test_pin_flow_gate_on_fixes_early_window_via_cascade(monkeypatch):
    monkeypatch.setenv("TPC_CASCADE_TIMED_WINDOWS", "1")
    agent = _bare_agent()
    calls = {"cascade": 0}
    real_cascade = agent._enforce_windows_in_order

    def spy(*a, **k):
        calls["cascade"] += 1
        return real_cascade(*a, **k)

    agent._enforce_windows_in_order = spy
    plan = _early_breakfast_plan()
    constraints = {"activity_time_windows": [WINDOW]}
    check = _breakfast_window_checker()

    agent._pin_timed_windows(plan, {"target_city": "TestCity", "people_number": 1}, constraints, check)

    assert calls["cascade"] >= 1  # fallback invoked once try_pin/resequence fail
    assert plan["itinerary"][0]["activities"][0]["start_time"] == "07:50"  # breakfast pinned
    assert plan["itinerary"][0]["activities"][0]["end_time"] == "08:40"
    assert agent._accepted(*check(plan)) is True
