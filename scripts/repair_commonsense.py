#!/usr/bin/env python
"""Repair the Phase 1 commonsense-tail plans (docs/tpc_phase1_playbook.md, W1).

Reads results/best/<uid>.json, applies four ordered deterministic repair moves (R1-R4 below) on a
deepcopy, and writes the repaired plan to results/<method>/<uid>.json only when the full oracle
schema/commonsense checker accepts it -- scripts/merge.py remains the sole writer of results/best,
so adoption stays score-monotonic (merge.py's own strictly-greater score gate is a second,
independent guard).

Two variants are built independently and the better one (by ``_variant_key``) is returned:

  shift-first (R1-R4), applied in order on one working copy:
    R1 -- drop duplicate meal types (repeated_meal)
    R2 -- restore chronological list order (overlap: list-order-only cases)
    R3 -- re-space overlapping activities, dropping one if it can't fit (overlap: real time conflicts)
    R4 -- re-ground an inbound leg that starts before the previous activity ends
          (transport_before_prev_end), then R3 runs once more to absorb any ripple it creates

  drop-first (R1 + R5), for the days R3's forward shift can only make worse:
    R5 -- rebuild each day as a maximal feasible chain from the previous activity's real end
          position/time, dropping any activity a grounded leg cannot reach inside its own opening
          hours and meal band; intercity legs and accommodations are structural and never dropped

R1-R4 is the right move on a merely mistimed day; R5 is the right move on an overfull one, where
shifting ripples forward and pushes a later constraint-carrying activity out of its own window.

Every leg recomputation reuses TPCAgent's existing grounding helpers (_get_transport,
_lookup_poi_open_bounds, _activity_end_position/_activity_start_position) -- no new geometry.
Intercity (airplane/train) activities are never moved, dropped, or re-timed by any move.
"""
import argparse
import glob
import json
import os
import sys
from copy import deepcopy
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLIT_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")
DEFAULT_SPLIT = "p1_commonsense_tail"
DEFAULT_METHOD = "repair_commonsense"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
CHINATRAVEL_ROOT = os.path.join(ROOT, "chinatravel")
if CHINATRAVEL_ROOT not in sys.path:
    sys.path.insert(0, CHINATRAVEL_ROOT)
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent, time_to_minutes, minutes_to_time
from chinatravel.agent.tpc_agent.tpc_llm import TPCLLM
from chinatravel.data.load_datasets import NpEncoder, load_query
from chinatravel.environment.world_env import WorldEnv
from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py
from scan_commonsense_residual import flag_plan

MEAL_TYPES = ("breakfast", "lunch", "dinner")


def _split_path(name):
    return os.path.join(SPLIT_DIR, name + ".txt")


def _read_uids(split):
    with open(_split_path(split), encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4, cls=NpEncoder)


def _day_is_chronological(activities):
    """Structural-only chronology check over one day's activity list (mirrors the official
    Is_time_correct rules this repair targets, without needing WorldEnv)."""
    prev_end = None
    for activity in activities:
        try:
            start_min = time_to_minutes(activity["start_time"])
            end_min = time_to_minutes(activity["end_time"])
        except Exception:
            return False
        if prev_end is not None and start_min < prev_end:
            return False
        transports = activity.get("transports") or []
        if transports:
            try:
                t_start_min = time_to_minutes(transports[0]["start_time"])
            except Exception:
                t_start_min = None
            if t_start_min is not None and prev_end is not None and t_start_min < prev_end:
                return False
        prev_end = end_min
    return True


def _shift_activity(activity, new_start_min):
    """Shift `activity` later to start at new_start_min, preserving its own duration.

    Never moves an activity earlier -- a no-op if new_start_min is not later than its current
    start. Returns True if the activity's times changed.
    """
    old_start_min = time_to_minutes(activity["start_time"])
    if new_start_min <= old_start_min:
        return False
    old_end_min = time_to_minutes(activity["end_time"])
    delta = new_start_min - old_start_min
    activity["start_time"] = minutes_to_time(old_start_min + delta)
    activity["end_time"] = minutes_to_time(old_end_min + delta)
    return True


def _lookup_transport(agent, city, from_pos, to_pos, depart_time, people):
    """Shortest-time valid inner-city leg from from_pos to to_pos departing at depart_time.

    Uses the shortest-time valid mode (``_best_transport_via_get_transport``, the same lookup the
    Task 3 packing passes use for ATT protection) rather than ``_get_transport``'s default
    metro-first mode order: a repair should fix a broken *timing*, not silently swap a plan's
    existing fast taxi/walk hop for a much slower multi-leg metro detour just because that
    happens to be the generic default.

    Falls back to a forced free walk, with the query's derived inner-transport-mode exclusion
    temporarily lifted, when that lookup finds no route at all: a solver-time "metro only"
    heuristic derived from the query can make no route reachable for a short hop even when the
    stored plan already walked it for free, and walking never costs money, so retrying with it
    cannot break a budget-style oracle clause the exclusion was derived from -- unlike falling
    back to taxi/metro, which could. Never falls back to a paid mode. Returns (transports,
    arrival), possibly (None, None).
    """
    try:
        transports, arrival = agent._best_transport_via_get_transport(city, from_pos, to_pos, depart_time, people)
    except Exception:
        transports, arrival = None, None
    if transports is not None:
        return transports, arrival
    saved_forced = getattr(agent, "_forced_inner_mode", None)
    saved_excluded = agent._transport_constraints.get("excluded_inner_transport")
    try:
        agent._forced_inner_mode = "walk"
        agent._transport_constraints["excluded_inner_transport"] = []
        return agent._get_transport(agent.env, city, from_pos, to_pos, depart_time, people)
    except Exception:
        return None, None
    finally:
        agent._forced_inner_mode = saved_forced
        agent._transport_constraints["excluded_inner_transport"] = saved_excluded


def _reground_inbound(agent, city, people, prev_activity, activity, *, clamp):
    """Recompute `activity`'s inbound leg from `prev_activity`'s end position/time via
    ``_lookup_transport``. When `clamp` is set, also shifts `activity` later (preserving its
    duration) if the recomputed arrival is later than its current start -- except an intercity
    (airplane/train) activity, whose own ticketed start_time/end_time is never moved; its inbound
    leg (the hop to the boarding station/airport) is still recomputed and re-timed against
    ``prev_activity``, since that leg is exactly what ``transport_before_prev_end`` flags when it
    starts too early. Returns True if anything changed."""
    from_pos = agent._activity_end_position(prev_activity)
    to_pos = agent._activity_start_position(activity)
    depart_time = str(prev_activity.get("end_time", ""))
    if not (from_pos and to_pos and depart_time):
        return False
    transports, arrival = _lookup_transport(agent, city, from_pos, to_pos, depart_time, people)
    if transports is None:
        return False
    is_intercity = agent._is_intercity_activity(activity)
    if is_intercity and arrival:
        # The activity's own start_time is a fixed ticketed departure that can never move, so a
        # regrounded leg is only an improvement if it still arrives in time -- otherwise we would
        # trade "departs before the previous activity ends" for "arrives after its own
        # departure," an equally invalid chronology this repair cannot fix by shifting.
        try:
            arrival_min = time_to_minutes(arrival)
            own_start_min = time_to_minutes(activity["start_time"])
        except Exception:
            return False
        if arrival_min > own_start_min:
            return False
    changed = False
    if activity.get("transports") != transports:
        activity["transports"] = transports
        changed = True
    if clamp and arrival and not is_intercity:
        try:
            arrival_min = time_to_minutes(arrival)
        except Exception:
            arrival_min = None
        if arrival_min is not None and _shift_activity(activity, arrival_min):
            changed = True
    return changed


def _repair_duplicate_meals(agent, plan, query, city, people):
    """R1: keep exactly one activity per meal type per day, dropping the rest."""
    changed = False
    hard_logic_text = "\n".join(str(c) for c in (query.get("hard_logic_py") or [])).lower()
    for day in plan.get("itinerary", []) or []:
        activities = day.get("activities", []) or []
        for meal_type in MEAL_TYPES:
            indices = [i for i, a in enumerate(activities) if isinstance(a, dict) and a.get("type") == meal_type]
            if len(indices) <= 1:
                continue
            keep = None
            for i in indices:
                pos = str(activities[i].get("position", ""))
                if pos and pos.lower() in hard_logic_text:
                    keep = i
                    break
            if keep is None:
                for i in indices:
                    trial_day = [a for j, a in enumerate(activities) if j == i or j not in indices]
                    if _day_is_chronological(trial_day):
                        keep = i
                        break
            if keep is None:
                keep = indices[0]
            for idx in sorted((i for i in indices if i != keep), reverse=True):
                prev_act = activities[idx - 1] if idx > 0 else None
                del activities[idx]
                changed = True
                if prev_act is not None and idx < len(activities):
                    _reground_inbound(agent, city, people, prev_act, activities[idx], clamp=True)
    return changed


def _restore_chronological_order(agent, plan, query, city, people):
    """R2: sort each day's activities by start_time, holding an intercity head/tail fixed."""
    changed = False
    for day in plan.get("itinerary", []) or []:
        activities = day.get("activities", []) or []
        if len(activities) < 2:
            continue
        head_fixed = agent._is_intercity_activity(activities[0])
        tail_fixed = agent._is_intercity_activity(activities[-1])
        start = 1 if head_fixed else 0
        end = len(activities) - 1 if tail_fixed else len(activities)
        middle = activities[start:end]
        if len(middle) < 2:
            continue
        sorted_middle = sorted(middle, key=lambda a: time_to_minutes(a["start_time"]))
        if [id(a) for a in sorted_middle] == [id(a) for a in middle]:
            continue
        new_activities = activities[:start] + sorted_middle + activities[end:]
        day["activities"] = new_activities
        activities = new_activities
        changed = True
        for idx in range(1, len(activities)):
            _reground_inbound(agent, city, people, activities[idx - 1], activities[idx], clamp=False)
    return changed


def _respace_overlaps(agent, plan, query, city, people):
    """R3: walk each day forward: shift an overlapping activity later (preserving its duration),
    or drop it if the shift would miss its POI closing time or a fixed intercity tail."""
    changed = False
    for day in plan.get("itinerary", []) or []:
        activities = day.get("activities", []) or []
        idx = 1
        while idx < len(activities):
            activity = activities[idx]
            prev_activity = activities[idx - 1]
            if agent._is_intercity_activity(activity):
                idx += 1
                continue
            try:
                prev_end_min = time_to_minutes(prev_activity["end_time"])
                start_min = time_to_minutes(activity["start_time"])
            except Exception:
                idx += 1
                continue
            if start_min >= prev_end_min:
                idx += 1
                continue

            from_pos = agent._activity_end_position(prev_activity)
            to_pos = agent._activity_start_position(activity)
            transports, arrival = _lookup_transport(
                agent, city, from_pos, to_pos, str(prev_activity["end_time"]), people)
            if transports is None or arrival is None:
                idx += 1
                continue

            new_start_min = max(start_min, time_to_minutes(arrival))
            duration = time_to_minutes(activity["end_time"]) - start_min
            new_end_min = new_start_min + duration

            fits = True
            try:
                bounds = agent._lookup_poi_open_bounds(
                    city, agent._activity_start_position(activity), activity.get("type"), activity.get("tickets"))
            except Exception:
                bounds = None
            if bounds is not None and new_end_min > bounds[1]:
                fits = False
            if idx + 1 < len(activities) and agent._is_intercity_activity(activities[idx + 1]):
                next_start_min = time_to_minutes(activities[idx + 1]["start_time"])
                if new_start_min > next_start_min:
                    fits = False

            if not fits:
                del activities[idx]
                changed = True
                if idx < len(activities):
                    _reground_inbound(agent, city, people, prev_activity, activities[idx], clamp=True)
                continue

            activity["transports"] = transports
            activity["start_time"] = minutes_to_time(new_start_min)
            activity["end_time"] = minutes_to_time(new_end_min)
            changed = True
            idx += 1
    return changed


def _reground_early_transport(agent, plan, query, city, people):
    """R4: an inbound leg that starts before the previous activity ends is re-requested from the
    previous activity's actual end_time, and the activity is shifted to the returned arrival."""
    changed = False
    for day in plan.get("itinerary", []) or []:
        activities = day.get("activities", []) or []
        for idx in range(1, len(activities)):
            activity = activities[idx]
            prev_activity = activities[idx - 1]
            transports = activity.get("transports") or []
            if not transports:
                continue
            try:
                t_start_min = time_to_minutes(transports[0]["start_time"])
                prev_end_min = time_to_minutes(prev_activity["end_time"])
            except Exception:
                continue
            if t_start_min >= prev_end_min:
                continue
            if _reground_inbound(agent, city, people, prev_activity, activity, clamp=True):
                changed = True
    return changed


MEAL_BANDS = {
    "breakfast": (time_to_minutes("06:00"), time_to_minutes("09:00")),
    "lunch": (time_to_minutes("11:00"), time_to_minutes("14:00")),
    "dinner": (time_to_minutes("17:00"), time_to_minutes("20:00")),
}


def _rebuild_day_by_dropping(agent, plan, query, city, people, protect_named=True, prefer_cheap=False):
    """R5: rebuild each day as a maximal feasible chain, dropping what cannot be made to fit.

    R3 shifts an overlapping activity later and only drops it as a last resort, which is the right
    move when the day is merely mistimed. It is the wrong move when the day is *overfull* -- the
    shift ripples forward and pushes a later, constraint-carrying activity (a named restaurant with
    a clause window, a POI that must open before noon) out of its own band, so the repair trades one
    failure for another. This move takes the opposite side: it walks the day in chronological order
    from the previous activity's real end position/time, keeps an activity only when a grounded leg
    reaches it inside its own opening hours and meal band, and otherwise removes it outright.

    Intercity legs and accommodations are structural and never dropped -- an intercity activity
    keeps its ticketed times and only has its inbound leg recomputed, and an accommodation is
    shifted to its arrival. ``repair_plan`` runs this as an alternative variant, not a replacement,
    and keeps whichever variant scores better.
    """
    changed = False
    itinerary = plan.get("itinerary", []) or []
    for day_idx, day in enumerate(itinerary):
        activities = day.get("activities", []) or []
        if len(activities) < 2:
            continue

        head_fixed = agent._is_intercity_activity(activities[0])
        tail_fixed = agent._is_intercity_activity(activities[-1])
        start = 1 if head_fixed else 0
        end = len(activities) - 1 if tail_fixed else len(activities)
        head = activities[:start]
        tail = activities[end:]
        middle = sorted(activities[start:end], key=lambda a: time_to_minutes(a["start_time"]))
        if not middle:
            continue

        anchor = head[-1] if head else _day_start_anchor(agent, plan, day_idx, activities)
        protected = _clause_named_positions(query) if protect_named else set()

        kept = []
        index = 0
        while index < len(middle):
            activity = middle[index]
            index += 1
            cursor = kept[-1] if kept else anchor
            if cursor is None:
                # No anchor to chain from (day 1 of a trip that starts in the target city): keep
                # the stored entry and its stored inbound leg rather than inventing one.
                kept.append(activity)
                continue
            placed = _place_activity(
                agent, city, people, cursor, activity, tail, prefer_cheap=prefer_cheap)
            if placed is None:
                if activity.get("type") == "accommodation":
                    # Never drop the night's stay; park it wherever it can be reached.
                    parked = _place_activity(
                        agent, city, people, cursor, activity, tail, relax=True,
                        prefer_cheap=prefer_cheap)
                    if parked is not None:
                        _commit_placement(activity, parked)
                        kept.append(activity)
                        changed = True
                        continue
                    kept.append(activity)
                    continue
                changed = True
                continue

            transports, new_start_min, new_end_min = placed
            if (
                new_start_min > time_to_minutes(activity["start_time"])
                and _is_protected(activity, protected)
                and kept
                and not _is_protected(kept[-1], protected)
                and kept[-1].get("type") != "accommodation"
            ):
                # This activity carries its own hard-logic time window, so shifting it later is
                # exactly the trade R3 makes and this variant exists to avoid. Drop whatever sits
                # in front of it instead and retry from the earlier cursor.
                kept.pop()
                index -= 1
                changed = True
                continue

            _commit_placement(activity, placed)
            kept.append(activity)
            changed = True

        # A fixed departure leg is only reachable if the last kept activity leaves enough time to
        # travel to the boarding point. "Ends before the flight departs" is not the same test --
        # a 45-minute dinner that ends at 18:07 still misses an 18:32 flight an hour's ride away,
        # and that gap is exactly what leaves `transport_before_prev_end` flagged after R4 declines
        # to reground the leg. Trim trailing droppable activities until the leg grounds.
        if tail:
            while True:
                last = kept[-1] if kept else (head[-1] if head else None)
                if last is None or last is tail[0]:
                    break
                if _tail_is_reachable(agent, city, people, last, tail[0]):
                    break
                if not kept or kept[-1].get("type") == "accommodation":
                    break
                kept.pop()
                changed = True
            last = kept[-1] if kept else (head[-1] if head else None)
            if last is not None and last is not tail[0]:
                _reground_inbound(agent, city, people, last, tail[0], clamp=False)

        new_activities = head + kept + tail
        if [id(a) for a in new_activities] != [id(a) for a in activities]:
            changed = True
        day["activities"] = new_activities
    return changed


def _day_start_anchor(agent, plan, day_idx, activities):
    """Where a non-arrival day actually begins, in the space checker's own terms: the end position
    of the *previous day's last activity* (in practice the night's hotel), departing no earlier
    than this day's stored opening leg. Returns a synthetic activity-shaped cursor, or ``None``
    for day 1, whose start is the inbound intercity leg instead.

    The position chain the checker walks is global across days, so reordering or de-duplicating a
    day's opening activity must not silently change where that day starts -- deriving the anchor
    from the stored plan's own opening leg would do exactly that once R1 drops the activity that
    carried it.
    """
    if day_idx <= 0:
        return None
    try:
        previous = plan["itinerary"][day_idx - 1]["activities"][-1]
    except Exception:
        return None
    position = agent._activity_end_position(previous)
    if not position:
        return None
    depart = None
    for activity in activities:
        legs = activity.get("transports") or []
        if legs and legs[0].get("start_time"):
            depart = str(legs[0]["start_time"])
            break
        if activity.get("start_time"):
            depart = str(activity["start_time"])
            break
    if not depart:
        return None
    return {"type": "accommodation", "position": position, "end_time": depart}


def _clause_named_positions(query):
    """POI names a hard_logic_py clause mentions by name, lowercased.

    A clause that pins a named POI to a time window is the one thing a forward shift most often
    breaks, so R5 refuses to move these and drops their neighbours instead.
    """
    text = "\n".join(str(c) for c in (query.get("hard_logic_py") or []))
    names = set()
    for chunk in text.split("'"):
        chunk = chunk.strip()
        if len(chunk) > 3 and not chunk.isidentifier():
            names.add(chunk.lower())
    return names


def _is_protected(activity, protected):
    position = str(activity.get("position", "") or "").strip().lower()
    return bool(position) and position in protected


def _place_activity(agent, city, people, cursor, activity, tail, relax=False, prefer_cheap=False):
    """Try to reach `activity` from `cursor`, returning (transports, start_min, end_min) or None.

    Prefers a leg in the activity's own stored mode -- a repair should fix a broken timing, not
    silently upgrade a free walk to a paid taxi and blow an inner-city-cost clause -- and falls back
    to the shortest-time valid mode when the stored one no longer fits. ``relax`` skips the
    fit tests, for structural activities that must be kept regardless. ``prefer_cheap`` widens the
    candidate modes and returns the cheapest leg that fits rather than the first, for queries whose
    clauses cap inner-city transport spend; feasibility comes before the ATT the faster mode buys,
    since a rejected plan scores zero on every preference term anyway.
    """
    if cursor is None:
        return None
    from_pos = agent._activity_end_position(cursor)
    to_pos = agent._activity_start_position(activity)
    depart = str(cursor.get("end_time", ""))
    if not (from_pos and to_pos and depart):
        return None
    try:
        old_start_min = time_to_minutes(activity["start_time"])
        duration = max(1, time_to_minutes(activity["end_time"]) - old_start_min)
    except Exception:
        return None

    kind = activity.get("type")
    stored_legs = activity.get("transports") or []
    stored_mode = str(stored_legs[0].get("mode", "")).strip().lower() if stored_legs else ""

    modes = [stored_mode] if stored_mode in ("walk", "metro", "taxi") else []
    if prefer_cheap:
        modes += [m for m in ("walk", "metro", "taxi") if m not in modes]
    options = []
    for mode in modes:
        saved_forced = getattr(agent, "_forced_inner_mode", None)
        try:
            agent._forced_inner_mode = mode
            options.append(agent._get_transport(agent.env, city, from_pos, to_pos, depart, people))
        except Exception:
            pass
        finally:
            agent._forced_inner_mode = saved_forced
    options.append(_lookup_transport(agent, city, from_pos, to_pos, depart, people))

    fallback = None
    fitting = []
    for transports, arrival in options:
        if transports is None or arrival is None:
            continue
        try:
            arrival_min = time_to_minutes(arrival)
        except Exception:
            continue
        start_min = max(arrival_min, old_start_min)
        end_min = start_min + duration
        if kind == "accommodation":
            try:
                end_min = max(end_min, time_to_minutes(activity["end_time"]))
            except Exception:
                pass
        candidate = (transports, start_min, end_min)
        if fallback is None:
            fallback = candidate
        if relax:
            return candidate
        if kind in MEAL_BANDS:
            band_open, band_close = MEAL_BANDS[kind]
            if start_min >= band_close or end_min > band_close or end_min <= band_open:
                continue
        try:
            bounds = agent._lookup_poi_open_bounds(city, to_pos, kind, activity.get("tickets"))
        except Exception:
            bounds = None
        if bounds is not None and (start_min < bounds[0] or end_min > bounds[1]):
            continue
        if tail:
            try:
                if end_min > time_to_minutes(tail[0]["start_time"]):
                    continue
            except Exception:
                pass
        if not prefer_cheap:
            return candidate
        fitting.append(candidate)
    if fitting:
        return min(fitting, key=lambda c: (_legs_cost(c[0]), c[2]))
    return fallback if relax else None


def _legs_cost(transports):
    total = 0.0
    for leg in transports or []:
        try:
            total += float(leg.get("cost", 0) or 0)
        except Exception:
            continue
    return total


def _commit_placement(activity, placed):
    transports, start_min, end_min = placed
    activity["transports"] = transports
    activity["start_time"] = minutes_to_time(start_min)
    activity["end_time"] = minutes_to_time(end_min)


def _tail_is_reachable(agent, city, people, prev_activity, tail_activity):
    """True when a grounded leg from `prev_activity`'s end reaches `tail_activity`'s boarding
    point no later than its own fixed departure time."""
    from_pos = agent._activity_end_position(prev_activity)
    to_pos = agent._activity_start_position(tail_activity)
    depart = str(prev_activity.get("end_time", ""))
    if not (from_pos and to_pos and depart):
        return True
    transports, arrival = _lookup_transport(agent, city, from_pos, to_pos, depart, people)
    if transports is None or arrival is None:
        return False
    try:
        return time_to_minutes(arrival) <= time_to_minutes(tail_activity["start_time"])
    except Exception:
        return True


def _repair_shift_first(agent, plan, query, city, people):
    """The original R1-R4 chain: prefer re-timing an activity over removing it."""
    _repair_duplicate_meals(agent, plan, query, city, people)
    _restore_chronological_order(agent, plan, query, city, people)
    _respace_overlaps(agent, plan, query, city, people)
    _reground_early_transport(agent, plan, query, city, people)
    _respace_overlaps(agent, plan, query, city, people)  # absorb any ripple R4 introduced


def _repair_drop_first(agent, plan, query, city, people):
    """R1 + R5: de-duplicate meals, then rebuild each day as a maximal feasible chain."""
    _repair_duplicate_meals(agent, plan, query, city, people)
    _rebuild_day_by_dropping(agent, plan, query, city, people, protect_named=True)
    _reground_early_transport(agent, plan, query, city, people)


def _repair_drop_first_unprotected(agent, plan, query, city, people):
    """R1 + R5 without the named-POI protection.

    Refusing to move a clause-named POI costs whatever sits in front of it, which is the right
    trade when that clause pins a time window and the wrong one when it only names the POI. Both
    are cheap to build, so run each and let ``_variant_key`` decide.
    """
    _repair_duplicate_meals(agent, plan, query, city, people)
    _rebuild_day_by_dropping(agent, plan, query, city, people, protect_named=False)
    _reground_early_transport(agent, plan, query, city, people)


def _repair_drop_first_cheap(agent, plan, query, city, people):
    """R1 + R5 choosing the cheapest fitting leg instead of the first.

    A query whose clauses cap inner-city transport spend can be pushed over the cap by the repair
    itself: every regrounded hop is free to pick a paid mode, and the tail's ride to the station is
    the most expensive one in the plan. This variant trades hop time for fare wherever both ground.
    """
    _repair_duplicate_meals(agent, plan, query, city, people)
    _rebuild_day_by_dropping(agent, plan, query, city, people, protect_named=True, prefer_cheap=True)
    _reground_early_transport(agent, plan, query, city, people)


def _variant_key(agent, query, plan):
    """Rank a repair variant the way the leaderboard does: full acceptance first, then the
    schema+commonsense gate that every other component is conditioned on, then satisfied clauses,
    then the DAV/ATT/DDR preference sum (which only counts for a fully accepted plan)."""
    try:
        schema_ok = bool(agent._schema_ok(query, plan))
    except Exception:
        schema_ok = False
    try:
        commonsense_ok = bool(agent._commonsense_ok(query, plan))
    except Exception:
        commonsense_ok = False
    clauses = query.get("hard_logic_py") or []
    try:
        results = evaluate_constraints_py(clauses, plan, verbose=False)
        passed = sum(1 for r in results if bool(r))
    except Exception:
        passed = 0
    env_ok = schema_ok and commonsense_ok
    full = env_ok and bool(clauses) and passed == len(clauses)
    preference = 0.0
    if full:
        try:
            preference = float(sum(agent._default_preference_components(plan)))
        except Exception:
            preference = 0.0
    return (1 if full else 0, 1 if env_ok else 0, passed, preference)


def repair_plan(agent, plan, query):
    """Return the best of the shift-first (R1-R4) and the two drop-first (R1+R5) repair variants.

    Both run on their own deepcopy of the stored plan; the caller gates the commit.
    """
    city = str(query.get("target_city", ""))
    people = int(query.get("people_number", 1) or 1)
    agent._set_transport_context(agent._collect_constraints(query))

    best = None
    best_key = None
    for build in (
        _repair_shift_first,
        _repair_drop_first,
        _repair_drop_first_unprotected,
        _repair_drop_first_cheap,
    ):
        trial = deepcopy(plan)
        try:
            build(agent, trial, query, city, people)
        except Exception:
            continue
        key = _variant_key(agent, query, trial)
        if best_key is None or key > best_key:
            best, best_key = trial, key
    return best if best is not None else deepcopy(plan)


def _residual_reason(query, plan):
    families = flag_plan(plan)
    return ",".join(sorted(families)) if families else "logical_clause_failure"


def _process(args):
    method = args.method or DEFAULT_METHOD
    result_dir = os.path.join(ROOT, "results", method)
    best_dir = os.path.join(ROOT, "results", "best")
    os.makedirs(result_dir, exist_ok=True)

    query_args = SimpleNamespace(splits=args.split, lang="en", oracle_translation=True)
    uids, query_data = load_query(query_args)
    if args.limit:
        uids = uids[: args.limit]

    considered = repaired = written = unresolved = 0
    unresolved_uids = []

    if args.dry_run:
        for uid in uids:
            best_path = os.path.join(best_dir, uid + ".json")
            if not os.path.exists(best_path):
                continue
            plan = _load_json(best_path)
            considered += 1
            families = flag_plan(plan)
            print("repair_commonsense: {} applicable repairs: {}".format(
                uid, ",".join(sorted(families)) if families else "none"))
        print("repair_commonsense: dry-run considered={}".format(considered))
        return 0

    agent = TPCAgent(
        env=WorldEnv(lang="en"),
        backbone_llm=TPCLLM(),
        cache_dir=os.path.join(ROOT, "cache"),
        log_dir=os.path.join(ROOT, "cache", "repair_commonsense"),
        debug=True,
        lang="en",
    )

    for uid in uids:
        best_path = os.path.join(best_dir, uid + ".json")
        if not os.path.exists(best_path):
            continue
        plan = _load_json(best_path)
        query = query_data.get(uid)
        if query is None:
            continue
        plan.pop("_eval_score", None)
        considered += 1
        constraints = agent._collect_constraints(query)
        check = agent._make_checker(query, constraints)
        try:
            trial = repair_plan(agent, plan, query)
        except Exception as exc:
            print("repair_commonsense: {} raised during repair: {}".format(uid, exc))
            unresolved += 1
            unresolved_uids.append((uid, "exception:{}".format(exc)))
            continue

        try:
            accepted = agent._accepted(*check(trial))
        except Exception:
            accepted = False
        if accepted:
            repaired += 1
            _save_json(os.path.join(result_dir, uid + ".json"), trial)
            written += 1
        else:
            unresolved += 1
            unresolved_uids.append((uid, _residual_reason(query, trial)))

    print("repair_commonsense: considered={} repaired={} written={} unresolved={}".format(
        considered, repaired, written, unresolved))
    if unresolved_uids:
        print("repair_commonsense: unresolved uids (uid, residual):")
        for uid, reason in unresolved_uids:
            print("  {}  {}".format(uid, reason))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default=DEFAULT_SPLIT, help="split file of uids to process")
    ap.add_argument("--method", default=None, help="results/ output directory (default: repair_commonsense)")
    ap.add_argument("--limit", type=int, default=None, help="process at most N uids")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true",
                     help="report the repair each plan would receive, write nothing")
    args = ap.parse_args()
    return _process(args)


if __name__ == "__main__":
    sys.exit(main())
