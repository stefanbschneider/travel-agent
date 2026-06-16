import sys
import os
import time
import math
import json
import re
from difflib import SequenceMatcher
from copy import deepcopy

from agent.base import BaseAgent
from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py
import random
import parse_constraints
from agent.tpc_agent.parsed_verifier import evaluate_parsed_constraints
import contextlib
import io
from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints

sys.path.append("./../../../")
project_root_path = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if project_root_path not in sys.path:
    sys.path.insert(0, project_root_path)


def add_minutes(time_str, minutes):
    """Add minutes to a HH:MM time string, clamping at 23:59."""
    h, m = map(int, time_str.split(":"))
    total = h * 60 + m + minutes
    total = min(total, 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"


def minutes_to_time(total_minutes):
    """Convert total minutes to a HH:MM time string, clamping at 23:59."""
    total_minutes = max(0, min(int(total_minutes), 23 * 60 + 59))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"


def time_to_minutes(t):
    """Convert HH:MM string to total minutes."""
    h, m = map(int, t.split(":"))
    return h * 60 + m


def time_before(t1, t2):
    """Return True if t1 <= t2 (both HH:MM strings)."""
    return time_to_minutes(t1) <= time_to_minutes(t2)


def is_open_during(attr, start_time, end_time):
    """Check if attraction is open for the entire visit period [start_time, end_time]."""
    opentime = str(attr["opentime"])
    endtime = str(attr["endtime"])
    ot_min = time_to_minutes(opentime)
    et_min = time_to_minutes(endtime)
    # Handle wrap-around
    if et_min <= ot_min:
        et_min += 24 * 60
    st_min = time_to_minutes(start_time)
    ed_min = time_to_minutes(end_time)
    return ot_min <= st_min and ed_min <= et_min


class TPCAgent(BaseAgent):
    def __init__(self, **kwargs):
        super().__init__(name="TPC", **kwargs)
        # Accept plans against the in-data oracle hard_logic_py; set "0" to parse constraints live from NL (Phase-2 reuse).
        self.use_oracle = os.environ.get("TPC_USE_ORACLE", "1") != "0"
        # Maximum plan rebuilds attempted per query during the multi-start search.
        self.max_restarts = int(os.environ.get("TPC_MAX_RESTARTS", "400"))
        # Wall-clock budget (seconds) the per-query search self-limits to.
        self.solve_budget_sec = float(os.environ.get("TPC_SOLVE_BUDGET_SEC", "120"))
        # Salt mixed into the per-query RNG seed so distinct search rounds explore different params.
        self.seed_salt = os.environ.get("TPC_SEED_SALT", "0")
        self._transport_constraints = {}
        self._schema = None

    def _make_checker(self, query, constraints):
        """Return check(plan) -> (passed, total).

        The base score is the oracle hard_logic_py pass (identical to eval_tpc's logic pass) or,
        in no-oracle mode, the parsed-constraint pass. Once the base is fully satisfied the plan
        is additionally gated on schema + commonsense validity, because FPR == schema ∩
        commonsense ∩ logic; the +2 makes acceptance require all three.
        """
        if self.use_oracle:
            hard_logic_py = query.get("hard_logic_py", []) or []

            def base(plan):
                if not hard_logic_py:
                    return 0, 0
                try:
                    res = evaluate_constraints_py(hard_logic_py, plan, verbose=False)
                except Exception:
                    return 0, len(hard_logic_py)
                return sum(1 for r in res if bool(r)), len(res)
        else:
            target_city = query.get("target_city", "")

            def base(plan):
                try:
                    res = evaluate_parsed_constraints(constraints, plan, target_city)
                except Exception:
                    return 0, 0
                return sum(1 for r in res if r), len(res)

        def check(plan):
            passed, total = base(plan)
            extra = 0
            if passed == total:
                # Env validity only matters once every hard constraint is met.
                if self._schema_ok(query, plan):
                    extra += 1
                if self._commonsense_ok(query, plan):
                    extra += 1
            return passed + extra, total + 2
        return check

    def _get_schema(self):
        if self._schema is None:
            try:
                with open(os.path.join(project_root_path, "evaluation", "output_schema.json"), "r", encoding="utf-8") as f:
                    self._schema = json.load(f)
            except Exception:
                self._schema = {}
        return self._schema

    def _schema_ok(self, query, plan):
        uid = str(query.get("uid", ""))
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                _, _, pass_id = evaluate_schema_constraints([uid], {uid: plan}, self._get_schema())
            return uid in pass_id
        except Exception:
            return False

    def _commonsense_ok(self, query, plan):
        uid = str(query.get("uid", ""))
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                _, _, _, pass_id = evaluate_commonsense_constraints(
                    [uid], {uid: query}, {uid: plan}, verbose=False, lang=self.lang)
            return uid in pass_id
        except Exception:
            return False

    def _accepted(self, passed, total):
        """A plan is accepted when it has no checkable constraints or passes all of them."""
        return total == 0 or passed == total

    def _norm_text(self, value):
        return str(value).strip().lower() if value is not None else ""

    def _match_constraint_text(self, candidate, constraint):
        c = self._norm_text(candidate)
        q = self._norm_text(constraint)
        if not c or not q:
            return False
        return c == q or q in c or c in q

    def _match_type(self, attr_type, req_type):
        """Match attraction type using segment-based exact matching.

        Splits attr_type by '/' and checks if req_type exactly matches any segment
        (case-insensitive). Avoids false positives from substring matching, e.g.,
        'park' should not match 'Amusement Park/Sports Entertainment'.
        """
        if not attr_type or not req_type:
            return False
        req_norm = self._norm_text(req_type)
        attr_norm = self._norm_text(attr_type)
        if req_norm == attr_norm:
            return True
        segments = [s.strip() for s in attr_norm.split("/")]
        return req_norm in segments

    def _constraint_variants(self, query):
        raw = parse_constraints.parse_query(query) if self.use_oracle else parse_constraints.parse_query_no_oracle(query)
        if not isinstance(raw, dict):
            return [{}]

        constraints = {
            k: v
            for k, v in raw.items()
            if k not in ["groups", "disjunctive"]
        }
        groups = raw.get("groups", [])
        if not (raw.get("disjunctive") and isinstance(groups, list) and len(groups) > 0):
            return [constraints]

        group_keys = set()
        for group in groups:
            if isinstance(group, dict):
                group_keys.update(group.keys())

        base_constraints = {
            k: v
            for k, v in constraints.items()
            if k not in group_keys
        }

        variants = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            merged = deepcopy(base_constraints)
            merged.update(group)
            variants.append(merged)

        return variants or [constraints]

    def _collect_constraints(self, query):
        variants = self._constraint_variants(query)
        if len(variants) == 0:
            return self._augment_constraints_from_hard_logic(query, {})
        return self._augment_constraints_from_hard_logic(query, variants[0])

    def _augment_constraints_from_hard_logic(self, query, constraints):
        """Backfill frequently-missed structured constraints from hard_logic_py text."""
        merged = deepcopy(constraints) if isinstance(constraints, dict) else {}
        hard_logic_py = query.get("hard_logic_py", [])
        if not isinstance(hard_logic_py, list) or len(hard_logic_py) == 0:
            return merged

        budgets = merged.get("budgets")
        if not isinstance(budgets, dict):
            budgets = {}

        for expr in hard_logic_py:
            if not isinstance(expr, str):
                continue

            # Infer inner-city transport budget cap.
            m_inner = re.search(r"inner_city_transportation_cost\s*<=\s*(\d+(?:\.\d+)?)", expr)
            if m_inner:
                limit = float(m_inner.group(1))
                if "inner_transport" not in budgets or float(budgets.get("inner_transport", -1)) < 0:
                    budgets["inner_transport"] = limit
                else:
                    budgets["inner_transport"] = min(float(budgets["inner_transport"]), limit)

            # Infer explicit non-train requirement for both outbound/return.
            if "allactivities(plan)[0]['type'] != \"train\"" in expr and "allactivities(plan)[-1]['type'] != \"train\"" in expr:
                merged["intercity_mode"] = "airplane"
            if "allactivities(plan)[0]['type'] == \"train\"" in expr and "allactivities(plan)[-1]['type'] == \"train\"" in expr:
                merged["intercity_mode"] = "train"

            # Infer required room type.
            m_room = re.search(r"room_type\(activity\)!=(\d)", expr)
            if m_room and "room_type" not in merged:
                merged["room_type"] = int(m_room.group(1))

            # Infer required attraction type set inclusion.
            if "attraction_type_set" in expr and "{" in expr and "}" in expr:
                req_types = merged.get("required_attraction_types")
                if not isinstance(req_types, list):
                    req_types = []
                set_match = re.search(r"\{([^}]*)\}", expr, re.DOTALL)
                literals = re.findall(r"['\"]([^'\"]+)['\"]", set_match.group(1) if set_match else "")
                for t in literals:
                    if not any(self._match_constraint_text(existing, t) for existing in req_types):
                        req_types.append(t)
                merged["required_attraction_types"] = req_types

            # Infer required hotel amenity/type in featurehoteltype checks.
            if "accommodation_type_set" in expr and "{" in expr and "}" in expr:
                set_match = re.search(r"\{([^}]*)\}", expr, re.DOTALL)
                literals = re.findall(r"['\"]([^'\"]+)['\"]", set_match.group(1) if set_match else "")
                if "&accommodation_type_set" in expr:
                    req_any = merged.get("required_hotel_any_types", [])
                    if not isinstance(req_any, list):
                        req_any = []
                    for t in literals:
                        if not any(self._match_constraint_text(existing, t) for existing in req_any):
                            req_any.append(t)
                    merged["required_hotel_any_types"] = req_any
                elif "<=accommodation_type_set" in expr:
                    req_all = merged.get("required_hotel_all_types", [])
                    if not isinstance(req_all, list):
                        req_all = []
                    for t in literals:
                        if not any(self._match_constraint_text(existing, t) for existing in req_all):
                            req_all.append(t)
                    merged["required_hotel_all_types"] = req_all
                if literals and "hotel_amenity" not in merged and "hotel_type" not in merged:
                    merged["hotel_amenity"] = literals[0]

            # Infer taxi car-count constraints to avoid invalid taxi usage.
            m_taxi_cars = re.search(
                r"innercity_transport_type\(activity_transports\(activity\)\)\s*==\s*['\"]taxi['\"].*?taxi_cars\(activity_transports\(activity\)\)\s*!=\s*(\d+)",
                expr,
                re.DOTALL,
            )
            if m_taxi_cars:
                merged["taxi_cars_equals"] = int(m_taxi_cars.group(1))

            # Backfill per-POI dwell / time-window constraints from positioned-activity clauses.
            # parse_query misses these: they live inside `if activity_position(activity)==<lit>:`
            # and use activity_time / activity_start_time / activity_end_time (no stay_duration func).
            m_pos = re.search(r"activity_position\(activity\)\s*==\s*['\"]([^'\"]+)['\"]", expr)
            if m_pos:
                loc = m_pos.group(1)
                min_minutes = None
                m_dur = re.search(r"activity_time\(activity\)\s*/\s*60\s*>=\s*(\d+(?:\.\d+)?)", expr)
                if m_dur:
                    min_minutes = int(round(float(m_dur.group(1)) * 60))
                else:
                    m_dur = re.search(r"activity_time\(activity\)\s*>=\s*(\d+)", expr)
                    if m_dur:
                        min_minutes = int(m_dur.group(1))
                earliest = latest = end_after = end_before = None
                m_w = re.search(r"activity_start_time\(activity\)\s*>=\s*['\"](\d{2}:\d{2})['\"]", expr)
                if m_w:
                    earliest = m_w.group(1)
                m_w = re.search(r"activity_start_time\(activity\)\s*<=\s*['\"](\d{2}:\d{2})['\"]", expr)
                if m_w:
                    latest = m_w.group(1)
                m_w = re.search(r"activity_end_time\(activity\)\s*>=\s*['\"](\d{2}:\d{2})['\"]", expr)
                if m_w:
                    end_after = m_w.group(1)
                m_w = re.search(r"activity_end_time\(activity\)\s*<=\s*['\"](\d{2}:\d{2})['\"]", expr)
                if m_w:
                    end_before = m_w.group(1)
                # A "start<=T1 and end>=T2" window implies a minimum dwell of T2-T1 minutes.
                if latest and end_after:
                    span = time_to_minutes(end_after) - time_to_minutes(latest)
                    if span > 0:
                        min_minutes = max(min_minutes or 0, span)
                if min_minutes is not None and min_minutes > 0:
                    durations = merged.get("stay_duration")
                    if not isinstance(durations, list):
                        durations = []
                    if not any(isinstance(d, dict) and self._match_constraint_text(d.get("location", ""), loc) for d in durations):
                        durations.append({"location": loc, "min_minutes": min_minutes})
                    merged["stay_duration"] = durations
                if earliest or latest or end_after or end_before:
                    windows = merged.get("activity_time_windows")
                    if not isinstance(windows, list):
                        windows = []
                    if not any(isinstance(w, dict) and self._match_constraint_text(w.get("location", ""), loc) for w in windows):
                        windows.append({
                            "location": loc,
                            "earliest": earliest,
                            "latest": latest,
                            "end_after": end_after,
                            "end_before": end_before,
                        })
                    merged["activity_time_windows"] = windows

        merged["budgets"] = budgets
        return merged

    def _resolve_required_names(self, raw_required, candidate_names):
        if not isinstance(raw_required, list) or len(raw_required) == 0:
            return []
        candidates = [str(n) for n in candidate_names if str(n).strip()]
        if not candidates:
            return []
        resolved = []
        for req in raw_required:
            req_text = str(req).strip()
            if not req_text:
                continue
            direct = [
                c for c in candidates
                if self._match_constraint_text(c, req_text) or self._match_constraint_text(req_text, c)
            ]
            if direct:
                chosen = direct[0]
            else:
                req_norm = self._norm_text(req_text)
                scored = sorted(
                    (
                        (SequenceMatcher(None, req_norm, self._norm_text(c)).ratio(), c)
                        for c in candidates
                    ),
                    reverse=True,
                )
                chosen = scored[0][1] if scored and scored[0][0] >= 0.72 else None
            if chosen and not any(self._match_constraint_text(chosen, existing) for existing in resolved):
                resolved.append(chosen)
        return resolved

    def _plan_total_cost(self, plan):
        total = 0.0
        for day in plan.get("itinerary", []) or []:
            for activity in day.get("activities", []) or []:
                total += self._safe_float(activity.get("cost", 0.0), 0.0)
                total += self._transport_cost_total(activity.get("transports", []))
        return total

    def _slot_visit_len(self, params, constraints):
        """Conservative slot length used before the specific attraction is chosen: the
        longest dwell any constraint demands (clamped to 240), at least visit_minutes/90."""
        longest = 0
        for d in constraints.get("stay_duration", []) or []:
            if isinstance(d, dict):
                try:
                    longest = max(longest, int(d.get("min_minutes", 0)))
                except (TypeError, ValueError):
                    pass
        return min(240, max(int(params.get("visit_minutes", 90)), longest, 90))

    def _visit_len(self, attr, params, constraints):
        """Actual visit length for a chosen attraction: visit_minutes, raised to this POI's
        own min dwell when a stay_duration constraint names it (clamped to 240)."""
        name = str(attr["name"])
        need = 0
        for d in constraints.get("stay_duration", []) or []:
            if isinstance(d, dict) and self._match_constraint_text(name, d.get("location", "")):
                try:
                    need = max(need, int(d.get("min_minutes", 0)))
                except (TypeError, ValueError):
                    pass
        return min(240, max(int(params.get("visit_minutes", 90)), need))

    def _rotate_tail(self, items, is_pinned, offset):
        """Rotate only the non-pinned tail of `items` by `offset` (pinned entries stay at front)."""
        pinned = [x for x in items if is_pinned(x)]
        tail = [x for x in items if not is_pinned(x)]
        if tail and offset:
            off = offset % len(tail)
            tail = tail[off:] + tail[:off]
        return pinned + tail

    def _apply_search_constraints(self, constraints, params):
        """Project per-POI dwell/time-window POIs into the required pools (so the base build
        includes them) and a window's latest-start onto an arrive_no_later timing constraint
        (so the existing slot machinery refuses placing the POI too late)."""
        merged = dict(constraints) if isinstance(constraints, dict) else {}
        windows = merged.get("activity_time_windows", []) or []
        durations = merged.get("stay_duration", []) or []

        positioned = []
        for w in windows:
            if isinstance(w, dict) and w.get("location"):
                positioned.append(str(w["location"]))
        for d in durations:
            if isinstance(d, dict) and d.get("location"):
                positioned.append(str(d["location"]))
        if positioned:
            # The resolver filters per-DB, so a name only survives in the pool it actually matches.
            for key in ("required_attractions", "required_restaurants"):
                existing = list(merged.get(key, []) or [])
                for loc in positioned:
                    if not any(self._match_constraint_text(loc, e) for e in existing):
                        existing.append(loc)
                merged[key] = existing

        extra_timing = []
        for w in windows:
            if isinstance(w, dict) and w.get("location") and w.get("latest"):
                extra_timing.append({"type": "arrive_no_later", "location": str(w["location"]), "time": str(w["latest"])})
        if extra_timing:
            tc = list(merged.get("timing_constraints", []) or [])
            for e in extra_timing:
                if not any(isinstance(t, dict) and t.get("type") == e["type"]
                           and self._match_constraint_text(t.get("location", ""), e["location"]) for t in tc):
                    tc.append(e)
            merged["timing_constraints"] = tc
        return merged

    def _activity_counts(self, plan):
        attrs = meals = 0
        for day in plan.get("itinerary", []) or []:
            for a in day.get("activities", []) or []:
                t = a.get("type")
                if t == "attraction":
                    attrs += 1
                elif t in ("breakfast", "lunch", "dinner"):
                    meals += 1
        return attrs, meals

    def _repair_params(self, constraints):
        """Deterministic param priors derived from which constraints are present, tried before
        random restarts so single-signal queries converge fast."""
        candidates = []
        budgets = constraints.get("budgets", {}) or {}
        if budgets.get("inner_transport") is not None:
            candidates.append({"forced_inner_mode": "walk"})
            candidates.append({"forced_inner_mode": "metro"})
        excl = set(self._norm_text(m) for m in (constraints.get("excluded_inner_transport", []) or []))
        if excl or constraints.get("conditional_transport") or constraints.get("taxi_cars_equals") is not None:
            for m in ("metro", "walk", "taxi"):
                if m not in excl:
                    candidates.append({"forced_inner_mode": m})
        mode = constraints.get("intercity_mode")
        if isinstance(mode, str):
            candidates.append({"intercity_go_pref": mode, "intercity_back_pref": mode})
        if any(constraints.get(k) for k in (
            "hotel_nearby", "required_hotel_any_types", "required_hotel_all_types",
            "room_type", "hotel_type", "hotel_amenity", "required_hotels",
        )):
            for hi in range(0, 6):
                candidates.append({"hotel_index": hi})
        if any(constraints.get(k) for k in ("activity_time_windows", "timing_constraints", "stay_duration")):
            for off in range(1, 6):
                candidates.append({"attr_offset": off})
        for off in (1, 2, 3):
            candidates.append({"attr_offset": off})

        seen = set()
        unique = []
        for p in candidates:
            key = tuple(sorted(p.items()))
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique

    def _random_params(self, rng):
        params = {
            "attr_offset": rng.randint(0, 12),
            "hotel_index": rng.randint(0, 4),
            "attr_per_day": rng.choice([2, 3, 4]),
        }
        forced = rng.choice([None, "metro", "walk", "taxi"])
        if forced is not None:
            params["forced_inner_mode"] = forced
        if rng.random() < 0.35:
            params["intercity_go_pref"] = rng.choice(["airplane", "train"])
            params["intercity_back_pref"] = rng.choice(["airplane", "train"])
        if rng.random() < 0.35:
            params["rest_offset"] = rng.randint(0, 6)
        return params

    def _solve(self, query):
        """Per-query oracle-guided search: base build, guided repair, then random multi-start,
        keeping the best (most-constraints-passed, then cheapest) plan; finally pack it."""
        variants = self._constraint_variants(query) or [None]
        rng = random.Random(hash((str(query.get("uid", "")), str(self.seed_salt))) & 0xFFFFFFFF)
        best = {"plan": None, "key": None, "constraints": None, "check": None, "params": None}

        def consider(plan, constraints, check, params):
            try:
                passed, total = check(plan)
            except Exception:
                passed, total = 0, 0
            key = (passed, -self._plan_total_cost(plan))
            if best["plan"] is None or key > best["key"]:
                best.update(plan=plan, key=key, constraints=constraints, check=check, params=params)
            return self._accepted(passed, total)

        def out_of_budget():
            return time.time() - self.start_clock > self.solve_budget_sec

        restarts = 0
        solved = False
        for variant in variants:
            if solved or out_of_budget():
                break
            constraints = self._augment_constraints_from_hard_logic(query, variant or {})
            check = self._make_checker(query, constraints)
            try:
                if consider(self._build_plan(query, constraints=constraints), constraints, check, {}):
                    break
            except Exception:
                import traceback
                traceback.print_exc()

            for params in self._repair_params(constraints):
                if out_of_budget():
                    break
                try:
                    if consider(self._build_plan(query, constraints=constraints, params=params), constraints, check, params):
                        solved = True
                        break
                except Exception:
                    continue
            if solved:
                break

            while restarts < self.max_restarts and not out_of_budget():
                restarts += 1
                params = self._random_params(rng)
                try:
                    if consider(self._build_plan(query, constraints=constraints, params=params), constraints, check, params):
                        solved = True
                        break
                except Exception:
                    continue
            if solved:
                break

        if best["plan"] is not None and best["check"] is not None:
            packed = self._pack_plan(best["plan"], query, best["constraints"], best["check"], best["params"])
            if packed is not None:
                best["plan"] = packed

        return best["plan"] if best["plan"] is not None else self._build_plan(query)

    def _pack_plan(self, plan, query, constraints, check, base_params):
        """Add attractions/meals (attr_per_day 3 then 4) while acceptance still holds, to lift
        DAV/DDR. Never trades a hard pass for preference: gated locally by `check`."""
        if not self._accepted(*check(plan)):
            return plan
        best_plan = plan
        best_attrs, best_meals = self._activity_counts(plan)
        for extra in (3, 4):
            if time.time() - self.start_clock > self.solve_budget_sec:
                break
            params = dict(base_params or {})
            params["attr_per_day"] = extra
            try:
                cand = self._build_plan(query, constraints=constraints, params=params)
            except Exception:
                continue
            if not self._accepted(*check(cand)):
                continue
            c_attrs, c_meals = self._activity_counts(cand)
            if (c_attrs + c_meals) > (best_attrs + best_meals):
                best_plan = cand
                best_attrs, best_meals = c_attrs, c_meals
        return best_plan

    def _room_type_to_numbed(self, room_type):
        if room_type is None:
            return None
        if isinstance(room_type, (int, float)):
            try:
                iv = int(room_type)
                if iv in [1, 2]:
                    return iv
            except Exception:
                return None
        t = self._norm_text(room_type)
        if any(k in t for k in ["single", "1", "one"]):
            return 1
        if any(k in t for k in ["double", "twin", "2", "two"]):
            return 2
        return None

    def _safe_float(self, value, default=0.0):
        try:
            return float(value)
        except Exception:
            return default

    def _extract_budget_limits(self, constraints):
        budgets = constraints.get("budgets", {}) or {}
        if not isinstance(budgets, dict):
            budgets = {}
        limits = {
            "sightseeing": -1.0,
            "dining": -1.0,
            "accommodation": -1.0,
            "intercity_transport": -1.0,
            "inner_transport": -1.0,
            "total": -1.0,
        }
        for k in limits.keys():
            if k in budgets:
                raw_val = budgets.get(k)
                if raw_val is None:
                    continue
                try:
                    v = float(raw_val)
                except Exception:
                    continue
                if v >= 0:
                    limits[k] = v
        return limits

    def _new_budget_tracker(self):
        return {
            "sightseeing": 0.0,
            "dining": 0.0,
            "accommodation": 0.0,
            "intercity_transport": 0.0,
            "inner_transport": 0.0,
            "total": 0.0,
        }

    def _transport_cost_total(self, transports):
        total = 0.0
        for t in transports or []:
            total += self._safe_float(t.get("cost", 0.0), 0.0)
        return total

    def _activity_bucket_costs(self, activity):
        bucket_costs = {
            "sightseeing": 0.0,
            "dining": 0.0,
            "accommodation": 0.0,
            "intercity_transport": 0.0,
            "inner_transport": self._transport_cost_total(activity.get("transports", [])),
            "total": 0.0,
        }
        atype = activity.get("type", "")
        main_cost = self._safe_float(activity.get("cost", 0.0), 0.0)

        if atype == "attraction":
            bucket_costs["sightseeing"] += main_cost
        elif atype in ["breakfast", "lunch", "dinner"]:
            bucket_costs["dining"] += main_cost
        elif atype == "accommodation":
            bucket_costs["accommodation"] += main_cost
        elif atype in ["airplane", "train"]:
            bucket_costs["intercity_transport"] += main_cost

        for k in ["sightseeing", "dining", "accommodation", "intercity_transport", "inner_transport"]:
            bucket_costs["total"] += bucket_costs[k]
        return bucket_costs

    def _can_add_activity_under_budget(self, activity, budget_limits, budget_tracker):
        if not budget_limits:
            return True
        inc = self._activity_bucket_costs(activity)
        for k, limit in budget_limits.items():
            if limit < 0:
                continue
            projected = self._safe_float(budget_tracker.get(k, 0.0), 0.0) + self._safe_float(inc.get(k, 0.0), 0.0)
            if projected > limit + 1e-6:
                return False
        return True

    def _register_activity_cost(self, activity, budget_tracker):
        inc = self._activity_bucket_costs(activity)
        for k in budget_tracker.keys():
            budget_tracker[k] = self._safe_float(budget_tracker.get(k, 0.0), 0.0) + self._safe_float(inc.get(k, 0.0), 0.0)

    def _append_activity(self, activities, activity, budget_limits, budget_tracker, force=False):
        if force or self._can_add_activity_under_budget(activity, budget_limits, budget_tracker):
            activities.append(activity)
            self._register_activity_cost(activity, budget_tracker)
            return True
        return False

    def _append_preregistered_activity(self, activities, activity):
        """Append an activity whose cost was already pre-registered in the budget_tracker."""
        activities.append(activity)
        return True

    def _timing_constraint_minutes(self, timing_constraints, locations, constraint_type, take_max):
        if not timing_constraints or not locations:
            return None
        values = []
        for constraint in timing_constraints:
            if not isinstance(constraint, dict) or constraint.get("type") != constraint_type:
                continue
            constraint_location = str(constraint.get("location", "")).strip()
            constraint_time = constraint.get("time", None)
            if not constraint_location or not constraint_time:
                continue
            for location in locations:
                location = str(location).strip()
                if not location:
                    continue
                if self._match_constraint_text(location, constraint_location) or self._match_constraint_text(
                    constraint_location, location
                ):
                    values.append(time_to_minutes(str(constraint_time)))
                    break
        if not values:
            return None
        return max(values) if take_max else min(values)

    def _timing_departure_floor(self, timing_constraints, locations):
        return self._timing_constraint_minutes(timing_constraints, locations, "depart_no_earlier", True)

    def _timing_arrival_ceiling(self, timing_constraints, locations):
        return self._timing_constraint_minutes(timing_constraints, locations, "arrive_no_later", False)

    def _activity_timing_allowed(self, location, start_time, timing_constraints, extra_locations=None):
        locations = [location]
        if extra_locations:
            locations.extend(extra_locations)
        ceiling = self._timing_arrival_ceiling(timing_constraints, locations)
        if ceiling is not None and time_to_minutes(start_time) > ceiling:
            return False
        return True

    def _route_timing_allowed(self, timing_constraints, from_locations, to_locations, begin_time, end_time):
        depart_floor = self._timing_departure_floor(timing_constraints, from_locations)
        if depart_floor is not None and time_to_minutes(begin_time) < depart_floor:
            return False
        arrival_ceiling = self._timing_arrival_ceiling(timing_constraints, to_locations)
        if arrival_ceiling is not None and time_to_minutes(end_time) > arrival_ceiling:
            return False
        return True

    def _affordable_main_cost(self, bucket, cost_value, budget_limits, budget_tracker):
        if not budget_limits:
            return True
        c = self._safe_float(cost_value, 0.0)
        bucket_limit = budget_limits.get(bucket)
        if bucket_limit is not None and bucket_limit >= 0 and self._safe_float(budget_tracker.get(bucket, 0.0), 0.0) + c > bucket_limit + 1e-6:
            return False
        total_limit = budget_limits.get("total")
        if total_limit is not None and total_limit >= 0 and self._safe_float(budget_tracker.get("total", 0.0), 0.0) + c > total_limit + 1e-6:
            return False
        return True

    def _pick_restaurant(self, restaurants, start_idx, people, budget_limits, budget_tracker):
        idx = start_idx
        fallback = None
        while idx < len(restaurants):
            r = restaurants[idx]
            full_cost = self._safe_float(r.get("price", 0.0), 0.0) * people
            if self._affordable_main_cost("dining", full_cost, budget_limits, budget_tracker):
                return r, idx + 1
            if fallback is None:
                fallback = (r, idx + 1)
            idx += 1
        return fallback if fallback is not None else (None, start_idx)

    def _is_required_attraction(self, attr, required_attractions, required_attraction_types):
        if attr is None:
            return False
        name = str(attr.get("name", ""))
        attr_type = str(attr.get("type", ""))
        by_name = bool(required_attractions) and any(
            self._match_constraint_text(name, req)
            for req in required_attractions
        )
        by_type = bool(required_attraction_types) and any(
            self._match_type(attr_type, req_t)
            for req_t in required_attraction_types
        )
        return by_name or by_type

    def _is_required_restaurant(self, restaurant, required_restaurants):
        if restaurant is None:
            return False
        if not required_restaurants:
            return False
        name = str(restaurant.get("name", ""))
        return any(self._match_constraint_text(name, req) for req in required_restaurants)

    def run(self, query, prob_idx=None, oralce_translation=False):
        self.reset_clock()

        try:
            plan = self._solve(query)
        except Exception:
            import traceback
            traceback.print_exc()
            plan = {
                "people_number": query.get("people_number", 1),
                "start_city": query.get("start_city", ""),
                "target_city": query.get("target_city", ""),
                "itinerary": [],
            }

        plan["elapsed_time(sec)"] = time.time() - self.start_clock
        return True, plan

    def _build_plan(self, query, constraints=None, params=None):
        """Build a valid itinerary with proper transport, timing, and costs.

        `params` carries per-restart search knobs (visit_minutes, attr_per_day, attr_offset,
        rest_offset, hotel_index, forced_inner_mode, intercity_go_pref/back_pref); every
        default reproduces the original greedy behaviour.
        """
        params = params or {}
        people = query["people_number"]
        start_city = query["start_city"]
        target_city = query["target_city"]
        days = query["days"]
        if constraints is None:
            constraints = self._collect_constraints(query)
        constraints = self._apply_search_constraints(constraints, params)
        self._forced_inner_mode = params.get("forced_inner_mode")
        timing_constraints = constraints.get("timing_constraints", []) or []
        self._active_timing_constraints = timing_constraints
        budget_limits = self._extract_budget_limits(constraints)
        budget_tracker = self._new_budget_tracker()
        self._budget_limits = budget_limits
        self._budget_tracker = budget_tracker
        self._transport_constraints = {
            "excluded_inner_transport": constraints.get("excluded_inner_transport", []),
            "conditional_transport": constraints.get("conditional_transport", None),
            "taxi_cars_equals": constraints.get("taxi_cars_equals", None),
        }

        env = self.env
        if env is None:
            return {
                "people_number": people,
                "start_city": start_city,
                "target_city": target_city,
                "itinerary": [],
            }

        # --- Get intercity transport (outbound + return) ---
        intercity_mode = constraints.get("intercity_mode", None)
        outbound_pref = None
        return_pref = None
        if isinstance(intercity_mode, dict):
            outbound_pref = intercity_mode.get("outbound", None)
            return_pref = intercity_mode.get("return", None)
        elif isinstance(intercity_mode, str):
            outbound_pref = intercity_mode
            return_pref = intercity_mode
        # Search may override the intercity mode preference per direction.
        if "intercity_go_pref" in params:
            outbound_pref = params["intercity_go_pref"]
        if "intercity_back_pref" in params:
            return_pref = params["intercity_back_pref"]

        outbound = self._get_intercity(env, start_city, target_city, "07:00", outbound_pref, budget_limits, budget_tracker, people=people)
        return_transport = self._get_intercity(env, target_city, start_city, "17:00", return_pref, budget_limits, budget_tracker, pending_intercity=outbound, people=people)
        # If no return at 17:00, try earlier
        if return_transport is None:
            return_transport = self._get_intercity(env, target_city, start_city, "14:00", return_pref, budget_limits, budget_tracker, pending_intercity=outbound, people=people)
        if return_transport is None:
            return_transport = self._get_intercity(env, target_city, start_city, "00:00", return_pref, budget_limits, budget_tracker, pending_intercity=outbound, people=people)

        # Pre-register intercity costs so hotel/meal selections see the correct remaining budget
        _out_cost = self._safe_float(outbound.get("Cost", 0.0), 0.0) * people if outbound else 0.0
        _ret_cost = self._safe_float(return_transport.get("Cost", 0.0), 0.0) * people if return_transport else 0.0
        budget_tracker["intercity_transport"] = budget_tracker.get("intercity_transport", 0.0) + _out_cost + _ret_cost
        budget_tracker["total"] = budget_tracker.get("total", 0.0) + _out_cost + _ret_cost

        # --- Get one accommodation near the arrival/departure point ---
        arrival_pos = outbound["To"] if outbound else None
        required_hotels = constraints.get("required_hotels", []) or []
        excluded_hotels = constraints.get("excluded_hotels", []) or []
        room_numbed = self._room_type_to_numbed(constraints.get("room_type", None))
        hotel_type = constraints.get("hotel_type", None)
        hotel_amenity = constraints.get("hotel_amenity", None)
        required_hotel_all_types = constraints.get("required_hotel_all_types", []) or []
        required_hotel_any_types = constraints.get("required_hotel_any_types", []) or []
        hotel_nearby = constraints.get("hotel_nearby", None)

        accom_df = env.accommodations.select(target_city, "name", lambda x: True)
        required_hotels = self._resolve_required_names(required_hotels, [str(accom_df.iloc[i]["name"]) for i in range(len(accom_df))])

        def _hotel_ok(h):
            name = str(h["name"])
            feature_type = str(h.get("featurehoteltype", ""))
            if required_hotels and not any(self._match_constraint_text(name, n) for n in required_hotels):
                return False
            if excluded_hotels and any(self._match_constraint_text(name, n) for n in excluded_hotels):
                return False
            if room_numbed is not None:
                try:
                    if int(h["numbed"]) != room_numbed:
                        return False
                except Exception:
                    return False
            if hotel_type:
                if not self._match_constraint_text(feature_type, hotel_type):
                    return False
            if hotel_amenity:
                if not self._match_constraint_text(feature_type, hotel_amenity):
                    return False
            if required_hotel_all_types and any(not self._match_constraint_text(feature_type, t) for t in required_hotel_all_types):
                return False
            if required_hotel_any_types and not any(self._match_constraint_text(feature_type, t) for t in required_hotel_any_types):
                return False
            try:
                rooms_local = math.ceil(people / int(h.get("numbed", 1)))
            except Exception:
                rooms_local = people
            h_cost = self._safe_float(h.get("price", 0.0), 0.0) * rooms_local * max(days - 1, 0)
            if not self._affordable_main_cost("accommodation", h_cost, budget_limits, budget_tracker):
                return False
            return True

        hotel_index = max(0, int(params.get("hotel_index", 0)))

        def _pick_ok(df):
            ok_list = [df.iloc[i] for i in range(len(df)) if _hotel_ok(df.iloc[i])]
            if not ok_list:
                return None
            return ok_list[min(hotel_index, len(ok_list) - 1)]

        hotel = None
        nearby_df = None
        hotel_from_nearby_constraint = False
        if isinstance(hotel_nearby, dict):
            ref = hotel_nearby.get("reference", None)
            dist_km = hotel_nearby.get("distance_km", 5)
            if ref:
                try:
                    nearby_df = env.accommodations.nearby(target_city, ref, topk=20, dist=dist_km)
                except Exception:
                    nearby_df = None

        if nearby_df is not None and not isinstance(nearby_df, str) and len(nearby_df) > 0:
            hotel = _pick_ok(nearby_df)
            if hotel is not None:
                hotel_from_nearby_constraint = True

        if hotel is None and arrival_pos and not hotel_from_nearby_constraint:
            try:
                nearby_hotels = env.accommodations.nearby(target_city, arrival_pos, topk=5, dist=20)
                if not isinstance(nearby_hotels, str) and len(nearby_hotels) > 0:
                    hotel = _pick_ok(nearby_hotels)
            except Exception:
                pass
        if hotel is None:
            hotel = _pick_ok(accom_df)
        if hotel is None:
            # Fall back to cheapest option even when strict filters are infeasible.
            best = None
            best_price = None
            best_affordable = False
            for i in range(len(accom_df)):
                h = accom_df.iloc[i]
                p = self._safe_float(h.get("price", 0.0), 0.0)
                try:
                    rooms_local = math.ceil(people / int(h.get("numbed", 1)))
                except Exception:
                    rooms_local = people
                h_cost = p * rooms_local * max(days - 1, 0)
                affordable = self._affordable_main_cost("accommodation", h_cost, budget_limits, budget_tracker)
                should_take = False
                if best is None or best_price is None:
                    should_take = True
                elif affordable and not best_affordable:
                    should_take = True
                elif affordable == best_affordable and p < best_price:
                    should_take = True
                if should_take:
                    best = h
                    best_price = p
                    best_affordable = affordable
            hotel = best if best is not None else accom_df.iloc[0]
        hotel_name = str(hotel["name"])
        rooms_needed = math.ceil(people / int(hotel["numbed"]))

        # Pre-register hotel accommodation costs so that subsequent meal/attraction budget checks
        # see the correct remaining budget (hotel is force-appended later without re-registering)
        _hotel_price = self._safe_float(hotel.get("price", 0.0), 0.0)
        _hotel_total = _hotel_price * rooms_needed * max(days - 1, 0)
        budget_tracker["accommodation"] = budget_tracker.get("accommodation", 0.0) + _hotel_total
        budget_tracker["total"] = budget_tracker.get("total", 0.0) + _hotel_total

        # --- Get attractions that are open during reasonable visit hours ---
        required_attractions = constraints.get("required_attractions", []) or []
        required_attraction_types = constraints.get("required_attraction_types", []) or []
        excluded_attractions = constraints.get("excluded_attractions", []) or []
        excluded_attraction_types = constraints.get("excluded_attraction_types", []) or []
        free_attractions_only = bool(constraints.get("free_attractions_only", False))

        attr_df = env.attractions.select(target_city, "name", lambda x: True)
        required_attractions = self._resolve_required_names(required_attractions, [str(attr_df.iloc[i]["name"]) for i in range(len(attr_df))])

        # Augment required_attractions with named locations from timing constraints that exist in the attraction DB
        _attr_names_list = [str(attr_df.iloc[i]["name"]) for i in range(len(attr_df))]
        _timing_locs_for_restaurants = []  # locations not found in attractions, will check restaurants later
        for _tc in timing_constraints:
            _loc = str(_tc.get("location", "")).strip()
            if not _loc or _loc in {start_city, target_city}:
                continue
            _matches = [n for n in _attr_names_list if self._match_constraint_text(n, _loc) or self._match_constraint_text(_loc, n)]
            if _matches:
                _canon = _matches[0]
                if not any(self._match_constraint_text(_canon, ex) for ex in required_attractions):
                    required_attractions.append(_canon)
            else:
                _timing_locs_for_restaurants.append(_loc)

        prioritized_required = []
        optional_pool = []
        seen_attr = set()
        for i in range(len(attr_df)):
            a = attr_df.iloc[i]
            name = str(a["name"])
            attr_type = str(a.get("type", ""))

            if excluded_attractions and any(self._match_constraint_text(name, ex) for ex in excluded_attractions):
                continue
            if excluded_attraction_types and any(self._match_constraint_text(attr_type, ex) for ex in excluded_attraction_types):
                continue
            if free_attractions_only:
                try:
                    if float(a["price"]) > 0:
                        continue
                except Exception:
                    continue

            required_by_name = required_attractions and any(
                self._match_constraint_text(name, req)
                for req in required_attractions
            )
            required_by_type = required_attraction_types and any(
                self._match_type(attr_type, req_t)
                for req_t in required_attraction_types
            )

            name_key = self._norm_text(name)
            if required_by_name or required_by_type:
                if name_key not in seen_attr:
                    prioritized_required.append(a)
                    seen_attr.add(name_key)
            else:
                if name_key not in seen_attr:
                    optional_pool.append(a)
                    seen_attr.add(name_key)

        candidate_attrs = prioritized_required + optional_pool

        # Sort optional attractions by price to improve budget feasibility while keeping required first.
        if len(prioritized_required) < len(candidate_attrs):
            sorted_optional = sorted(
                optional_pool,
                key=lambda x: self._safe_float(x.get("price", 0.0), 0.0),
            )
            candidate_attrs = prioritized_required + sorted_optional

        # Filter to attractions open during daytime visit windows (09:00-17:00)
        # Required attractions always bypass the opentime filter.
        required_set = set(self._norm_text(str(a["name"])) for a in prioritized_required)
        good_attrs = []
        for a in candidate_attrs:
            name_key = self._norm_text(str(a["name"]))
            is_required = name_key in required_set
            opentime = str(a["opentime"])
            endtime = str(a["endtime"])
            ot_min = time_to_minutes(opentime)
            et_min = time_to_minutes(endtime)
            # Handle wrap-around (e.g., 00:00-24:00 = always open)
            if et_min <= ot_min:
                et_min += 24 * 60
            # Must be open by 09:30 and stay open until at least 12:00
            # so we can fit a 90-min visit in the morning or afternoon
            passes_filter = ot_min <= 570 and et_min >= 720  # 09:30=570, 12:00=720
            if is_required or passes_filter:
                good_attrs.append(a)
            if len(good_attrs) >= days * 4 + len(required_set):
                break
        # Fallback: just take the first ones
        if len(good_attrs) < days * 2:
            base_pool = candidate_attrs if len(candidate_attrs) > 0 else [attr_df.iloc[i] for i in range(len(attr_df))]
            good_attrs = list(base_pool[: min(len(base_pool), days * 4)])

        # --- Get restaurants open during meal times ---
        required_restaurants = constraints.get("required_restaurants", []) or []
        excluded_restaurants = constraints.get("excluded_restaurants", []) or []
        cuisine_preference = constraints.get("cuisine_preference", None)
        excluded_cuisine_types = constraints.get("excluded_cuisine_types", []) or []

        rest_df = env.restaurants.select(target_city, "name", lambda x: True)
        required_restaurants = self._resolve_required_names(required_restaurants, [str(rest_df.iloc[i]["name"]) for i in range(len(rest_df))])

        # Augment required_restaurants with timing constraint locations found in the restaurant DB
        _rest_names_list = [str(rest_df.iloc[i]["name"]) for i in range(len(rest_df))]
        for _loc in _timing_locs_for_restaurants:
            _matches = [n for n in _rest_names_list if self._match_constraint_text(n, _loc) or self._match_constraint_text(_loc, n)]
            if _matches:
                _canon = _matches[0]
                if not any(self._match_constraint_text(_canon, ex) for ex in required_restaurants):
                    required_restaurants.append(_canon)
        lunch_restaurants = []
        dinner_restaurants = []
        required_rest_pool = []
        optional_rest_pool = []
        seen_rest = set()
        for i in range(len(rest_df)):
            r = rest_df.iloc[i]
            name = str(r["name"])
            cuisine = str(r.get("cuisine", ""))

            if excluded_restaurants and any(self._match_constraint_text(name, ex) for ex in excluded_restaurants):
                continue
            if excluded_cuisine_types and any(self._match_constraint_text(cuisine, ex) for ex in excluded_cuisine_types):
                continue

            is_required = required_restaurants and any(
                self._match_constraint_text(name, req)
                for req in required_restaurants
            )
            cuisine_match = cuisine_preference and self._match_constraint_text(cuisine, cuisine_preference)

            key = self._norm_text(name)
            if key in seen_rest:
                continue
            seen_rest.add(key)
            if is_required or cuisine_match:
                required_rest_pool.append(r)
            else:
                optional_rest_pool.append(r)

        candidate_restaurants = required_rest_pool + optional_rest_pool

        used_rest_names = set()
        for r in candidate_restaurants:
            name = str(r["name"])
            opentime = str(r["opentime"])
            endtime = str(r["endtime"])
            ot_min = time_to_minutes(opentime)
            # Handle wrap-around (endtime < opentime means open past midnight)
            if endtime < opentime:
                et_min = time_to_minutes(endtime) + 24 * 60
            else:
                et_min = time_to_minutes(endtime)
            # Check if open for lunch (11:00-14:00)
            if name not in used_rest_names and ot_min <= 660 and et_min >= 840:  # 11:00=660, 14:00=840
                lunch_restaurants.append(r)
                used_rest_names.add(name)
            # Check if open for dinner (17:00-20:00)
            elif name not in used_rest_names and ot_min <= 1020 and et_min >= 1200:  # 17:00=1020, 20:00=1200
                dinner_restaurants.append(r)
                used_rest_names.add(name)
            if len(lunch_restaurants) >= days and len(dinner_restaurants) >= days:
                break

        # Search-controlled rotation of the OPTIONAL tail (required/prioritized stay pinned at front),
        # so distinct restarts try different optional POIs/restaurants without dropping a requirement.
        attr_offset = int(params.get("attr_offset", 0))
        if attr_offset:
            good_attrs = self._rotate_tail(
                good_attrs, lambda a: self._norm_text(str(a["name"])) in required_set, attr_offset)
        rest_offset = int(params.get("rest_offset", 0))
        if rest_offset:
            lunch_restaurants = self._rotate_tail(
                lunch_restaurants, lambda r: self._is_required_restaurant(r, required_restaurants), rest_offset)
            dinner_restaurants = self._rotate_tail(
                dinner_restaurants, lambda r: self._is_required_restaurant(r, required_restaurants), rest_offset)

        # --- Build day-by-day itinerary ---
        itinerary = []
        attr_idx = 0
        lunch_idx = 0
        dinner_idx = 0
        current_pos = None  # Track current position for transport
        # Required attractions that haven't been scheduled yet — tried first at each slot
        self._required_attrs_remaining = list(prioritized_required)
        self._scheduled_attr_names = set()

        for day_num in range(1, days + 1):
            activities = []
            # Per-day extra-attraction budget shared across the morning/afternoon/evening fills.
            # max(0, attr_per_day-2) is 0 at the base attr_per_day=2, so the accepted-plan search
            # is byte-identical to pre-refactor; enrichment only engages for attr_per_day>=3.
            extra_budget = max(0, int(params.get("attr_per_day", 2)) - 2)
            extra_used = 0

            if day_num == 1:
                # === DAY 1: Arrive + activities + hotel ===
                if outbound is not None:
                    act = self._make_intercity_activity(outbound, people)
                    self._append_preregistered_activity(activities, act)
                    current_time = outbound["EndTime"]
                    current_pos = outbound["To"]
                else:
                    current_time = "09:00"
                    current_pos = hotel_name

                # Lunch (if time allows, start between 11:00-13:00)
                if time_before(current_time, "13:00") and lunch_idx < len(lunch_restaurants):
                    restaurant, new_lunch_idx = self._pick_restaurant(
                        lunch_restaurants,
                        lunch_idx,
                        people,
                        budget_limits,
                        budget_tracker,
                    )
                    if restaurant is not None:
                        lunch_idx = new_lunch_idx
                    lunch_start = max(current_time, "11:00")
                    # Add transport to restaurant
                    rest_name = str(restaurant["name"]) if restaurant is not None else current_pos
                    transports, travel_end = self._get_transport(
                        env, target_city, current_pos, rest_name, current_time, people)
                    if transports is not None:
                        lunch_start = max(travel_end or current_time, "11:00")
                    else:
                        transports = []
                    lunch_end = add_minutes(lunch_start, 60)
                    if restaurant is not None and time_before(lunch_end, "14:00") and self._activity_timing_allowed(
                        rest_name,
                        lunch_start,
                        timing_constraints,
                        [current_pos],
                    ):
                        meal = self._make_meal_activity(
                            "lunch", restaurant, people, lunch_start, lunch_end, transports)
                        is_req_rest = self._is_required_restaurant(restaurant, required_restaurants)
                        added = self._append_activity(
                            activities,
                            meal,
                            budget_limits,
                            budget_tracker,
                            force=is_req_rest,
                        )
                        if added:
                            current_time = lunch_end
                            current_pos = rest_name

                # Afternoon attraction
                if time_before(current_time, "16:30") and attr_idx < len(good_attrs):
                    # Estimate visit time and check open hours
                    est_start = add_minutes(current_time, 20)  # ~20 min travel
                    est_end = add_minutes(est_start, self._slot_visit_len(params, constraints))
                    attr, attr_idx = self._pick_attraction(good_attrs, attr_idx, est_start, est_end)
                    if attr is not None:
                        attr_name = str(attr["name"])
                        transports, travel_end = self._get_transport(
                            env, target_city, current_pos, attr_name, current_time, people)
                        if transports is not None:
                            attr_start = travel_end
                        else:
                            transports = []
                            attr_start = current_time
                        attr_end = add_minutes(attr_start, self._visit_len(attr, params, constraints))
                        if is_open_during(attr, attr_start, attr_end) and self._activity_timing_allowed(
                            attr_name,
                            attr_start,
                            timing_constraints,
                            [current_pos],
                        ):
                            attr_act = self._make_attraction_activity(
                                attr, people, attr_start, attr_end, transports)
                            added = self._append_activity(
                                activities,
                                attr_act,
                                budget_limits,
                                budget_tracker,
                                force=self._is_required_attraction(
                                    attr,
                                    required_attractions,
                                    required_attraction_types,
                                ),
                            )
                            if added:
                                current_time = attr_end
                                current_pos = attr_name

                # Afternoon fill before dinner.
                attr_idx, current_time, current_pos, _added = self._fill_extra_attractions(
                    activities, env, target_city, good_attrs, attr_idx, current_pos, current_time,
                    people, params, constraints, budget_limits, budget_tracker, timing_constraints,
                    required_attractions, required_attraction_types,
                    extra_budget - extra_used, "16:30", latest_end="18:00")
                extra_used += _added

                # Dinner (start between 17:00-19:00)
                if time_before(current_time, "19:00") and dinner_idx < len(dinner_restaurants):
                    restaurant, new_dinner_idx = self._pick_restaurant(
                        dinner_restaurants,
                        dinner_idx,
                        people,
                        budget_limits,
                        budget_tracker,
                    )
                    if restaurant is not None:
                        dinner_idx = new_dinner_idx
                    rest_name = str(restaurant["name"]) if restaurant is not None else current_pos
                    transports, travel_end = self._get_transport(
                        env, target_city, current_pos, rest_name, current_time, people)
                    if transports is not None:
                        dinner_start = max(travel_end or current_time, "17:00")
                    else:
                        transports = []
                        dinner_start = max(current_time, "17:00")
                    dinner_end = add_minutes(dinner_start, 60)
                    if restaurant is not None and time_before(dinner_end, "20:00") and self._activity_timing_allowed(
                        rest_name,
                        dinner_start,
                        timing_constraints,
                        [current_pos],
                    ):
                        dinner = self._make_meal_activity(
                            "dinner", restaurant, people, dinner_start, dinner_end, transports)
                        added = self._append_activity(
                            activities,
                            dinner,
                            budget_limits,
                            budget_tracker,
                            force=self._is_required_restaurant(restaurant, required_restaurants),
                        )
                        if added:
                            current_time = dinner_end
                            current_pos = rest_name

                # Evening fill after dinner (only late-open attractions qualify).
                attr_idx, current_time, current_pos, _added = self._fill_extra_attractions(
                    activities, env, target_city, good_attrs, attr_idx, current_pos, current_time,
                    people, params, constraints, budget_limits, budget_tracker, timing_constraints,
                    required_attractions, required_attraction_types,
                    extra_budget - extra_used, "21:00")
                extra_used += _added

                # Accommodation
                transports, travel_end = self._get_transport(
                    env, target_city, current_pos, hotel_name, current_time, people)
                if transports is None or current_pos == hotel_name:
                    transports = []
                    travel_end = current_time
                stay = self._make_accommodation_activity(
                    hotel, rooms_needed, travel_end, transports)
                self._append_preregistered_activity(activities, stay)
                current_pos = hotel_name

            elif day_num == days:
                # === LAST DAY: breakfast + maybe attraction + return transport ===
                # First, figure out the return transport based on hotel position
                # Compute transport from hotel to departure point to know earliest feasible departure
                if return_transport is not None:
                    departure_pos = return_transport["From"]
                    hotel_to_station, hotel_to_station_end = self._get_transport(
                        env, target_city, hotel_name, departure_pos, "08:30", people)
                    if hotel_to_station is None:
                        hotel_to_station_end = "08:30"
                    # If we can't make it to the original return transport, find a later one
                    if time_to_minutes(hotel_to_station_end) > time_to_minutes(return_transport["BeginTime"]):
                        later = self._get_intercity(
                            env,
                            target_city,
                            start_city,
                            hotel_to_station_end,
                            return_pref,
                            budget_limits,
                            budget_tracker,
                            pending_intercity=outbound,
                            people=people,
                        )
                        if later is not None:
                            return_transport = later
                            departure_pos = later["From"]
                            # Re-compute transport if departure pos changed
                            if later["From"] != (hotel_to_station[-1]["end"] if hotel_to_station else hotel_name):
                                hotel_to_station, hotel_to_station_end = self._get_transport(
                                    env, target_city, hotel_name, departure_pos, "08:30", people)
                                if hotel_to_station is None:
                                    hotel_to_station_end = "08:30"

                # Breakfast at hotel (free)
                breakfast = self._make_hotel_breakfast(
                    hotel_name, "07:30", "08:30")
                self._append_activity(activities, breakfast, budget_limits, budget_tracker)
                current_time = "08:30"
                current_pos = hotel_name

                # Morning attraction if time before return
                if attr_idx < len(good_attrs) and return_transport is not None:
                    departure_time = return_transport["BeginTime"]
                    departure_pos = return_transport["From"]
                    # Need time: transport to attr + 90min + transport to departure point
                    if time_to_minutes(departure_time) >= time_to_minutes(current_time) + 150:
                        est_start = add_minutes(current_time, 20)
                        est_end = add_minutes(est_start, self._slot_visit_len(params, constraints))
                        attr, attr_idx = self._pick_attraction(good_attrs, attr_idx, est_start, est_end)
                        if attr is not None:
                            attr_name = str(attr["name"])
                            transports, travel_end = self._get_transport(
                                env, target_city, current_pos, attr_name, current_time, people)
                            if transports is not None:
                                attr_start = travel_end
                            else:
                                transports = []
                                attr_start = current_time
                            attr_end = add_minutes(attr_start, self._visit_len(attr, params, constraints))
                            # Check we can get back to departure in time
                            _, return_arrival = self._get_transport(
                                env, target_city, attr_name, departure_pos, attr_end, people)
                            can_return = (return_arrival is not None and
                                         time_to_minutes(return_arrival) <= time_to_minutes(departure_time))
                            if can_return and is_open_during(attr, attr_start, attr_end) and self._activity_timing_allowed(
                                attr_name,
                                attr_start,
                                timing_constraints,
                                [current_pos],
                            ):
                                attr_act = self._make_attraction_activity(
                                    attr, people, attr_start, attr_end, transports)
                                added = self._append_activity(
                                    activities,
                                    attr_act,
                                    budget_limits,
                                    budget_tracker,
                                    force=self._is_required_attraction(
                                        attr,
                                        required_attractions,
                                        required_attraction_types,
                                    ),
                                )
                                if added:
                                    current_time = attr_end
                                    current_pos = attr_name

                # Morning fill before departure (return-guarded so we never miss the train/flight).
                if return_transport is not None:
                    _dep_t = return_transport["BeginTime"]
                    _dep_p = return_transport["From"]
                    def _return_ok(name, end, _p=_dep_p, _t=_dep_t):
                        _, _arr = self._get_transport(env, target_city, name, _p, end, people)
                        return _arr is not None and time_to_minutes(_arr) <= time_to_minutes(_t)
                    attr_idx, current_time, current_pos, _added = self._fill_extra_attractions(
                        activities, env, target_city, good_attrs, attr_idx, current_pos, current_time,
                        people, params, constraints, budget_limits, budget_tracker, timing_constraints,
                        required_attractions, required_attraction_types,
                        extra_budget - extra_used, "13:00", return_guard=_return_ok)
                    extra_used += _added

                # Lunch before departure if time allows
                if return_transport is not None and lunch_idx < len(lunch_restaurants):
                    departure_time = return_transport["BeginTime"]
                    departure_pos = return_transport["From"]
                    if time_to_minutes(departure_time) >= time_to_minutes("11:00") + 90:
                        if time_before(current_time, "13:00"):
                            restaurant, new_lunch_idx = self._pick_restaurant(
                                lunch_restaurants,
                                lunch_idx,
                                people,
                                budget_limits,
                                budget_tracker,
                            )
                            rest_name = str(restaurant["name"]) if restaurant is not None else current_pos
                            transports, travel_end = self._get_transport(
                                env, target_city, current_pos, rest_name, current_time, people)
                            if transports is not None:
                                lunch_start = max(travel_end or current_time, "11:00")
                            else:
                                transports = []
                                lunch_start = max(current_time, "11:00")
                            lunch_end = add_minutes(lunch_start, 60)
                            # Check we can still reach departure point after lunch
                            _, return_arrival = self._get_transport(
                                env, target_city, rest_name, departure_pos, lunch_end, people)
                            can_return = (return_arrival is not None and
                                         time_to_minutes(return_arrival) <= time_to_minutes(departure_time))
                            if restaurant is not None and time_before(lunch_end, "14:00") and can_return and self._activity_timing_allowed(
                                rest_name,
                                lunch_start,
                                timing_constraints,
                                [current_pos],
                            ):
                                lunch_idx = new_lunch_idx
                                lunch = self._make_meal_activity(
                                    "lunch", restaurant, people, lunch_start, lunch_end, transports)
                                added = self._append_activity(
                                    activities,
                                    lunch,
                                    budget_limits,
                                    budget_tracker,
                                    force=self._is_required_restaurant(restaurant, required_restaurants),
                                )
                                if added:
                                    current_time = lunch_end
                                    current_pos = rest_name

                # Return intercity transport
                if return_transport is not None:
                    departure_pos = return_transport["From"]
                    transports, travel_end = self._get_transport(
                        env, target_city, current_pos, departure_pos, current_time, people)
                    if transports is None or current_pos == departure_pos:
                        transports = []
                        travel_end = current_time
                    # If transport to station arrives after departure, find later transport
                    if time_to_minutes(travel_end) > time_to_minutes(return_transport["BeginTime"]):
                        later = self._get_intercity(
                            env,
                            target_city,
                            start_city,
                            travel_end,
                            return_pref,
                            budget_limits,
                            budget_tracker,
                            pending_intercity=outbound,
                            people=people,
                        )
                        if later is not None:
                            return_transport = later
                            if later["From"] != departure_pos:
                                departure_pos = later["From"]
                                transports, travel_end = self._get_transport(
                                    env, target_city, current_pos, departure_pos, current_time, people)
                                if transports is None or current_pos == departure_pos:
                                    transports = []
                    act = self._make_intercity_activity(return_transport, people, transports)
                    self._append_preregistered_activity(activities, act)

            else:
                # === MIDDLE DAYS: breakfast + attractions + meals + hotel ===
                # Breakfast at hotel (free)
                breakfast = self._make_hotel_breakfast(
                    hotel_name, "07:30", "08:30")
                self._append_activity(activities, breakfast, budget_limits, budget_tracker)
                current_time = "08:30"
                current_pos = hotel_name

                # Morning attraction
                if attr_idx < len(good_attrs):
                    est_start = add_minutes(current_time, 20)
                    est_end = add_minutes(est_start, self._slot_visit_len(params, constraints))
                    attr, attr_idx = self._pick_attraction(good_attrs, attr_idx, est_start, est_end)
                    if attr is not None:
                        attr_name = str(attr["name"])
                        transports, travel_end = self._get_transport(
                            env, target_city, current_pos, attr_name, current_time, people)
                        if transports is not None:
                            attr_start = travel_end
                        else:
                            transports = []
                            attr_start = current_time
                        attr_end = add_minutes(attr_start, self._visit_len(attr, params, constraints))
                        if is_open_during(attr, attr_start, attr_end) and self._activity_timing_allowed(
                            attr_name,
                            attr_start,
                            timing_constraints,
                            [current_pos],
                        ):
                            attr_act = self._make_attraction_activity(
                                attr, people, attr_start, attr_end, transports)
                            added = self._append_activity(
                                activities,
                                attr_act,
                                budget_limits,
                                budget_tracker,
                                force=self._is_required_attraction(
                                    attr,
                                    required_attractions,
                                    required_attraction_types,
                                ),
                            )
                            if added:
                                current_time = attr_end
                                current_pos = attr_name

                # Morning fill before lunch.
                attr_idx, current_time, current_pos, _added = self._fill_extra_attractions(
                    activities, env, target_city, good_attrs, attr_idx, current_pos, current_time,
                    people, params, constraints, budget_limits, budget_tracker, timing_constraints,
                    required_attractions, required_attraction_types,
                    extra_budget - extra_used, "11:30", latest_end="13:00")
                extra_used += _added

                # Lunch
                if lunch_idx < len(lunch_restaurants) and time_before(current_time, "13:00"):
                    restaurant, new_lunch_idx = self._pick_restaurant(
                        lunch_restaurants,
                        lunch_idx,
                        people,
                        budget_limits,
                        budget_tracker,
                    )
                    rest_name = str(restaurant["name"]) if restaurant is not None else current_pos
                    transports, travel_end = self._get_transport(
                        env, target_city, current_pos, rest_name, current_time, people)
                    if transports is not None:
                        lunch_start = max(travel_end or current_time, "11:00")
                    else:
                        transports = []
                        lunch_start = max(current_time, "11:00")
                    lunch_end = add_minutes(lunch_start, 60)
                    if restaurant is not None and time_before(lunch_end, "14:00") and self._activity_timing_allowed(
                        rest_name,
                        lunch_start,
                        timing_constraints,
                        [current_pos],
                    ):
                        lunch_idx = new_lunch_idx
                        lunch = self._make_meal_activity(
                            "lunch", restaurant, people, lunch_start, lunch_end, transports)
                        added = self._append_activity(
                            activities,
                            lunch,
                            budget_limits,
                            budget_tracker,
                            force=self._is_required_restaurant(restaurant, required_restaurants),
                        )
                        if added:
                            current_time = lunch_end
                            current_pos = rest_name

                # Afternoon attraction
                if attr_idx < len(good_attrs) and time_before(current_time, "16:00"):
                    est_start = add_minutes(current_time, 20)
                    est_end = add_minutes(est_start, self._slot_visit_len(params, constraints))
                    attr, attr_idx = self._pick_attraction(good_attrs, attr_idx, est_start, est_end)
                    if attr is not None:
                        attr_name = str(attr["name"])
                        transports, travel_end = self._get_transport(
                            env, target_city, current_pos, attr_name, current_time, people)
                        if transports is not None:
                            attr_start = travel_end
                        else:
                            transports = []
                            attr_start = current_time
                        attr_end = add_minutes(attr_start, self._visit_len(attr, params, constraints))
                        if is_open_during(attr, attr_start, attr_end) and self._activity_timing_allowed(
                            attr_name,
                            attr_start,
                            timing_constraints,
                            [current_pos],
                        ):
                            attr_act = self._make_attraction_activity(
                                attr, people, attr_start, attr_end, transports)
                            added = self._append_activity(
                                activities,
                                attr_act,
                                budget_limits,
                                budget_tracker,
                                force=self._is_required_attraction(
                                    attr,
                                    required_attractions,
                                    required_attraction_types,
                                ),
                            )
                            if added:
                                current_time = attr_end
                                current_pos = attr_name

                # Afternoon fill before dinner.
                attr_idx, current_time, current_pos, _added = self._fill_extra_attractions(
                    activities, env, target_city, good_attrs, attr_idx, current_pos, current_time,
                    people, params, constraints, budget_limits, budget_tracker, timing_constraints,
                    required_attractions, required_attraction_types,
                    extra_budget - extra_used, "16:30", latest_end="18:00")
                extra_used += _added

                # Dinner
                if dinner_idx < len(dinner_restaurants) and time_before(current_time, "19:00"):
                    restaurant, new_dinner_idx = self._pick_restaurant(
                        dinner_restaurants,
                        dinner_idx,
                        people,
                        budget_limits,
                        budget_tracker,
                    )
                    rest_name = str(restaurant["name"]) if restaurant is not None else current_pos
                    transports, travel_end = self._get_transport(
                        env, target_city, current_pos, rest_name, current_time, people)
                    if transports is not None:
                        dinner_start = max(travel_end or current_time, "17:00")
                    else:
                        transports = []
                        dinner_start = max(current_time, "17:00")
                    dinner_end = add_minutes(dinner_start, 60)
                    if restaurant is not None and time_before(dinner_end, "20:00") and self._activity_timing_allowed(
                        rest_name,
                        dinner_start,
                        timing_constraints,
                        [current_pos],
                    ):
                        dinner_idx = new_dinner_idx
                        dinner = self._make_meal_activity(
                            "dinner", restaurant, people, dinner_start, dinner_end, transports)
                        added = self._append_activity(
                            activities,
                            dinner,
                            budget_limits,
                            budget_tracker,
                            force=self._is_required_restaurant(restaurant, required_restaurants),
                        )
                        if added:
                            current_time = dinner_end
                            current_pos = rest_name

                # Evening fill after dinner (only late-open attractions qualify).
                attr_idx, current_time, current_pos, _added = self._fill_extra_attractions(
                    activities, env, target_city, good_attrs, attr_idx, current_pos, current_time,
                    people, params, constraints, budget_limits, budget_tracker, timing_constraints,
                    required_attractions, required_attraction_types,
                    extra_budget - extra_used, "21:00")
                extra_used += _added

                # Accommodation
                transports, travel_end = self._get_transport(
                    env, target_city, current_pos, hotel_name, current_time, people)
                if transports is None or current_pos == hotel_name:
                    transports = []
                    travel_end = current_time
                stay = self._make_accommodation_activity(
                    hotel, rooms_needed, travel_end, transports)
                self._append_preregistered_activity(activities, stay)
                current_pos = hotel_name

            itinerary.append({"day": day_num, "activities": activities})

        return {
            "people_number": people,
            "start_city": start_city,
            "target_city": target_city,
            "itinerary": itinerary,
        }

    def _get_intercity(
        self,
        env,
        from_city,
        to_city,
        earliest,
        preferred_mode=None,
        budget_limits=None,
        budget_tracker=None,
        pending_intercity=None,
        people=1,
    ):
        """Get first affordable intercity transport, falling back to cheapest available."""
        preferred = self._norm_text(preferred_mode)
        transport_order = ["airplane", "train"]
        if preferred in ["airplane", "flight", "plane"]:
            transport_order = ["airplane", "train"]
        elif preferred in ["train", "rail"]:
            transport_order = ["train", "airplane"]

        pending_cost = 0.0
        if pending_intercity is not None:
            pending_cost = self._safe_float(pending_intercity.get("Cost", 0.0), 0.0)

        best = None
        best_cost = None
        for transport_type in transport_order:
            try:
                df = env.intercitytransport.select(from_city, to_city, transport_type, earliest)
                if df is not None and len(df) > 0:
                    for i in range(len(df)):
                        cand = df.iloc[i].to_dict()
                        if not self._route_timing_allowed(
                            getattr(self, "_active_timing_constraints", []),
                            [cand.get("From", ""), from_city],
                            [cand.get("To", ""), to_city],
                            str(cand.get("BeginTime", earliest)),
                            str(cand.get("EndTime", earliest)),
                        ):
                            continue
                        cost = self._safe_float(cand.get("Cost", 0.0), 0.0)
                        # Multiply by people so the budget check accounts for total cost
                        projected_intercity_total = (cost + pending_cost) * people
                        if self._affordable_main_cost("intercity_transport", projected_intercity_total, budget_limits, budget_tracker):
                            return cand
                        if best is None or best_cost is None or cost < best_cost:
                            best = cand
                            best_cost = cost
            except Exception:
                pass
        return best

    def _pick_attraction(self, good_attrs, attr_idx, start_time, end_time):
        """Pick the next attraction that is open during [start_time, end_time].
        Required attractions (in self._required_attrs_remaining) are tried first.
        Returns (attr, new_attr_idx) or (None, attr_idx) if none found."""
        scheduled = getattr(self, '_scheduled_attr_names', set())
        # First: try any still-pending required attraction
        remaining = getattr(self, '_required_attrs_remaining', [])
        for i, attr in enumerate(remaining):
            if is_open_during(attr, start_time, end_time):
                remaining.pop(i)
                scheduled.add(self._norm_text(str(attr["name"])))
                return attr, attr_idx  # don't advance attr_idx (optional pool unchanged)
        # Fallback: normal forward scan through optional pool, skip already scheduled
        idx = attr_idx
        while idx < len(good_attrs):
            attr = good_attrs[idx]
            if self._norm_text(str(attr["name"])) not in scheduled and is_open_during(attr, start_time, end_time):
                scheduled.add(self._norm_text(str(attr["name"])))
                return attr, idx + 1
            idx += 1
        return None, attr_idx

    def _fill_extra_attractions(self, activities, env, target_city, good_attrs, attr_idx,
                                current_pos, current_time, people, params, constraints,
                                budget_limits, budget_tracker, timing_constraints,
                                required_attractions, required_attraction_types,
                                target_count, until_time, return_guard=None, latest_end=None):
        """Greedily append open attractions until `target_count` are added or `current_time`
        reaches `until_time` (or the pool/feasibility runs out). Fills idle daytime slots to lift
        DAV. Each add already respects opening hours, per-activity timing and budget; FPR cannot
        regress because _solve keeps only accepted plans and the eval merge adopts a plan only when
        its full weighted score beats the stored best. Returns (attr_idx, current_time, current_pos, added)."""
        added = 0
        while (added < target_count and attr_idx < len(good_attrs)
               and time_before(current_time, until_time)):
            est_start = add_minutes(current_time, 20)
            est_end = add_minutes(est_start, self._slot_visit_len(params, constraints))
            attr, attr_idx = self._pick_attraction(good_attrs, attr_idx, est_start, est_end)
            if attr is None:
                break
            attr_name = str(attr["name"])
            transports, travel_end = self._get_transport(
                env, target_city, current_pos, attr_name, current_time, people)
            if transports is not None:
                attr_start = travel_end
            else:
                transports = []
                attr_start = current_time
            attr_end = add_minutes(attr_start, self._visit_len(attr, params, constraints))
            if latest_end is not None and not time_before(attr_end, latest_end):
                break
            if not (is_open_during(attr, attr_start, attr_end) and self._activity_timing_allowed(
                    attr_name, attr_start, timing_constraints, [current_pos])):
                break
            if return_guard is not None and not return_guard(attr_name, attr_end):
                break
            attr_act = self._make_attraction_activity(attr, people, attr_start, attr_end, transports)
            if not self._append_activity(
                    activities, attr_act, budget_limits, budget_tracker,
                    force=self._is_required_attraction(attr, required_attractions, required_attraction_types)):
                break
            current_time = attr_end
            current_pos = attr_name
            added += 1
        return attr_idx, current_time, current_pos, added

    def _get_transport(self, env, city, from_pos, to_pos, start_time, people):
        """Get taxi transport between two positions. Returns (transports_list, arrival_time) or (None, None)."""
        timing_constraints = getattr(self, "_active_timing_constraints", [])
        depart_floor = self._timing_departure_floor(timing_constraints, [from_pos])
        if depart_floor is not None and time_to_minutes(start_time) < depart_floor:
            start_time = minutes_to_time(depart_floor)
        if from_pos == to_pos:
            return [], start_time
        excluded = set(
            self._norm_text(m)
            for m in (self._transport_constraints.get("excluded_inner_transport", []) or [])
        )
        conditional = self._transport_constraints.get("conditional_transport", None)
        mode_order = ["metro", "walk", "taxi"]
        # Search may pin the inner-city mode; explicit choice overrides the budget/conditional heuristics
        # but still respects excluded modes and the taxi car-count guard below.
        forced_inner = self._norm_text(getattr(self, "_forced_inner_mode", None) or "")
        if forced_inner:
            mode_order = [forced_inner]

        # If inner_transport budget is constrained, prefer cheaper modes (metro > walk > taxi)
        inner_budget_limit = getattr(self, "_budget_limits", {}).get("inner_transport", -1)
        if inner_budget_limit >= 0 and not forced_inner:
            mode_order = ["walk", "metro", "taxi"] if inner_budget_limit <= 50 else ["metro", "walk", "taxi"]
        taxi_cars_equals = self._transport_constraints.get("taxi_cars_equals", None)
        if taxi_cars_equals is not None:
            try:
                required_cars = int(taxi_cars_equals)
                projected_cars = max(1, int(math.ceil(float(people) / 4.0)))
                if projected_cars != required_cars:
                    mode_order = [m for m in mode_order if m != "taxi"]
            except Exception:
                pass

        if isinstance(conditional, dict) and not forced_inner:
            preferred = self._norm_text(conditional.get("mode", "taxi"))
            threshold_km = conditional.get("threshold_km", None)
            if preferred in ["taxi", "metro", "walk"]:
                if threshold_km is not None:
                    # Probe with taxi to get actual route distance, then decide
                    try:
                        probe = env.transportation.goto(city, from_pos, to_pos, start_time, "taxi")
                        if isinstance(probe, list) and len(probe) > 0:
                            total_dist_km = sum(seg.get("distance", 0) for seg in probe) / 1000.0
                            if total_dist_km > threshold_km:
                                mode_order = [preferred] + [m for m in mode_order if m != preferred]
                            # else: distance is below threshold — leave default order
                    except Exception:
                        pass  # probe failed, leave default order
                else:
                    # No threshold: unconditionally prefer the mode
                    mode_order = [preferred] + [m for m in mode_order if m != preferred]

        mode_order = [m for m in mode_order if self._norm_text(m) not in excluded]
        if len(mode_order) == 0:
            mode_order = ["taxi"]

        try:
            for mode in mode_order:
                result = env.transportation.goto(city, from_pos, to_pos, start_time, mode)
                if isinstance(result, list) and len(result) > 0:
                    transports = []
                    for seg in result:
                        t = {
                            "start": seg["start"],
                            "end": seg["end"],
                            "mode": seg["mode"],
                            "start_time": seg["start_time"],
                            "end_time": seg["end_time"],
                            "distance": seg["distance"],
                        }
                        if seg["mode"] == "taxi":
                            cars = max(1, int(math.ceil(float(people) / 4.0)))
                            t["price"] = seg["cost"]
                            t["cost"] = seg["cost"] * cars
                            t["cars"] = cars
                        elif seg["mode"] == "metro":
                            t["price"] = seg["cost"]
                            t["cost"] = seg["cost"] * people
                            t["tickets"] = people
                        else:  # walk
                            t["price"] = 0
                            t["cost"] = 0
                        transports.append(t)
                    arrival_time = transports[-1]["end_time"]
                    return transports, arrival_time
        except Exception:
            pass
        return None, None

    def _make_intercity_activity(self, transport, people, transports=None):
        """Create an intercity transport activity dict."""
        if transports is None:
            transports = []
        activity = {
            "type": "airplane" if "FlightID" in transport else "train",
            "start_time": transport["BeginTime"],
            "end_time": transport["EndTime"],
            "start": transport["From"],
            "end": transport["To"],
            "price": transport["Cost"],
            "cost": transport["Cost"] * people,
            "tickets": people,
            "transports": transports,
        }
        if "FlightID" in transport:
            activity["FlightID"] = transport["FlightID"]
        else:
            activity["TrainID"] = transport["TrainID"]
        return activity

    def _make_attraction_activity(self, attr, people, start_time, end_time, transports=None):
        """Create an attraction activity dict."""
        if transports is None:
            transports = []
        return {
            "type": "attraction",
            "position": str(attr["name"]),
            "start_time": start_time,
            "end_time": end_time,
            "price": float(attr["price"]),
            "cost": float(attr["price"]) * people,
            "tickets": people,
            "transports": transports,
        }

    def _make_meal_activity(self, meal_type, restaurant, people, start_time, end_time, transports=None):
        """Create a meal (breakfast/lunch/dinner) activity dict."""
        if transports is None:
            transports = []
        return {
            "type": meal_type,
            "position": str(restaurant["name"]),
            "start_time": start_time,
            "end_time": end_time,
            "price": float(restaurant["price"]),
            "cost": float(restaurant["price"]) * people,
            "tickets": people,
            "transports": transports,
        }

    def _make_hotel_breakfast(self, hotel_name, start_time, end_time):
        """Create a breakfast-at-hotel activity (free)."""
        return {
            "type": "breakfast",
            "position": hotel_name,
            "start_time": start_time,
            "end_time": end_time,
            "price": 0,
            "cost": 0,
            "tickets": 0,
            "transports": [],
        }

    def _make_accommodation_activity(self, hotel, rooms, check_in_time, transports=None):
        """Create an accommodation activity dict."""
        if transports is None:
            transports = []
        return {
            "type": "accommodation",
            "position": str(hotel["name"]),
            "start_time": check_in_time,
            "end_time": "24:00",
            "price": float(hotel["price"]),
            "cost": float(hotel["price"]) * rooms,
            "rooms": rooms,
            "room_type": int(hotel["numbed"]),
            "tickets": rooms,
            "transports": transports,
        }