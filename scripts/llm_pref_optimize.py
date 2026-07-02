#!/usr/bin/env python
"""LLM-assisted selector over checker-gated preference-improving plan candidates."""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Iterable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLIT_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")
DEFAULT_METHOD = "TPCAgent_TPCLLM_en_oracletranslation_llm_pref"
GHOST_ATTR_SLOTS = [(9, 10), (10, 11), (14, 15), (15, 16), (16, 17), (19, 20), (20, 21)]
GHOST_DEFAULT_ATTR_CAP = 4
GHOST_DEFAULT_ATTR_SLOTS = ",".join("{:02d}:00-{:02d}:00".format(start, end) for start, end in GHOST_ATTR_SLOTS)
GHOST_MEAL_DURATION = 60

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
CHINATRAVEL_ROOT = os.path.join(ROOT, "chinatravel")
if CHINATRAVEL_ROOT not in sys.path:
    sys.path.insert(0, CHINATRAVEL_ROOT)

try:
    from chinatravel.agent.load_model import init_llm
except Exception:  # pragma: no cover - runtime dependency may be absent in helper-only tests
    init_llm = None
try:
    from chinatravel.agent.tpc_agent.tpc_llm import TPCLLM
except Exception:  # pragma: no cover
    TPCLLM = None


def time_to_minutes(t):
    h, m = str(t).split(":")[:2]
    return int(h) * 60 + int(m)


def minutes_to_time(total_minutes):
    total_minutes = max(0, min(int(total_minutes), 23 * 60 + 59))
    return "{:02d}:{:02d}".format(total_minutes // 60, total_minutes % 60)


@dataclass
class Candidate:
    id: str
    lever: str
    description: str
    before: tuple[float, float, float]
    after: tuple[float, float, float]
    plan: dict


def _split_path(name):
    return os.path.join(SPLIT_DIR, name + ".txt")


def _read_uids(split):
    with open(_split_path(split), encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    try:
        from chinatravel.data.load_datasets import NpEncoder
    except Exception:
        NpEncoder = None
    with open(path, "w", encoding="utf-8") as f:
        if NpEncoder is None:
            json.dump(data, f, ensure_ascii=False, indent=4)
        else:
            json.dump(data, f, ensure_ascii=False, indent=4, cls=NpEncoder)


def _env_int(name, default):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return int(value)


def _minutes(value):
    return time_to_minutes(str(value))


def _leg_minutes(leg):
    try:
        return _minutes(leg["end_time"]) - _minutes(leg["start_time"])
    except Exception:
        return 0


def _components(agent, plan) -> tuple[float, float, float]:
    return tuple(agent._default_preference_components(plan))


def _component_dict(agent, plan) -> dict:
    dav, att, ddr = _components(agent, plan)
    attrs, meals = agent._activity_counts(plan)
    days = len(plan.get("itinerary", []) or [])
    hops = []
    for day in plan.get("itinerary", []) or []:
        for activity in day.get("activities", []) or []:
            transports = activity.get("transports", []) or []
            if transports:
                hops.append(sum(_leg_minutes(leg) for leg in transports))
    avg_transport = sum(hops) / len(hops) if hops else -1.0
    return {
        "dav": dav * 100.0,
        "att": att * 100.0,
        "ddr": ddr * 100.0,
        "attrs": attrs,
        "meals": meals,
        "days": days,
        "avg_transport_minutes": avg_transport,
    }


def _pref_sum(components) -> float:
    return float(sum(components))


def _candidate_deltas(candidate):
    return tuple(a - b for b, a in zip(candidate.before, candidate.after))


def _candidate_sort_key(candidate):
    dav_delta, att_delta, ddr_delta = _candidate_deltas(candidate)
    total_delta = dav_delta + att_delta + ddr_delta
    return (-total_delta, -att_delta, -ddr_delta, -dav_delta, candidate.id)


def _init_optimizer_llm(name, max_model_len):
    try:
        return init_llm(name, max_model_len=max_model_len)
    except Exception as exc:
        print(
            "llm_pref: llm_init_failed={}: {}; using TPCLLM fallback".format(
                exc.__class__.__name__, exc
            )
        )
        return TPCLLM()


def _parse_llm_choice(raw, valid_ids) -> list[str]:
    valid = set(valid_ids)
    try:
        data = json.loads(str(raw).strip())
    except Exception:
        return []
    if not isinstance(data, dict) or set(data.keys()) != {"candidate_ids"}:
        return []
    ids = data.get("candidate_ids")
    if not isinstance(ids, list):
        return []
    chosen = []
    seen = set()
    for cid in ids:
        if cid in valid and cid not in seen:
            chosen.append(cid)
            seen.add(cid)
    return chosen


def _choose_candidate(llm, uid, query, current_diag, candidates) -> Candidate | None:
    if not candidates:
        return None
    valid_ids = [candidate.id for candidate in candidates]
    candidate_payload = []
    for candidate in candidates:
        dav_delta, att_delta, ddr_delta = _candidate_deltas(candidate)
        candidate_payload.append(
            {
                "id": candidate.id,
                "lever": candidate.lever,
                "description": candidate.description,
                "dav_after": candidate.after[0] * 100.0,
                "att_after": candidate.after[1] * 100.0,
                "ddr_after": candidate.after[2] * 100.0,
                "dav_delta": dav_delta * 100.0,
                "att_delta": att_delta * 100.0,
                "ddr_delta": ddr_delta * 100.0,
            }
        )
    payload = {
        "uid": uid,
        "query": query.get("nature_language", ""),
        "current": {
            "dav": current_diag.get("dav"),
            "att": current_diag.get("att"),
            "ddr": current_diag.get("ddr"),
            "attrs": current_diag.get("attrs"),
            "meals": current_diag.get("meals"),
            "avg_transport_minutes": current_diag.get("avg_transport_minutes"),
        },
        "candidates": candidate_payload,
    }
    messages = [
        {
            "role": "system",
            "content": "You choose from prevalidated travel-plan candidate IDs only. Return JSON only: {\"candidate_ids\": [\"...\"]}. Do not invent IDs and do not rewrite the plan.",
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    try:
        raw = llm(messages, one_line=False, json_mode=True)
    except Exception:
        raw = ""
    choice_ids = _parse_llm_choice(raw, valid_ids)
    if choice_ids:
        by_id = {candidate.id: candidate for candidate in candidates}
        return by_id[choice_ids[0]]
    return sorted(candidates, key=_candidate_sort_key)[0]


def _candidate_if_better(candidates, cid, lever, description, trial, agent, check, before_components):
    if trial is None:
        return
    try:
        if not agent._accepted(*check(trial)):
            return
        after_components = _components(agent, trial)
    except Exception:
        return
    if _pref_sum(after_components) > _pref_sum(before_components) + 1e-9:
        candidates.append(
            Candidate(
                id=cid,
                lever=lever,
                description=description,
                before=tuple(before_components),
                after=tuple(after_components),
                plan=deepcopy(trial),
            )
        )


def _safe_global_candidates(uid, query, plan, agent, constraints, check, candidates):
    before_components = _components(agent, plan)
    try:
        trial = deepcopy(plan)
        upgraded = agent._upgrade_transport_modes(trial, query, constraints, check)
        _candidate_if_better(
            candidates,
            "safe.transport_upgrade",
            "att",
            "Upgrade inner-city transport modes when the checker accepts faster hops.",
            upgraded,
            agent,
            check,
            before_components,
        )
    except Exception:
        pass
    try:
        trial = deepcopy(plan)
        dense = agent._densify_plan(trial, query, constraints, check)
        _candidate_if_better(
            candidates,
            "safe.densify_default",
            "mixed",
            "Run the existing checker-gated densify pass on idle windows.",
            dense,
            agent,
            check,
            before_components,
        )
    except Exception:
        pass


def _used_positions(plan, types):
    used = set()
    for day in plan.get("itinerary", []) or []:
        for activity in day.get("activities", []) or []:
            if activity.get("type") in types and activity.get("position"):
                used.add(str(activity.get("position") or "").strip())
    return used


def _iter_rows(df) -> Iterable[dict]:
    if df is None or isinstance(df, str):
        return []
    if hasattr(df, "iterrows"):
        rows = []
        for _, row in df.iterrows():
            try:
                rows.append(row.to_dict())
            except Exception:
                rows.append(dict(row))
        return rows
    if isinstance(df, list):
        return [dict(row) for row in df if isinstance(row, dict)]
    return []


def _coord_map(*dfs) -> dict[str, object]:
    coords = {}
    for df in dfs:
        for row in _iter_rows(df):
            name = str(row.get("name", "") or "").strip()
            if name and "lat" in row and "lon" in row:
                coords[name.lower()] = row
    return coords


def _safe_distance(agent, a, b):
    try:
        dist = agent._haversine_km(a, b)
        if not math.isfinite(dist):
            return 1_000_000.0
        return dist
    except Exception:
        return 1_000_000.0


def _rank_rows(agent, rows, prev_anchor, next_anchor, limit):
    def key(row):
        distance = 0.0
        if prev_anchor is not None:
            distance += _safe_distance(agent, prev_anchor, row)
        if next_anchor is not None:
            distance += _safe_distance(agent, row, next_anchor)
        try:
            price = float(row.get("price", 0.0) or 0.0)
        except Exception:
            price = 0.0
        return (distance, price, str(row.get("name", "") or ""))

    return sorted(list(rows), key=key)[: max(0, limit)]


def _try_replace_between(plan, query, agent, check, day_idx, act_idx, row, kind) -> dict | None:
    trial = deepcopy(plan)
    itinerary = trial.get("itinerary", []) or []
    if day_idx < 0 or day_idx >= len(itinerary):
        return None
    activities = itinerary[day_idx].get("activities", []) or []
    if not (1 <= act_idx < len(activities) - 1):
        return None
    prev_act = activities[act_idx - 1]
    old_act = activities[act_idx]
    next_act = activities[act_idx + 1]
    city = query.get("target_city", "")
    people = int(query.get("people_number", 1) or 1)
    prev_pos = agent._activity_end_position(prev_act)
    next_pos = agent._activity_start_position(next_act)
    poi_name = str(row.get("name", "") or "").strip()
    if not prev_pos or not next_pos or not poi_name:
        return None
    try:
        old_start_min = _minutes(old_act.get("start_time", ""))
        old_end_min = _minutes(old_act.get("end_time", ""))
        next_start_min = _minutes(next_act.get("start_time", ""))
        dwell = old_end_min - old_start_min
        if dwell <= 0:
            raise ValueError("nonpositive dwell")
    except Exception:
        try:
            dwell = int(agent._densify_dwell_minutes(row, kind))
            old_start_min = _minutes(old_act.get("start_time", prev_act.get("end_time", "")))
            next_start_min = _minutes(next_act.get("start_time", ""))
        except Exception:
            return None
    try:
        transports_in, arrival = agent._get_transport(
            agent.env, city, prev_pos, poi_name, str(prev_act.get("end_time", "")), people
        )
    except Exception:
        return None
    if transports_in is None or arrival is None:
        return None
    try:
        arrival_min = _minutes(arrival)
        open_min, close_min = agent._poi_open_bounds(row)
    except Exception:
        return None
    replacement_start_min = max(arrival_min, old_start_min, open_min)
    replacement_end_min = replacement_start_min + dwell
    if replacement_end_min > close_min or replacement_end_min > next_start_min:
        return None
    replacement_start_time = minutes_to_time(replacement_start_min)
    replacement_end_time = minutes_to_time(replacement_end_min)
    try:
        transports_out, next_arrival = agent._get_transport(
            agent.env, city, poi_name, next_pos, replacement_end_time, people
        )
    except Exception:
        return None
    if transports_out is None or next_arrival is None:
        return None
    try:
        if _minutes(next_arrival) > next_start_min:
            return None
    except Exception:
        return None
    if kind == "attraction":
        replacement = agent._make_attraction_activity(row, people, replacement_start_time, replacement_end_time, transports_in)
    else:
        replacement = agent._make_meal_activity(kind, row, people, replacement_start_time, replacement_end_time, transports_in)
    activities[act_idx] = replacement
    next_act["transports"] = transports_out
    try:
        if agent._accepted(*check(trial)):
            return trial
    except Exception:
        return None
    return None


def _slug(value):
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
    slug = "_".join(part for part in slug.split("_") if part)
    return (slug or "unknown")[:48]


def _safe_replacement_candidates(uid, query, plan, agent, check, attr_df, rest_df, replace_limit, candidates):
    before_components = _components(agent, plan)
    coord_by_name = _coord_map(attr_df, rest_df)
    used_attrs = _used_positions(plan, {"attraction"})
    used_restaurants = _used_positions(plan, {"breakfast", "lunch", "dinner"})
    attr_rows = [row for row in _iter_rows(attr_df) if str(row.get("name", "") or "").strip() not in used_attrs]
    rest_rows = [row for row in _iter_rows(rest_df) if str(row.get("name", "") or "").strip() not in used_restaurants]
    for day_idx, day in enumerate(plan.get("itinerary", []) or []):
        activities = day.get("activities", []) or []
        for act_idx in range(1, max(1, len(activities) - 1)):
            activity = activities[act_idx]
            kind = activity.get("type")
            if kind == "attraction":
                rows = attr_rows
            elif kind in ("breakfast", "lunch", "dinner"):
                rows = rest_rows
            else:
                continue
            prev_act = activities[act_idx - 1]
            next_act = activities[act_idx + 1]
            prev_anchor = coord_by_name.get(agent._norm_text(agent._activity_end_position(prev_act)))
            next_anchor = coord_by_name.get(agent._norm_text(agent._activity_start_position(next_act)))
            for row in _rank_rows(agent, rows, prev_anchor, next_anchor, replace_limit):
                trial = _try_replace_between(plan, query, agent, check, day_idx, act_idx, row, kind)
                cid = "safe.replace.d{}.a{}.{}".format(day_idx, act_idx, _slug(row.get("name", "")))
                _candidate_if_better(
                    candidates,
                    cid,
                    "att",
                    "Replace one {} with a nearby same-kind POI and rebuild adjacent transport.".format(kind),
                    trial,
                    agent,
                    check,
                    before_components,
                )


def _ghost_candidate(uid, query, plan, agent, check, attr_df, rest_df, args, candidates):
    try:
        import scripts.ghost_densify as ghost

        before_components = _components(agent, plan)
        ghost_plan, _added = ghost._ghost_densify_one(
            uid,
            plan,
            query,
            agent,
            attr_df,
            rest_df,
            args.max_candidates,
            ghost._parse_attr_slots(args.ghost_attr_slots),
            args.ghost_attr_cap,
            flex_meals=True,
            upgrade_transport=args.ghost_upgrade_transport,
            meal_duration=args.ghost_meal_duration,
            force_meals=args.ghost_force_meals,
            attr_window_open=args.ghost_attr_window_open,
            attr_window_close=args.ghost_attr_window_close,
        )
        _candidate_if_better(
            candidates,
            "ghost.densify_default",
            "mixed",
            "Run the existing ghost-densify detour candidate builder.",
            ghost_plan,
            agent,
            check,
            before_components,
        )
    except Exception:
        pass


def _prepare_agent_context(agent, constraints):
    constraints = constraints or {}
    agent._active_timing_constraints = constraints.get("timing_constraints", []) or []
    agent._transport_constraints = {
        "excluded_inner_transport": constraints.get("excluded_inner_transport", []),
        "conditional_transport": constraints.get("conditional_transport", None),
        "taxi_cars_equals": constraints.get("taxi_cars_equals", None),
    }
    agent._forced_inner_mode = None
    agent._budget_limits = agent._extract_budget_limits(constraints)


def _build_candidates(uid, query, plan, agent, constraints, check, attr_df, rest_df, args) -> list[Candidate]:
    _prepare_agent_context(agent, constraints)
    candidates = []
    if args.candidate_mode in {"safe", "both"}:
        _safe_global_candidates(uid, query, plan, agent, constraints, check, candidates)
        _safe_replacement_candidates(uid, query, plan, agent, check, attr_df, rest_df, args.replace_candidates, candidates)
    if args.candidate_mode in {"ghost", "both"}:
        _ghost_candidate(uid, query, plan, agent, check, attr_df, rest_df, args, candidates)
    by_id = {}
    for candidate in candidates:
        old = by_id.get(candidate.id)
        if old is None:
            by_id[candidate.id] = candidate
            continue
        if _pref_sum(_candidate_deltas(candidate)) > _pref_sum(_candidate_deltas(old)):
            by_id[candidate.id] = candidate
    return sorted(by_id.values(), key=_candidate_sort_key)


def _process(args):
    if args.no_oracle:
        os.environ["TPC_USE_ORACLE"] = "0"
    oracle = not args.no_oracle
    method = args.method or DEFAULT_METHOD
    best_dir = os.path.join(ROOT, "results", "best")
    result_dir = os.path.join(ROOT, "results", method)

    from chinatravel.agent.tpc_agent.tpc_agent import TPCAgent
    from chinatravel.data.load_datasets import load_query
    from chinatravel.environment.world_env import WorldEnv

    query_args = SimpleNamespace(splits=args.split, lang="en", oracle_translation=oracle)
    uids, query_data = load_query(query_args)
    if args.max_uids > 0:
        uids = uids[: args.max_uids]
    agent = TPCAgent(
        env=WorldEnv(lang="en"),
        backbone_llm=TPCLLM(),
        cache_dir=os.path.join(ROOT, "cache"),
        log_dir=os.path.join(ROOT, "cache", "llm_pref_optimize"),
        debug=True,
        lang="en",
    )
    llm = _init_optimizer_llm(args.llm, args.max_model_len)
    city_tables = {}

    def tables_for(city):
        city = str(city or "").strip()
        if city not in city_tables:
            try:
                city_tables[city] = (
                    agent.env.attractions.select(city, "name", lambda x: True),
                    agent.env.restaurants.select(city, "name", lambda x: True),
                )
            except Exception:
                city_tables[city] = ([], [])
        return city_tables[city]

    considered = accepted = candidate_sets = chosen = improved = written = skipped = 0
    for uid in uids:
        best_path = os.path.join(best_dir, uid + ".json")
        if not os.path.exists(best_path):
            skipped += 1
            continue
        query = query_data.get(uid)
        if query is None:
            skipped += 1
            continue
        try:
            plan = _load_json(best_path)
            plan.pop("_eval_score", None)
            considered += 1
            constraints = agent._collect_constraints(query)
            check = agent._make_checker(query, constraints)
            _prepare_agent_context(agent, constraints)
            if not agent._accepted(*check(plan)):
                skipped += 1
                continue
            accepted += 1
            original_components = _components(agent, plan)
            current_plan = deepcopy(plan)
            attr_df, rest_df = tables_for(query.get("target_city"))
            for _pass_idx in range(max(0, args.passes)):
                current_components = _components(agent, current_plan)
                candidates = _build_candidates(
                    uid, query, current_plan, agent, constraints, check, attr_df, rest_df, args
                )
                if not candidates:
                    break
                candidate_sets += 1
                selected = _choose_candidate(llm, uid, query, _component_dict(agent, current_plan), candidates)
                if selected is None:
                    break
                try:
                    selected_components = _components(agent, selected.plan)
                    if _pref_sum(selected_components) <= _pref_sum(current_components) + 1e-9:
                        break
                    if not agent._accepted(*check(selected.plan)):
                        break
                except Exception:
                    break
                current_plan = deepcopy(selected.plan)
                chosen += 1
            final_components = _components(agent, current_plan)
            if _pref_sum(final_components) > _pref_sum(original_components) + 1e-9:
                current_plan.pop("_eval_score", None)
                improved += 1
                if not args.dry_run:
                    os.makedirs(result_dir, exist_ok=True)
                    _save_json(os.path.join(result_dir, uid + ".json"), current_plan)
                    written += 1
        except Exception as exc:
            print("llm_pref: {} failed: {}".format(uid, exc))
            skipped += 1
    print(
        "llm_pref: considered={} accepted={} candidate_sets={} chosen={} improved={} written={} skipped={} dry_run={} method={}".format(
            considered,
            accepted,
            candidate_sets,
            chosen,
            improved,
            written,
            skipped,
            1 if args.dry_run else 0,
            method,
        )
    )
    return 0


def _run_parallel(args):
    uids = _read_uids(args.split)
    if args.max_uids > 0:
        uids = uids[: args.max_uids]
    workers = max(1, min(args.workers, len(uids)))
    shards = [uids[i::workers] for i in range(workers)]
    prefix = "_tmp_{}_llm_pref_shard".format(os.getpid())
    for stale in glob.glob(os.path.join(SPLIT_DIR, prefix + "*.txt")):
        os.remove(stale)

    log_dir = os.path.join(ROOT, "cache", "llm_pref_logs")
    os.makedirs(log_dir, exist_ok=True)
    tmp_splits = []
    procs = []
    logs = []
    try:
        for k, shard in enumerate(shards):
            if not shard:
                continue
            name = "{}{}".format(prefix, k)
            path = _split_path(name)
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(shard) + "\n")
            tmp_splits.append(path)
            log_path = os.path.join(log_dir, "{}_shard{}.log".format(os.getpid(), k))
            logf = open(log_path, "w", encoding="utf-8")
            logs.append(logf)
            cmd = [
                sys.executable,
                "scripts/llm_pref_optimize.py",
                "--split",
                name,
                "--workers",
                "1",
                "--method",
                args.method or DEFAULT_METHOD,
                "--llm",
                args.llm,
                "--candidate-mode",
                args.candidate_mode,
                "--passes",
                str(args.passes),
                "--max-candidates",
                str(args.max_candidates),
                "--replace-candidates",
                str(args.replace_candidates),
                "--max-uids",
                str(args.max_uids),
                "--ghost-attr-cap",
                str(args.ghost_attr_cap),
                "--ghost-attr-slots",
                args.ghost_attr_slots,
                "--ghost-meal-duration",
                str(args.ghost_meal_duration),
                "--ghost-attr-window-open",
                args.ghost_attr_window_open,
                "--ghost-attr-window-close",
                args.ghost_attr_window_close,
            ]
            if args.max_model_len is not None:
                cmd.extend(["--max-model-len", str(args.max_model_len)])
            if args.no_oracle:
                cmd.append("--no-oracle")
            if args.dry_run:
                cmd.append("--dry-run")
            if args.ghost_force_meals:
                cmd.append("--ghost-force-meals")
            if args.ghost_upgrade_transport:
                cmd.append("--ghost-upgrade-transport")
            procs.append((k, len(shard), subprocess.Popen(cmd, cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT)))
        print("llm_pref: {} workers over {} queries (logs in {})".format(len(procs), len(uids), log_dir))
        rc = 0
        try:
            for k, n, proc in procs:
                code = proc.wait()
                print("  worker {}: {} queries rc={}".format(k, n, code))
                rc = rc or code
        except KeyboardInterrupt:
            for _, _, proc in procs:
                proc.terminate()
            raise
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
    ap.add_argument("--no-oracle", dest="no_oracle", action="store_true")
    ap.add_argument("--llm", default=os.environ.get("TPC_LLM_PREF_LLM", "gpt-4o"))
    ap.add_argument("--max-model-len", type=int, default=_env_int("TPC_LLM_PREF_MAX_MODEL_LEN", None))
    ap.add_argument(
        "--candidate-mode",
        choices=["safe", "ghost", "both"],
        default=os.environ.get("TPC_LLM_PREF_CANDIDATE_MODE", "safe"),
    )
    ap.add_argument("--passes", type=int, default=int(os.environ.get("TPC_LLM_PREF_PASSES", "2")))
    ap.add_argument("--max-candidates", type=int, default=int(os.environ.get("TPC_LLM_PREF_MAX_CANDIDATES", "24")))
    ap.add_argument("--replace-candidates", type=int, default=int(os.environ.get("TPC_LLM_PREF_REPLACE_CANDIDATES", "12")))
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--max-uids", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ghost-attr-cap", type=int, default=int(os.environ.get("TPC_GHOST_ATTR_CAP", GHOST_DEFAULT_ATTR_CAP)))
    ap.add_argument(
        "--ghost-attr-slots",
        default=os.environ.get("TPC_GHOST_ATTR_SLOTS", GHOST_DEFAULT_ATTR_SLOTS),
        help="comma-separated HH:MM-HH:MM attraction slots for ghost candidates",
    )
    ap.add_argument("--ghost-force-meals", action="store_true", default=bool(int(os.environ.get("TPC_GHOST_FORCE_MEALS", "0"))))
    ap.add_argument("--ghost-upgrade-transport", action="store_true", default=False)
    ap.add_argument("--ghost-meal-duration", type=int, default=int(os.environ.get("TPC_GHOST_MEAL_DURATION", GHOST_MEAL_DURATION)))
    ap.add_argument("--ghost-attr-window-open", default=os.environ.get("TPC_GHOST_ATTR_WINDOW_OPEN", "09:00"))
    ap.add_argument("--ghost-attr-window-close", default=os.environ.get("TPC_GHOST_ATTR_WINDOW_CLOSE", "21:00"))
    args = ap.parse_args()
    if args.workers > 1:
        return _run_parallel(args)
    return _process(args)


if __name__ == "__main__":
    raise SystemExit(main())
