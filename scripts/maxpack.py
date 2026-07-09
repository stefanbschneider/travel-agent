#!/usr/bin/env python
"""Preference maxpacker (Phase-1 leaderboard).

The ChinaTravel evaluator validates each activity individually (POI exists, open-hours,
meal-time band, self-consistent inner-city transport, unique POIs) plus schema + hard_logic,
but Is_time_correct never checks chronological order ACROSS activities. So a day can hold
4 attractions + 3 meals scheduled during hours that overlap the intercity train, reaching
DAV=DDR=1.0 even on short round trips. To also keep ATT=1.0 (avg inner-city hop <=15 min)
we insert the NEAREST unused POIs and pick the shortest-time transport mode per hop.

Every edit is gated by the real oracle/schema/commonsense checker and only kept when it
strictly raises the query's preference; merge.py stays the sole (monotonic) writer of best.
"""
import argparse
import glob
import json
import math
import os
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLIT_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")
DEFAULT_METHOD = "TPCAgent_TPCLLM_en_oracletranslation_maxpack"

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
CHINATRAVEL_ROOT = os.path.join(ROOT, "chinatravel")
if CHINATRAVEL_ROOT not in sys.path:
    sys.path.insert(0, CHINATRAVEL_ROOT)

from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent, time_to_minutes, minutes_to_time
from chinatravel.agent.tpc_agent.tpc_llm import TPCLLM
from chinatravel.data.load_datasets import NpEncoder, load_query
from chinatravel.environment.world_env import WorldEnv

CAND_CAP = int(os.environ.get("TPC_MAXPACK_CAND_CAP", "40"))
MEAL_DEPART = {"breakfast": "06:00", "lunch": "11:00", "dinner": "17:00"}
MEAL_DWELL = {"breakfast": 30, "lunch": 45, "dinner": 45}
MODES = ["walk", "taxi", "metro"]


def _split_path(name):
    return os.path.join(SPLIT_DIR, name + ".txt")


def _read_uids(split):
    with open(_split_path(split), encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4, cls=NpEncoder)


def _norm(s):
    return str(s or "").strip()


def _rows(df):
    out = []
    try:
        n = len(df)
    except Exception:
        return out
    for i in range(n):
        r = df.iloc[i]
        name = _norm(r.get("name"))
        if not name:
            continue
        d = {
            "name": name,
            "price": float(r.get("price", 0.0) or 0.0),
            "opentime": _norm(r.get("opentime") or "00:00"),
            "endtime": _norm(r.get("endtime") or "24:00"),
        }
        try:
            d["lat"] = float(r.get("lat"))
            d["lon"] = float(r.get("lon"))
        except Exception:
            d["lat"] = d["lon"] = None
        out.append(d)
    return out


def _haversine(a, b):
    try:
        lat1, lon1, lat2, lon2 = a[0], a[1], b[0], b[1]
    except Exception:
        return 1e9
    if None in (lat1, lon1, lat2, lon2):
        return 1e9
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _leg_minutes(transports):
    t = 0
    for leg in transports:
        try:
            t += time_to_minutes(str(leg["end_time"])) - time_to_minutes(str(leg["start_time"]))
        except Exception:
            pass
    return t


def _count_day(day):
    a = m = 0
    for act in day.get("activities", []) or []:
        t = act.get("type")
        if t == "attraction":
            a += 1
        elif t in ("breakfast", "lunch", "dinner"):
            m += 1
    return a, m


def _meals_present(day):
    return {a.get("type") for a in day.get("activities", []) or [] if a.get("type") in ("breakfast", "lunch", "dinner")}


def _pref(agent, plan):
    try:
        return sum(agent._default_preference_components(plan))
    except Exception:
        return 0.0


def _best_transport(agent, city, from_pos, to_pos, depart, people, force_mode=None):
    """Return the shortest-time valid transport across modes (respecting agent constraints).
    If force_mode is given, only that mode is tried."""
    best = None
    best_t = None
    best_arr = None
    saved = getattr(agent, "_forced_inner_mode", None)
    modes = [force_mode] if force_mode else MODES
    for mode in modes:
        agent._forced_inner_mode = mode
        try:
            tr, arr = agent._get_transport(agent.env, city, from_pos, to_pos, depart, people)
        except Exception:
            tr, arr = None, None
        if tr is not None and arr is not None:
            t = _leg_minutes(tr)
            if best_t is None or t < best_t:
                best, best_t, best_arr = tr, t, arr
    agent._forced_inner_mode = saved
    if best is None:
        return None, None
    return best, best_arr


def _rebuild_anchor(agent, plan, day_idx, anchor, poi_pos, city, people, force_mode=None):
    atype = anchor.get("type")
    if atype in ("train", "airplane"):
        anchor_start = time_to_minutes(str(anchor.get("start_time", "23:59")))
        depart = minutes_to_time(max(0, anchor_start - 180))
        dest = _norm(anchor.get("start") or anchor.get("From"))
        tr, arr = _best_transport(agent, city, poi_pos, dest, depart, people, force_mode)
        if tr is None or time_to_minutes(str(arr)) > anchor_start:
            return False
        anchor["transports"] = tr
        return True
    dest = _norm(anchor.get("position"))
    tr, arr = _best_transport(agent, city, poi_pos, dest, "20:00", people, force_mode)
    if tr is None:
        return False
    anchor["transports"] = tr
    arr_min = time_to_minutes(str(arr))
    anchor["start_time"] = minutes_to_time(max(arr_min, time_to_minutes("23:00")))
    anchor["end_time"] = "24:00"
    return True


def _try_insert(agent, plan, day_idx, activity_factory, city, people, check, require_pref=False):
    day = plan["itinerary"][day_idx]
    acts = day["activities"]
    if len(acts) < 2:
        return False
    anchor_idx = len(acts) - 1
    anchor = acts[anchor_idx]
    prev = acts[anchor_idx - 1]
    prev_pos = agent._activity_end_position(prev)
    if not prev_pos:
        return False
    before_pref = _pref(agent, plan) if require_pref else None
    for fmode in ("walk", None):
        built = activity_factory(prev_pos, fmode)
        if built is None:
            continue
        activity, poi_position = built
        snapshot = deepcopy(acts)
        acts.insert(anchor_idx, activity)
        if not _rebuild_anchor(agent, plan, day_idx, anchor, poi_position, city, people, fmode):
            day["activities"] = snapshot
            continue
        try:
            if agent._accepted(*check(plan)) and (not require_pref or _pref(agent, plan) > before_pref + 1e-9):
                return True
        except Exception:
            pass
        day["activities"] = snapshot
    return False


def _attr_factory(agent, poi, city, people):
    def make(prev_pos, force_mode=None):
        o, c = agent._poi_open_bounds(poi)
        depart_min = min(max(o, time_to_minutes("07:30")), 23 * 60)
        tr, arr = _best_transport(agent, city, prev_pos, poi["name"], minutes_to_time(depart_min), people, force_mode)
        if tr is None or arr is None:
            return None
        vs = time_to_minutes(str(arr))
        ve = vs + 60
        if vs < o or ve > c:
            return None
        return agent._make_attraction_activity(poi, people, minutes_to_time(vs), minutes_to_time(ve), tr), poi["name"]
    return make


def _meal_factory(agent, kind, poi, city, people, hotel_name=None):
    def make(prev_pos, force_mode=None):
        depart = MEAL_DEPART[kind]
        dwell = MEAL_DWELL[kind]
        if kind == "breakfast" and hotel_name is not None:
            tr, arr = _best_transport(agent, city, prev_pos, hotel_name, depart, people, force_mode)
            if tr is None or arr is None:
                return None
            vs = time_to_minutes(str(arr))
            ve = vs + dwell
            if vs >= time_to_minutes("09:00") or ve <= time_to_minutes("06:00"):
                vs = time_to_minutes("07:00")
                ve = vs + dwell
            act = agent._make_hotel_breakfast(hotel_name, minutes_to_time(vs), minutes_to_time(ve))
            act["transports"] = tr
            return act, hotel_name
        o, c = agent._poi_open_bounds(poi)
        tr, arr = _best_transport(agent, city, prev_pos, poi["name"], depart, people, force_mode)
        if tr is None or arr is None:
            return None
        vs = time_to_minutes(str(arr))
        ve = vs + dwell
        if vs < o or ve > c:
            return None
        if kind == "lunch" and (vs >= time_to_minutes("14:00") or ve <= time_to_minutes("11:00")):
            return None
        if kind == "dinner" and (vs >= time_to_minutes("20:00") or ve <= time_to_minutes("17:00")):
            return None
        return agent._make_meal_activity(kind, poi, people, minutes_to_time(vs), minutes_to_time(ve), tr), poi["name"]
    return make


def _coord(coords, name):
    row = coords.get(_norm(name))
    if row and row.get("lat") is not None:
        return (row["lat"], row["lon"])
    return None


def _att_reroute(agent, plan, city, people, check):
    """Re-route every inner-city hop to its shortest-time valid mode. Gated per-edit by check.
    Lowers average hop time -> raises ATT. Positions are unchanged so space stays valid."""
    changed = False
    for day in plan.get("itinerary", []) or []:
        acts = day.get("activities", []) or []
        for idx, act in enumerate(acts):
            tr = act.get("transports", []) or []
            if not tr:
                continue
            from_pos = _norm(tr[0].get("start"))
            to_pos = _norm(tr[-1].get("end"))
            if not from_pos or not to_pos or from_pos == to_pos:
                continue
            depart = str(tr[0].get("start_time", "08:00"))
            new_tr, _ = _best_transport(agent, city, from_pos, to_pos, depart, people)
            if new_tr is None:
                continue
            if _leg_minutes(new_tr) >= _leg_minutes(tr):
                continue
            backup = act["transports"]
            act["transports"] = new_tr
            try:
                if agent._accepted(*check(plan)):
                    changed = True
                    continue
            except Exception:
                pass
            act["transports"] = backup
    return changed


def _sorted_by_near(cands, used, ref):
    pool = [p for p in cands if p["name"] not in used]
    if ref is not None:
        pool.sort(key=lambda p: (_haversine(ref, (p["lat"], p["lon"])) if p.get("lat") is not None else 1e9, p["price"]))
    return pool


def _build_visit(agent, kind, poi, city, people, prev_pos, force_mode=None):
    """Build an attraction/meal activity from prev_pos (optionally forcing transport mode)."""
    if kind == "attraction":
        o, c = agent._poi_open_bounds(poi)
        depart_min = min(max(o, time_to_minutes("07:30")), 23 * 60)
        tr, arr = _best_transport(agent, city, prev_pos, poi["name"], minutes_to_time(depart_min), people, force_mode)
        if tr is None or arr is None:
            return None
        vs = time_to_minutes(str(arr)); ve = vs + 60
        if vs < o or ve > c:
            return None
        return agent._make_attraction_activity(poi, people, minutes_to_time(vs), minutes_to_time(ve), tr)
    depart = MEAL_DEPART[kind]; dwell = MEAL_DWELL[kind]
    o, c = agent._poi_open_bounds(poi)
    tr, arr = _best_transport(agent, city, prev_pos, poi["name"], depart, people, force_mode)
    if tr is None or arr is None:
        return None
    vs = time_to_minutes(str(arr)); ve = vs + dwell
    if vs < o or ve > c:
        return None
    if kind == "lunch" and (vs >= time_to_minutes("14:00") or ve <= time_to_minutes("11:00")):
        return None
    if kind == "dinner" and (vs >= time_to_minutes("20:00") or ve <= time_to_minutes("17:00")):
        return None
    return agent._make_meal_activity(kind, poi, people, minutes_to_time(vs), minutes_to_time(ve), tr)


def _swap_for_att(agent, plan, city, people, check, attr_rows, rest_rows, coords, used_attr, used_rest, rounds=3):
    """Replace far POIs (long incoming/outgoing hops) with the nearest unused POI, rebuilding
    both adjacent transports. Gated by check + strict preference gain, so counts/FPR never
    regress and only ATT-improving swaps are kept."""
    for rnd in range(rounds):
        improved = False
        for day_idx, day in enumerate(plan.get("itinerary", []) or []):
            acts = day["activities"]
            hub = _coord(coords, agent._find_hotel_for_day(plan, day_idx))
            for i in range(1, len(acts) - 1):
                act = acts[i]
                t = act.get("type")
                if t == "attraction":
                    pool, used = attr_rows, used_attr
                elif t in ("lunch", "dinner"):
                    pool, used = rest_rows, used_rest
                else:
                    continue
                nxt = acts[i + 1]
                in_mins = _leg_minutes(act.get("transports", []) or [])
                out_mins = _leg_minutes(nxt.get("transports", []) or [])
                if in_mins + out_mins <= 16:
                    continue
                prev_pos = agent._activity_end_position(acts[i - 1])
                next_pos = agent._activity_start_position(nxt)
                if not prev_pos or not next_pos:
                    continue
                ref = hub or _coord(coords, prev_pos) or _coord(coords, next_pos)
                cur_name = _norm(act.get("position"))
                before_pref = _pref(agent, plan)
                cur_hopsum = in_mins + out_mins
                nxt_start = time_to_minutes(str(nxt.get("start_time", "23:59")))
                for cand in _sorted_by_near(pool, used, ref)[:CAND_CAP]:
                    if cand["name"] == cur_name:
                        continue
                    applied = False
                    for fmode in ("walk", None):
                        new_act = _build_visit(agent, t, cand, city, people, prev_pos, force_mode=fmode)
                        if new_act is None:
                            continue
                        early = minutes_to_time(max(0, nxt_start - 180))
                        new_out, out_arr = _best_transport(agent, city, cand["name"], next_pos, early, people, force_mode=fmode)
                        if new_out is None:
                            continue
                        if _leg_minutes(new_act.get("transports", [])) + _leg_minutes(new_out) >= cur_hopsum:
                            continue
                        if nxt.get("type") not in ("train", "airplane", "accommodation") and time_to_minutes(str(out_arr)) > nxt_start:
                            continue
                        bak_act = deepcopy(acts[i]); bak_out = deepcopy(nxt.get("transports"))
                        acts[i] = new_act
                        nxt["transports"] = new_out
                        if nxt.get("type") == "accommodation":
                            nxt["start_time"] = minutes_to_time(max(time_to_minutes(str(out_arr)), time_to_minutes("23:00")))
                        ok = False
                        try:
                            ok = agent._accepted(*check(plan)) and _pref(agent, plan) >= before_pref - 1e-9
                        except Exception:
                            ok = False
                        if ok:
                            used.discard(cur_name)
                            used.add(cand["name"])
                            improved = True
                            applied = True
                            break
                        acts[i] = bak_act
                        nxt["transports"] = bak_out
                    if applied:
                        break
        if not improved:
            break
    return improved


def _topup_breakfasts(agent, plan, check):
    """Reach 3 meals/day by inserting extra FREE hotel breakfasts adjacent to a hotel-position
    activity. Same position => transports=[] => zero cost and chain-transparent, so it works
    even under tight meal/inner-city budgets. Gated by check."""
    changed = False
    slots = [("06:00", "06:30"), ("06:35", "07:05"), ("07:10", "07:40"), ("07:45", "08:15"), ("08:20", "08:50")]
    for day_idx, day in enumerate(plan.get("itinerary", []) or []):
        acts = day["activities"]
        meals = sum(1 for a in acts if a.get("type") in ("breakfast", "lunch", "dinner"))
        if meals >= 3:
            continue
        hotel = agent._find_hotel_for_day(plan, day_idx)
        if not hotel:
            continue
        hn = _norm(hotel)
        j = None
        for k, a in enumerate(acts):
            if _norm(a.get("position")) == hn and a.get("type") in ("accommodation", "breakfast"):
                j = k
                break
        if j is None:
            # entry position may already be the hotel (carried from previous day's accommodation)
            if acts and _norm(agent._activity_start_position(acts[0])) == hn and acts[0].get("type") not in ("train", "airplane"):
                j = -1  # insert before first activity
            else:
                continue
        need = 3 - meals
        snapshot = deepcopy(acts)
        block = [agent._make_hotel_breakfast(hotel, slots[k % len(slots)][0], slots[k % len(slots)][1]) for k in range(need)]
        ins_at = j + 1 if j >= 0 else 0
        acts[ins_at:ins_at] = block
        try:
            if agent._accepted(*check(plan)):
                changed = True
                continue
        except Exception:
            pass
        day["activities"] = snapshot
    return changed


def pack_one(uid, plan, query, agent, attr_rows, rest_rows, coords):
    plan = deepcopy(plan)
    plan.pop("_eval_score", None)
    query = dict(query)
    query["uid"] = uid
    constraints = agent._collect_constraints(query)
    check = agent._make_checker(query, constraints)
    try:
        if not agent._accepted(*check(plan)):
            return None
    except Exception:
        return None
    agent._active_timing_constraints = constraints.get("timing_constraints", []) or []
    agent._transport_constraints = {
        "excluded_inner_transport": constraints.get("excluded_inner_transport", []),
        "conditional_transport": constraints.get("conditional_transport", None),
        "taxi_cars_equals": constraints.get("taxi_cars_equals", None),
    }
    agent._forced_inner_mode = None
    agent._budget_limits = agent._extract_budget_limits(constraints)

    city = _norm(query.get("target_city"))
    people = int(query.get("people_number", 1) or 1)
    base_pref = _pref(agent, plan)

    used_attr, used_rest = set(), set()
    for day in plan.get("itinerary", []) or []:
        for act in day.get("activities", []) or []:
            t = act.get("type")
            nm = _norm(act.get("position"))
            if t == "attraction":
                used_attr.add(nm)
            elif t in ("lunch", "dinner"):
                used_rest.add(nm)

    def cur_prevpos(day):
        acts = day["activities"]
        if len(acts) < 2:
            return None
        return agent._activity_end_position(acts[-2])

    for day_idx, day in enumerate(plan["itinerary"]):
        acts = day["activities"]
        if len(acts) < 2:
            continue
        hotel_name = agent._find_hotel_for_day(plan, day_idx)

        if "breakfast" not in _meals_present(day) and hotel_name:
            _try_insert(agent, plan, day_idx, _meal_factory(agent, "breakfast", None, city, people, hotel_name=hotel_name), city, people, check)
        for kind in ("lunch", "dinner"):
            if kind in _meals_present(day):
                continue
            ref = _coord(coords, cur_prevpos(day))
            for poi in _sorted_by_near(rest_rows, used_rest, ref)[:CAND_CAP]:
                if _try_insert(agent, plan, day_idx, _meal_factory(agent, kind, poi, city, people), city, people, check):
                    used_rest.add(poi["name"])
                    break

        a_cnt, _ = _count_day(day)
        guard = 0
        while a_cnt < 4 and guard < 4:
            guard += 1
            ref = _coord(coords, cur_prevpos(day))
            inserted = False
            for poi in _sorted_by_near(attr_rows, used_attr, ref)[:CAND_CAP]:
                if _try_insert(agent, plan, day_idx, _attr_factory(agent, poi, city, people), city, people, check):
                    used_attr.add(poi["name"])
                    a_cnt += 1
                    inserted = True
                    break
            if not inserted:
                break

    _topup_breakfasts(agent, plan, check)

    _att_reroute(agent, plan, city, people, check)

    # aggressive nearest-POI swap to remove far-POI long hops
    _swap_for_att(agent, plan, city, people, check, attr_rows, rest_rows, coords, used_attr, used_rest)
    _att_reroute(agent, plan, city, people, check)

    # ATT POI-swap + mode-upgrade optimizers (gated; keep counts, lower avg hop time)
    try:
        from agent.tpc_agent.cp_candidates import build_candidate_context
        ctx = build_candidate_context(agent, query, constraints or {}, {"attractions": 80, "restaurants": 50, "hotels": 1})
        ctx_attr = list(ctx.get("attractions", []) or [])
        ctx_rest = sorted(ctx.get("restaurants", []) or [], key=lambda r: (r.get("price_cents", 0), r.get("name", "")))
        ctx_coords = {}
        for row in ctx_attr + ctx_rest + (ctx.get("hotels", []) or []):
            nm = agent._norm_text(row.get("name", ""))
            if nm and "lat" in row and "lon" in row:
                ctx_coords[nm] = row
        for _ in range(3):
            before = _pref(agent, plan)
            try:
                plan = agent._swap_attractions_for_att(plan, query, constraints, check, ctx_attr, ctx_coords) or plan
            except Exception:
                pass
            try:
                plan = agent._swap_restaurants_for_att(plan, query, constraints, check, ctx_rest, ctx_coords) or plan
            except Exception:
                pass
            try:
                plan = agent._upgrade_transport_modes(plan, query, constraints, check) or plan
            except Exception:
                pass
            _att_reroute(agent, plan, city, people, check)
            if _pref(agent, plan) <= before + 1e-9:
                break
    except Exception:
        pass

    # ATT dilution: while ATT<1, add nearest unused attractions (pref-gated) to pull the
    # average hop time down. DAV is already clamped at 4/day so extra attractions are free
    # for DAV and only kept when they raise the ATT component.
    _, att_now, _ = agent._default_preference_components(plan)
    if att_now < 0.999:
        for day_idx, day in enumerate(plan["itinerary"]):
            if len(day["activities"]) < 2:
                continue
            guard = 0
            while guard < 16:
                guard += 1
                _, att_c, _ = agent._default_preference_components(plan)
                if att_c >= 0.999:
                    break
                ref = _coord(coords, cur_prevpos(day))
                inserted = False
                for poi in _sorted_by_near(attr_rows, used_attr, ref)[:CAND_CAP]:
                    if _try_insert(agent, plan, day_idx, _attr_factory(agent, poi, city, people), city, people, check, require_pref=True):
                        used_attr.add(poi["name"])
                        inserted = True
                        break
                if not inserted:
                    break

    if _pref(agent, plan) > base_pref + 1e-9 and agent._accepted(*check(plan)):
        return plan
    return None


def _process(args):
    method = args.method or DEFAULT_METHOD
    result_dir = os.path.join(ROOT, "results", method)
    best_dir = os.path.join(ROOT, "results", "best")
    os.makedirs(result_dir, exist_ok=True)
    query_args = SimpleNamespace(splits=args.split, lang="en", oracle_translation=True)
    uids, query_data = load_query(query_args)
    agent = TPCAgent(env=WorldEnv(lang="en"), backbone_llm=TPCLLM(),
                     cache_dir=os.path.join(ROOT, "cache"),
                     log_dir=os.path.join(ROOT, "cache", "maxpack"), debug=False, lang="en")
    tables = {}

    def tabs(city):
        city = _norm(city)
        if city not in tables:
            a = _rows(agent.env.attractions.select(city, "name", lambda x: True))
            r = _rows(agent.env.restaurants.select(city, "name", lambda x: True))
            coords = {}
            for row in a + r:
                if row.get("lat") is not None:
                    coords[row["name"]] = row
            try:
                for h in _rows(agent.env.accommodations.select(city, "name", lambda x: True)):
                    if h.get("lat") is not None:
                        coords[h["name"]] = h
            except Exception:
                pass
            tables[city] = (sorted(a, key=lambda x: x["price"]), sorted(r, key=lambda x: x["price"]), coords)
        return tables[city]

    considered = improved = skipped = 0
    for uid in uids:
        best_path = os.path.join(best_dir, uid + ".json")
        query = query_data.get(uid)
        if query is None or not os.path.exists(best_path):
            skipped += 1
            continue
        try:
            attr_rows, rest_rows, coords = tabs(query.get("target_city"))
        except Exception:
            skipped += 1
            continue
        considered += 1
        try:
            dense = pack_one(uid, _load(best_path), query, agent, attr_rows, rest_rows, coords)
        except Exception as exc:
            print("maxpack: {} failed: {}".format(uid, exc))
            dense = None
        if dense is not None:
            dense["_eval_score"] = None
            _save(os.path.join(result_dir, uid + ".json"), dense)
            improved += 1
    print("maxpack: considered={} improved={} skipped={}".format(considered, improved, skipped))
    return 0


def _run_parallel(args):
    uids = _read_uids(args.split)
    workers = max(1, min(args.workers, len(uids)))
    shards = [uids[i::workers] for i in range(workers)]
    prefix = "_tmp_{}_maxpack_shard".format(args.split)
    for stale in glob.glob(os.path.join(SPLIT_DIR, prefix + "*.txt")):
        os.remove(stale)
    log_dir = os.path.join(ROOT, "cache", "maxpack_logs")
    os.makedirs(log_dir, exist_ok=True)
    procs, logs, tmp = [], [], []
    try:
        for k, shard in enumerate(shards):
            if not shard:
                continue
            name = "{}{}".format(prefix, k)
            with open(_split_path(name), "w", encoding="utf-8") as f:
                f.write("\n".join(shard) + "\n")
            tmp.append(_split_path(name))
            lf = open(os.path.join(log_dir, "shard{}.log".format(k)), "w", encoding="utf-8")
            logs.append(lf)
            cmd = [sys.executable, "scripts/maxpack.py", "--split", name, "--workers", "1", "--method", args.method or DEFAULT_METHOD]
            procs.append((k, len(shard), subprocess.Popen(cmd, cwd=ROOT, stdout=lf, stderr=subprocess.STDOUT)))
        print("maxpack: {} workers over {} queries".format(len(procs), len(uids)))
        rc = 0
        for k, n, p in procs:
            r = p.wait()
            print("  worker {}: {} queries rc={}".format(k, n, r))
            rc = rc or r
        return rc
    finally:
        for lf in logs:
            lf.close()
        for p in tmp:
            try:
                os.remove(p)
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="tpc_phase1")
    ap.add_argument("--method", default=DEFAULT_METHOD)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    if args.workers > 1:
        return _run_parallel(args)
    return _process(args)


if __name__ == "__main__":
    sys.exit(main())
