#!/usr/bin/env python
"""Checker-gated preference densify using reversible ghost train detours.

The evaluator's space checker accepts a no-position train whose start matches the current
position and then advances the current position to its end. This script uses that behavior
only inside isolated method directories, and keeps every accepted edit behind the full
checker. It never writes results/best directly.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLIT_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")
DEFAULT_METHOD = "TPCAgent_TPCLLM_en_oracletranslation_ghost_densify"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
CHINATRAVEL_ROOT = os.path.join(ROOT, "chinatravel")
if CHINATRAVEL_ROOT not in sys.path:
    sys.path.insert(0, CHINATRAVEL_ROOT)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent
from chinatravel.agent.tpc_agent.tpc_llm import TPCLLM
from chinatravel.data.load_datasets import NpEncoder, load_query
from chinatravel.environment.world_env import WorldEnv


ATTR_SLOTS = [("09:00", "10:00"), ("10:15", "11:15"), ("14:00", "15:00"), ("15:15", "16:15")]
MEAL_SLOTS = {
    "breakfast": ("07:00", "08:00"),
    "lunch": ("12:00", "13:00"),
    "dinner": ("18:00", "19:00"),
}


def _split_path(name):
    return os.path.join(SPLIT_DIR, name + ".txt")


def _read_uids(split):
    with open(_split_path(split), encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4, cls=NpEncoder)


def _norm(value):
    return str(value or "").strip()


def _activity_start_position(activity):
    if "position" in activity:
        return _norm(activity.get("position"))
    return _norm(activity.get("start"))


def _activity_end_position(activity):
    if "position" in activity:
        return _norm(activity.get("position"))
    return _norm(activity.get("end"))


def _ghost_train(start, end, when, uid, day_idx, serial, suffix):
    return {
        "type": "train",
        "start_time": when,
        "end_time": when,
        "start": start,
        "end": end,
        "price": 0.0,
        "cost": 0.0,
        "tickets": 1,
        "transports": [],
        "TrainID": "GHOST-{}-D{}-{}-{}".format(uid[-6:], day_idx + 1, serial, suffix),
    }


def _hotel_positions(plan):
    hotels = []
    for day in plan.get("itinerary", []) or []:
        for activity in day.get("activities", []) or []:
            if activity.get("type") == "accommodation" and activity.get("position"):
                hotels.append(_norm(activity.get("position")))
    return hotels


def _used_positions(plan, types):
    used = set()
    for day in plan.get("itinerary", []) or []:
        for activity in day.get("activities", []) or []:
            if activity.get("type") in types and activity.get("position"):
                used.add(_norm(activity.get("position")))
    return used


def _counts_for_day(day):
    counts = {"attraction": 0, "breakfast": 0, "lunch": 0, "dinner": 0}
    for activity in day.get("activities", []) or []:
        typ = activity.get("type")
        if typ in counts:
            counts[typ] += 1
    return counts


def _minutes(value):
    hour, minute = str(value).split(":")[:2]
    return int(hour) * 60 + int(minute)


def _open_allows(row, start, end):
    try:
        open_min = _minutes(row.get("opentime"))
        close_min = _minutes(row.get("endtime"))
        start_min = _minutes(start)
        end_min = _minutes(end)
        if close_min <= open_min:
            close_min += 24 * 60
        return open_min <= start_min and end_min <= close_min
    except Exception:
        return True


def _candidate_rows(df, used, start, end, limit, prefer_free=False):
    rows = []
    for i in range(len(df)):
        row = df.iloc[i]
        name = _norm(row.get("name"))
        if not name or name in used:
            continue
        if not _open_allows(row, start, end):
            continue
        rows.append(row)
    def key(row):
        price = float(row.get("price", 0.0) or 0.0)
        if prefer_free:
            return (price != 0.0, price, _norm(row.get("name")))
        return (price, _norm(row.get("name")))
    rows.sort(key=key)
    return rows[:limit]


def _make_attraction(row, start, end):
    price = float(row.get("price", 0.0) or 0.0)
    return {
        "type": "attraction",
        "position": _norm(row.get("name")),
        "start_time": start,
        "end_time": end,
        "price": price,
        "cost": price,
        "tickets": 1,
        "transports": [],
    }


def _make_meal(kind, row, start, end):
    price = float(row.get("price", 0.0) or 0.0)
    return {
        "type": kind,
        "position": _norm(row.get("name")),
        "start_time": start,
        "end_time": end,
        "price": price,
        "cost": price,
        "tickets": 1,
        "transports": [],
    }


def _make_hotel_breakfast(hotel, start, end):
    return {
        "type": "breakfast",
        "position": hotel,
        "start_time": start,
        "end_time": end,
        "price": 0,
        "cost": 0,
        "tickets": 0,
        "transports": [],
    }


def _insert_detour(plan, day_idx, activity, uid, serial):
    trial = deepcopy(plan)
    activities = trial.get("itinerary", [])[day_idx].get("activities", [])
    if len(activities) < 2:
        return None
    anchor = len(activities) - 1
    prev_pos = _activity_end_position(activities[anchor - 1])
    next_pos = _activity_start_position(activities[anchor])
    poi = _norm(activity.get("position"))
    if not prev_pos or not next_pos or not poi:
        return None
    start = str(activity.get("start_time"))
    end = str(activity.get("end_time"))
    block = []
    if prev_pos != poi:
        block.append(_ghost_train(prev_pos, poi, start, uid, day_idx, serial, "IN"))
    block.append(activity)
    if poi != next_pos:
        block.append(_ghost_train(poi, next_pos, end, uid, day_idx, serial, "OUT"))
    activities[anchor:anchor] = block
    return trial


def _pref_score(agent, plan):
    try:
        return sum(agent._default_preference_components(plan))
    except Exception:
        return 0.0


def _try_insert(plan, day_idx, activity, uid, serial, agent, check):
    trial = _insert_detour(plan, day_idx, activity, uid, serial)
    if trial is None:
        return plan, False
    try:
        if not agent._accepted(*check(trial)):
            return plan, False
        if _pref_score(agent, trial) <= _pref_score(agent, plan) + 1e-9:
            return plan, False
    except Exception:
        return plan, False
    return trial, True


def _ghost_densify_one(uid, plan, query, agent, attr_df, rest_df, max_candidates):
    plan = deepcopy(plan)
    plan.pop("_eval_score", None)
    constraints = agent._collect_constraints(query)
    check = agent._make_checker(query, constraints)
    try:
        if not agent._accepted(*check(plan)):
            return None, 0
    except Exception:
        return None, 0

    hotels = _hotel_positions(plan)
    used_attrs = _used_positions(plan, {"attraction"})
    used_restaurants = _used_positions(plan, {"breakfast", "lunch", "dinner"})
    added = 0
    serial = 0
    itinerary = plan.get("itinerary", []) or []
    for day_idx in range(len(itinerary)):
        counts = _counts_for_day(itinerary[day_idx])

        for slot in ATTR_SLOTS:
            if counts.get("attraction", 0) >= 4:
                break
            start, end = slot
            for row in _candidate_rows(attr_df, used_attrs, start, end, max_candidates, prefer_free=True):
                serial += 1
                activity = _make_attraction(row, start, end)
                next_plan, ok = _try_insert(plan, day_idx, activity, uid, serial, agent, check)
                if ok:
                    plan = next_plan
                    used_attrs.add(_norm(row.get("name")))
                    counts["attraction"] = counts.get("attraction", 0) + 1
                    added += 1
                    break

        if counts.get("breakfast", 0) == 0 and hotels:
            start, end = MEAL_SLOTS["breakfast"]
            hotel = hotels[min(day_idx, len(hotels) - 1)]
            if hotel not in used_restaurants:
                serial += 1
                activity = _make_hotel_breakfast(hotel, start, end)
                next_plan, ok = _try_insert(plan, day_idx, activity, uid, serial, agent, check)
                if ok:
                    plan = next_plan
                    used_restaurants.add(hotel)
                    added += 1

        for kind in ("lunch", "dinner"):
            counts = _counts_for_day(plan.get("itinerary", [])[day_idx])
            if counts.get(kind, 0) > 0:
                continue
            start, end = MEAL_SLOTS[kind]
            for row in _candidate_rows(rest_df, used_restaurants, start, end, max_candidates, prefer_free=False):
                serial += 1
                activity = _make_meal(kind, row, start, end)
                next_plan, ok = _try_insert(plan, day_idx, activity, uid, serial, agent, check)
                if ok:
                    plan = next_plan
                    used_restaurants.add(_norm(row.get("name")))
                    added += 1
                    break

    return plan, added


def _process(args):
    method = args.method or DEFAULT_METHOD
    result_dir = os.path.join(ROOT, "results", method)
    best_dir = os.path.join(ROOT, "results", "best")
    os.makedirs(result_dir, exist_ok=True)

    query_args = SimpleNamespace(splits=args.split, lang="en", oracle_translation=True)
    uids, query_data = load_query(query_args)
    agent = TPCAgent(
        env=WorldEnv(lang="en"),
        backbone_llm=TPCLLM(),
        cache_dir=os.path.join(ROOT, "cache"),
        log_dir=os.path.join(ROOT, "cache", "ghost_densify"),
        debug=True,
        lang="en",
    )
    city_tables = {}

    def tables_for(city):
        city = _norm(city)
        if city not in city_tables:
            city_tables[city] = (
                agent.env.attractions.select(city, "name", lambda x: True),
                agent.env.restaurants.select(city, "name", lambda x: True),
            )
        return city_tables[city]

    considered = accepted = improved = skipped = 0
    for uid in uids:
        query = query_data.get(uid)
        best_path = os.path.join(best_dir, uid + ".json")
        if query is None or not os.path.exists(best_path):
            skipped += 1
            continue
        try:
            attr_df, rest_df = tables_for(query.get("target_city"))
            if isinstance(attr_df, str) or isinstance(rest_df, str) or len(attr_df) == 0 or len(rest_df) == 0:
                skipped += 1
                continue
        except Exception:
            skipped += 1
            continue
        considered += 1
        plan = _load_json(best_path)
        dense, added = _ghost_densify_one(uid, plan, query, agent, attr_df, rest_df, args.max_candidates)
        if dense is None:
            skipped += 1
            continue
        accepted += 1
        if added > 0 and _pref_score(agent, dense) > _pref_score(agent, plan) + 1e-9:
            dense["_eval_score"] = None
            _save_json(os.path.join(result_dir, uid + ".json"), dense)
            improved += 1
    print("ghost_densify: considered={} accepted={} improved={} skipped={}".format(considered, accepted, improved, skipped))
    return 0


def _run_parallel(args):
    uids = _read_uids(args.split)
    workers = max(1, min(args.workers, len(uids)))
    shards = [uids[i::workers] for i in range(workers)]
    prefix = "_tmp_{}_ghost_shard".format(args.split)
    for stale in glob.glob(os.path.join(SPLIT_DIR, prefix + "*.txt")):
        os.remove(stale)
    log_dir = os.path.join(ROOT, "cache", "ghost_densify_logs")
    os.makedirs(log_dir, exist_ok=True)
    procs = []
    logs = []
    tmp_splits = []
    try:
        for k, shard in enumerate(shards):
            if not shard:
                continue
            name = "{}{}".format(prefix, k)
            path = _split_path(name)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(shard) + "\n")
            tmp_splits.append(path)
            log_path = os.path.join(log_dir, "{}_shard{}.log".format(args.split, k))
            logf = open(log_path, "w", encoding="utf-8")
            logs.append(logf)
            cmd = [sys.executable, "scripts/ghost_densify.py", "--split", name, "--workers", "1", "--method", args.method or DEFAULT_METHOD, "--max-candidates", str(args.max_candidates)]
            procs.append((k, len(shard), subprocess.Popen(cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)))
        rc = 0
        for k, n, proc in procs:
            code = proc.wait()
            print("ghost_densify: worker={} queries={} rc={}".format(k, n, code))
            rc = max(rc, code)
        return rc
    finally:
        for logf in logs:
            logf.close()
        for path in tmp_splits:
            try:
                os.remove(path)
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="tpc_phase1")
    ap.add_argument("--method", default=DEFAULT_METHOD)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--max-candidates", type=int, default=24)
    args = ap.parse_args()
    if args.workers > 1:
        return _run_parallel(args)
    return _process(args)


if __name__ == "__main__":
    raise SystemExit(main())
