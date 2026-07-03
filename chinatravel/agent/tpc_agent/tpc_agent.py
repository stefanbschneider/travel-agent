import sys
import os
import time
import math
import json
from difflib import SequenceMatcher
from copy import deepcopy

from agent.base import BaseAgent
from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py
import random
import parse_constraints
from agent.tpc_agent.parsed_verifier import evaluate_parsed_constraints
from agent.tpc_agent.solver_constraints import solver_constraint_variants
import contextlib
import io
from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
from chinatravel.evaluation.commonsense_constraint import evaluate_commonsense_constraints
from chinatravel.symbol_verification.concept_func import normalize_poi_name

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
        hard_logic_py = query.get("hard_logic_py", []) or []
        target_city = query.get("target_city", "")

        def base_check(plan):
            if self.use_oracle:
                if not hard_logic_py:
                    return 0, 0
                try:
                    res = evaluate_constraints_py(hard_logic_py, plan, verbose=False)
                except Exception:
                    return 0, len(hard_logic_py)
                return sum(1 for r in res if bool(r)), len(res)

            try:
                res = evaluate_parsed_constraints(constraints, plan, target_city)
            except Exception:
                return 0, 0
            return sum(1 for r in res if r), len(res)

        def check(plan):
            passed, total = base_check(plan)
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

    def _is_intercity_activity(self, activity):
        return isinstance(activity, dict) and activity.get("type") in ("airplane", "train")

    def _sanitize_plan_for_grounding(self, plan, query):
        """Drop accidental mid-itinerary intercity placeholders.

        Hardened evaluator grounding allows train/airplane only as the global first/last
        activity. If a candidate contains middle intercity markers, remove them and, when
        possible, reconnect the following POI via a legal inner-city transport edge.
        """
        if not isinstance(plan, dict):
            return plan
        itinerary = plan.get("itinerary", []) or []
        if not isinstance(itinerary, list) or len(itinerary) == 0:
            return plan

        def flatten_refs(p):
            refs = []
            for day_idx, day in enumerate(p.get("itinerary", []) or []):
                activities = (day or {}).get("activities", [])
                if not isinstance(activities, list):
                    continue
                for act_idx, activity in enumerate(activities):
                    refs.append((day_idx, act_idx, activity))
            return refs

        refs = flatten_refs(plan)
        if len(refs) <= 2:
            return plan
        if not any(
            self._is_intercity_activity(activity) and global_idx not in (0, len(refs) - 1)
            for global_idx, (_, _, activity) in enumerate(refs)
        ):
            return plan

        cleaned = deepcopy(plan)
        city = str(query.get("target_city", ""))
        people = int(query.get("people_number", 1) or 1)

        # Remove one illegal marker at a time so indices stay valid.
        while True:
            refs = flatten_refs(cleaned)
            illegal_idx = None
            for global_idx, (_day_idx, _act_idx, activity) in enumerate(refs):
                if self._is_intercity_activity(activity) and global_idx not in (0, len(refs) - 1):
                    illegal_idx = global_idx
                    break
            if illegal_idx is None:
                break

            day_idx, act_idx, _activity = refs[illegal_idx]
            prev_ref = refs[illegal_idx - 1] if illegal_idx > 0 else None
            next_ref = refs[illegal_idx + 1] if illegal_idx + 1 < len(refs) else None

            day_activities = cleaned["itinerary"][day_idx].get("activities", [])
            if not isinstance(day_activities, list) or act_idx >= len(day_activities):
                break
            del day_activities[act_idx]

            if prev_ref is None or next_ref is None:
                continue
            prev_day, prev_idx, _ = prev_ref
            next_day, next_idx, _ = next_ref
            if next_day == day_idx and next_idx > act_idx:
                next_idx -= 1
            try:
                prev_act = cleaned["itinerary"][prev_day]["activities"][prev_idx]
                next_act = cleaned["itinerary"][next_day]["activities"][next_idx]
            except Exception:
                continue
            if not isinstance(next_act, dict) or self._is_intercity_activity(next_act):
                continue

            from_pos = self._activity_end_position(prev_act)
            to_pos = self._activity_start_position(next_act)
            depart_time = str(prev_act.get("end_time", ""))
            if not (city and from_pos and to_pos and depart_time):
                continue
            try:
                transports, arrival = self._get_transport(
                    self.env, city, from_pos, to_pos, depart_time, people
                )
            except Exception:
                transports, arrival = None, None
            if not transports:
                continue
            next_start = str(next_act.get("start_time", ""))
            if next_start and (not arrival or not time_before(arrival, next_start)):
                continue
            next_act["transports"] = transports

        return cleaned

    def _norm_text(self, value):
        if value is None:
            return ""
        try:
            value = normalize_poi_name(str(value))
        except Exception:
            pass
        return str(value).strip().lower()

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
        return solver_constraint_variants(query, raw, use_oracle=self.use_oracle)

    def _collect_constraints(self, query):
        variants = self._constraint_variants(query)
        if len(variants) == 0:
            return {}
        return variants[0]


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
        longest dwell any constraint demands (clamped to 240), at least 60 minutes."""
        longest = 0
        for d in constraints.get("stay_duration", []) or []:
            if isinstance(d, dict):
                try:
                    longest = max(longest, int(d.get("min_minutes", 0)))
                except (TypeError, ValueError):
                    pass
        return min(240, max(int(params.get("visit_minutes", 90)), longest, 60))

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

    def _visit_minutes_candidates(self, constraints):
        """Return dwell baselines explored by search (small values improve packing density).

        Candidates remain bounded by named minimum-dwell constraints so required visits are
        never shortened below what the query asks for.
        """
        longest = 0
        for d in (constraints or {}).get("stay_duration", []) or []:
            if isinstance(d, dict):
                try:
                    longest = max(longest, int(d.get("min_minutes", 0)))
                except (TypeError, ValueError):
                    pass
        base = [60, 75, 90, 105]
        floor = min(240, max(60, longest))
        values = sorted(set(min(240, max(v, floor)) for v in base))
        return values if values else [90]

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

    def _default_preference_components(self, plan):
        attrs, meals = self._activity_counts(plan)
        days = max(1, len(plan.get("itinerary", []) or []))
        dav = min(1.0, attrs / (4.0 * days))
        ddr = min(1.0, meals / (3.0 * days))
        transit_total = 0
        transit_count = 0
        for day in plan.get("itinerary", []) or []:
            for activity in day.get("activities", []) or []:
                transports = activity.get("transports", []) or []
                if transports:
                    transit_total += self._inner_activity_minutes(activity)
                    transit_count += 1
        average_transit = transit_total / transit_count if transit_count > 0 else -1
        att = max(0.0, min(1.0, (-1.0 / 105.0) * average_transit + 8.0 / 7.0))
        return dav, att, ddr

    def _eval_proxy(self, plan):
        dav, att, ddr = self._default_preference_components(plan)
        return 5.0 * dav + 5.0 * att + 5.0 * ddr

    def _accepted_eval_key(self, plan):
        """Rank fully valid plans by the default leaderboard preference components.

        Once a plan passes every hard/env check, prefer the strongest DAV/ATT/DDR combination
        instead of reusing the generic search key that still prioritizes raw passed-count.
        """
        dav, att, ddr = self._default_preference_components(plan)
        attrs, meals = self._activity_counts(plan)
        return (dav + att + ddr, dav + ddr, attrs + meals, -self._plan_total_cost(plan))

    def _repair_params(self, constraints):
        """Deterministic param priors derived from which constraints are present, tried before
        random restarts so single-signal queries converge fast."""
        candidates = []
        for vm in self._visit_minutes_candidates(constraints):
            candidates.append({"visit_minutes": vm})
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

    def _random_params(self, rng, constraints):
        params = {
            "attr_offset": rng.randint(0, 12),
            "hotel_index": rng.randint(0, 4),
            "attr_per_day": rng.choice([2, 3, 4]),
            "visit_minutes": rng.choice(self._visit_minutes_candidates(constraints)),
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
        keeping the best accepted plan found within budget; finally pack it."""
        variants = self._constraint_variants(query) or [None]
        rng = random.Random(hash((str(query.get("uid", "")), str(self.seed_salt))) & 0xFFFFFFFF)
        init_key = (-1, float("-inf"), float("-inf"))
        accepted_init_key = (float("-inf"), float("-inf"), float("-inf"), float("-inf"))
        best = {"plan": None, "key": init_key, "constraints": None, "check": None, "params": None}
        best_accepted = {
            "plan": None,
            "key": accepted_init_key,
            "constraints": None,
            "check": None,
            "params": None,
        }

        def consider(plan, constraints, check, params):
            plan = self._sanitize_plan_for_grounding(plan, query)
            try:
                passed, total = check(plan)
            except Exception:
                passed, total = 0, 0
            search_key = (passed, self._eval_proxy(plan), -self._plan_total_cost(plan))
            if best["plan"] is None or search_key > best["key"]:
                best.update(plan=plan, key=search_key, constraints=constraints, check=check, params=params)
            accepted = self._accepted(passed, total)
            if accepted:
                accepted_key = self._accepted_eval_key(plan)
                if best_accepted["plan"] is None or accepted_key > best_accepted["key"]:
                    best_accepted.update(
                        plan=plan,
                        key=accepted_key,
                        constraints=constraints,
                        check=check,
                        params=params,
                    )
            return accepted

        def out_of_budget():
            return time.time() - self.start_clock > self.solve_budget_sec

        restarts = 0
        for variant in variants:
            if out_of_budget():
                break
            constraints = deepcopy(variant or {})
            check = self._make_checker(query, constraints)
            accepted_base = False
            try:
                accepted_base = consider(self._build_plan(query, constraints=constraints), constraints, check, {})
            except Exception:
                import traceback
                traceback.print_exc()

            run_cp_after_pass = os.environ.get("TPC_CP_AFTER_PASS", "1") != "0"
            run_cp = (
                os.environ.get("TPC_USE_CP_SOLVER", "1") != "0"
                and not out_of_budget()
                and (os.environ.get("TPC_CP_FORCE") == "1" or run_cp_after_pass or not accepted_base)
            )
            if run_cp:
                try:
                    from agent.tpc_agent.cp_solver import solve_with_cp_sat

                    elapsed = time.time() - self.start_clock
                    remaining = max(1.0, self.solve_budget_sec - elapsed)
                    default_limit = min(30.0, remaining / 2.0)
                    cp_limit = float(os.environ.get("TPC_CP_TIME_LIMIT_SEC", str(default_limit)))
                    cp_limit = max(1.0, min(cp_limit, remaining))
                    cp_plan = solve_with_cp_sat(
                        self,
                        query,
                        constraints,
                        check,
                        cp_limit,
                        self._visit_minutes_candidates(constraints),
                    )
                    if cp_plan is not None:
                        consider(cp_plan, constraints, check, {"solver": "cp_sat"})
                except Exception:
                    pass

            for params in self._repair_params(constraints):
                if out_of_budget():
                    break
                try:
                    consider(self._build_plan(query, constraints=constraints, params=params), constraints, check, params)
                except Exception:
                    continue

            while restarts < self.max_restarts and not out_of_budget():
                restarts += 1
                params = self._random_params(rng, constraints)
                try:
                    consider(self._build_plan(query, constraints=constraints, params=params), constraints, check, params)
                except Exception:
                    continue

        chosen = best_accepted if best_accepted["plan"] is not None else best

        if chosen["plan"] is not None and chosen["check"] is not None:
            packed = self._pack_plan(chosen["plan"], query, chosen["constraints"], chosen["check"], chosen["params"])
            if packed is not None:
                chosen["plan"] = packed

        if chosen["plan"] is not None:
            return self._sanitize_plan_for_grounding(chosen["plan"], query)
        return self._sanitize_plan_for_grounding(self._build_plan(query), query)

    def _pack_plan(self, plan, query, constraints, check, base_params):
        """Add attractions/meals (attr_per_day 3 then 4) while acceptance still holds, to lift
        DAV/DDR. Never trades a hard pass for preference: gated locally by `check`."""
        plan = self._sanitize_plan_for_grounding(plan, query)
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
            cand = self._sanitize_plan_for_grounding(cand, query)
            if not self._accepted(*check(cand)):
                continue
            c_attrs, c_meals = self._activity_counts(cand)
            if (c_attrs + c_meals) > (best_attrs + best_meals):
                best_plan = cand
                best_attrs, best_meals = c_attrs, c_meals
        dense = self._densify_plan(best_plan, query, constraints, check)
        return self._sanitize_plan_for_grounding(dense, query)

    def _activity_start_position(self, activity):
        if activity.get("type") in ("airplane", "train"):
            return str(activity.get("start", "") or activity.get("From", ""))
        return str(activity.get("position", "") or activity.get("start", ""))

    def _activity_end_position(self, activity):
        if activity.get("type") in ("airplane", "train"):
            return str(activity.get("end", "") or activity.get("To", ""))
        return str(activity.get("position", "") or activity.get("end", ""))

    def _poi_open_bounds(self, poi):
        open_min = poi.get("open_min", None)
        close_min = poi.get("close_min", None)
        if open_min is None:
            try:
                open_min = time_to_minutes(str(poi.get("opentime", "00:00")))
            except Exception:
                open_min = 0
        if close_min is None:
            close_raw = str(poi.get("endtime", "24:00"))
            try:
                close_min = 24 * 60 if close_raw == "24:00" else time_to_minutes(close_raw)
            except Exception:
                close_min = 24 * 60
        if close_min <= open_min:
            close_min += 24 * 60
        return int(open_min), int(close_min)

    def _densify_dwell_minutes(self, poi, kind):
        if kind != "attraction":
            return int(os.environ.get("TPC_DENSIFY_MEAL_DWELL", "60"))
        # Attraction visit length used when packing idle gaps. The verifier enforces no
        # minimum duration (only open-hours containment + positive duration), so a shorter
        # dwell lets more attractions fit tight gaps and lifts DAV; default is the
        # compute-node smoke/full-score winner.
        return int(os.environ.get("TPC_DENSIFY_ATTR_DWELL", "60"))

    def _inner_activity_minutes(self, activity):
        total = 0
        for leg in activity.get("transports", []) or []:
            try:
                total += time_to_minutes(str(leg["end_time"])) - time_to_minutes(str(leg["start_time"]))
            except Exception:
                continue
        return total

    def _haversine_km(self, a, b):
        try:
            lat1 = math.radians(float(a["lat"]))
            lon1 = math.radians(float(a["lon"]))
            lat2 = math.radians(float(b["lat"]))
            lon2 = math.radians(float(b["lon"]))
        except Exception:
            return float("inf")
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        s = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 6371.0 * 2.0 * math.atan2(math.sqrt(s), math.sqrt(max(0.0, 1.0 - s)))

    def _day_gaps(self, activities, win_open, win_close, min_minutes):
        gaps = []
        for idx in range(len(activities) - 1):
            try:
                prev_end = time_to_minutes(str(activities[idx].get("end_time", "")))
                next_start = time_to_minutes(str(activities[idx + 1].get("start_time", "")))
            except Exception:
                continue
            gap_start = max(prev_end, win_open)
            gap_end = min(next_start, win_close)
            if gap_end - gap_start >= min_minutes:
                gaps.append((idx, gap_start, gap_end))
        return gaps

    def _env_time_minutes(self, name, default):
        raw = str(os.environ.get(name, default))
        try:
            if ":" in raw:
                return time_to_minutes(raw)
            value = float(raw)
            if 0 <= value <= 24:
                return int(value * 60)
            return int(value)
        except Exception:
            return time_to_minutes(default)

    def _compress_activity_windows(self, plan, check):
        if os.environ.get("TPC_DENSIFY_COMPRESS_BEFORE", "0") != "1":
            return
        try:
            attr_dwell = max(1, int(os.environ.get(
                "TPC_DENSIFY_COMPRESS_ATTR_DWELL",
                os.environ.get("TPC_DENSIFY_ATTR_DWELL", "60"),
            )))
            meal_dwell = max(1, int(os.environ.get(
                "TPC_DENSIFY_COMPRESS_MEAL_DWELL",
                os.environ.get("TPC_DENSIFY_MEAL_DWELL", "60"),
            )))
        except Exception:
            return
        for day in plan.get("itinerary", []) or []:
            for activity in day.get("activities", []) or []:
                kind = activity.get("type")
                if kind == "attraction":
                    target = attr_dwell
                elif kind in ("breakfast", "lunch", "dinner"):
                    target = meal_dwell
                else:
                    continue
                try:
                    start_min = time_to_minutes(str(activity.get("start_time", "")))
                    end_min = time_to_minutes(str(activity.get("end_time", "")))
                except Exception:
                    continue
                new_end = start_min + target
                if new_end >= end_min:
                    continue
                old_end = activity.get("end_time")
                activity["end_time"] = minutes_to_time(new_end)
                try:
                    if self._accepted(*check(plan)):
                        continue
                except Exception:
                    pass
                activity["end_time"] = old_end

    def _find_hotel_for_day(self, plan, day_idx):
        itinerary = plan.get("itinerary", []) or []
        for scan in range(day_idx, -1, -1):
            activities = itinerary[scan].get("activities", []) or []
            for activity in reversed(activities):
                if activity.get("type") == "accommodation" and activity.get("position"):
                    return str(activity["position"])
        for scan in range(day_idx + 1, len(itinerary)):
            activities = itinerary[scan].get("activities", []) or []
            for activity in activities:
                if activity.get("type") == "accommodation" and activity.get("position"):
                    return str(activity["position"])
        return None

    def _insert_breakfast(self, plan, day_idx, hotel_name, check):
        activities = plan["itinerary"][day_idx].get("activities", [])
        if not activities:
            return False
        if day_idx == 0 and activities[0].get("type") in ("airplane", "train"):
            return False
        try:
            first_act = activities[0]
            first_transports = first_act.get("transports", []) or []
            if first_transports:
                anchor_raw = first_transports[0].get("start_time", "")
            else:
                anchor_raw = first_act.get("start_time", "00:00")
            end_min = min(
                time_to_minutes(str(anchor_raw)),
                self._env_time_minutes("TPC_DENSIFY_HOTEL_BREAKFAST_END", "08:30"),
            )
            dwell = max(1, int(os.environ.get(
                "TPC_DENSIFY_HOTEL_BREAKFAST_DWELL",
                os.environ.get("TPC_DENSIFY_MEAL_DWELL", "60"),
            )))
            start_min = end_min - dwell
            if start_min < time_to_minutes("06:00"):
                return False
        except Exception:
            return False
        before_key = self._accepted_eval_key(plan)
        activity = self._make_hotel_breakfast(hotel_name, minutes_to_time(start_min), minutes_to_time(end_min))
        activities.insert(0, activity)
        try:
            if self._accepted(*check(plan)) and self._accepted_eval_key(plan) > before_key:
                return True
        except Exception:
            pass
        del activities[0]
        return False

    def _insert_restaurant_breakfast(self, plan, day_idx, restaurants, city, people, check, used_restaurants=None):
        activities = plan["itinerary"][day_idx].get("activities", [])
        if not activities:
            return None
        window = (6 * 60, self._env_time_minutes("TPC_DENSIFY_BREAKFAST_WIN_CLOSE", "09:00"))
        meal_gap_min = max(1, int(os.environ.get("TPC_DENSIFY_MEAL_GAP_MIN", "60")))
        for restaurant in restaurants:
            r_name = self._norm_text(restaurant.get("name", ""))
            if not r_name or (used_restaurants is not None and r_name in used_restaurants):
                continue
            if self._insert_activity_before_first(plan, day_idx, restaurant, "breakfast", window, city, people, check):
                return r_name
            for prev_idx, _gap_start, _gap_end in self._day_gaps(activities, window[0], window[1], meal_gap_min):
                if self._insert_activity(plan, day_idx, prev_idx, restaurant, "breakfast", window, city, people, check):
                    return r_name
            if self._insert_activity_after_last(plan, day_idx, restaurant, "breakfast", window, city, people, check):
                return r_name
        return None

    def _insert_activity_before_first(self, plan, day_idx, poi, kind, window, city, people, check):
        activities = plan["itinerary"][day_idx].get("activities", [])
        if not activities:
            return False
        first_act = activities[0]
        next_pos = self._activity_start_position(first_act)
        poi_name = str(poi.get("name", ""))
        if not next_pos or not poi_name:
            return False

        prev_pos = None
        anchor_min = None
        transports_in = first_act.get("transports", []) or []
        if transports_in:
            first_leg = transports_in[0]
            prev_pos = str(first_leg.get("start", "") or "")
            try:
                anchor_min = time_to_minutes(str(first_leg.get("start_time", "")))
            except Exception:
                anchor_min = None
        if (not prev_pos or anchor_min is None) and day_idx > 0:
            hotel_name = self._find_hotel_for_day(plan, day_idx)
            if hotel_name:
                prev_pos = hotel_name
                anchor_min = time_to_minutes("08:30")
        if not prev_pos or anchor_min is None:
            return False

        try:
            next_start_min = time_to_minutes(str(first_act.get("start_time", "")))
        except Exception:
            return False
        if anchor_min >= next_start_min:
            return False

        win_open, win_close = window
        poi_open, poi_close = self._poi_open_bounds(poi)
        try:
            transports_to_poi, arrival = self._get_transport(
                self.env, city, prev_pos, poi_name, minutes_to_time(anchor_min), people)
        except Exception:
            return False
        if transports_to_poi is None or arrival is None:
            return False
        try:
            arrival_min = time_to_minutes(str(arrival))
        except Exception:
            return False

        start_min = max(arrival_min, win_open, poi_open)
        dwell = self._densify_dwell_minutes(poi, kind)
        end_min = start_min + dwell
        if end_min > min(win_close, poi_close):
            return False

        end_time = minutes_to_time(end_min)
        try:
            transports_to_next, next_arrival = self._get_transport(
                self.env, city, poi_name, next_pos, end_time, people)
        except Exception:
            return False
        if transports_to_next is None or next_arrival is None:
            return False
        try:
            if time_to_minutes(str(next_arrival)) > next_start_min:
                return False
        except Exception:
            return False

        start_time = minutes_to_time(start_min)
        if kind == "attraction":
            activity = self._make_attraction_activity(poi, people, start_time, end_time, transports_to_poi)
        else:
            activity = self._make_meal_activity(kind, poi, people, start_time, end_time, transports_to_poi)

        before = self._activity_counts(plan)
        old_first_transports = deepcopy(first_act.get("transports", []))
        first_act["transports"] = transports_to_next
        activities.insert(0, activity)
        try:
            if self._accepted(*check(plan)) and self._activity_counts(plan) > before:
                return True
        except Exception:
            pass
        del activities[0]
        first_act["transports"] = old_first_transports
        return False

    def _insert_activity_after_last(self, plan, day_idx, poi, kind, window, city, people, check):
        activities = plan["itinerary"][day_idx].get("activities", [])
        if not activities:
            return False
        last_act = activities[-1]
        prev_pos = self._activity_end_position(last_act)
        poi_name = str(poi.get("name", ""))
        if not prev_pos or not poi_name:
            return False
        if last_act.get("type") in ("airplane", "train"):
            return False

        # Preserve final intercity departure on the last day.
        itinerary = plan.get("itinerary", []) or []
        if day_idx == len(itinerary) - 1:
            return False

        try:
            start_anchor_min = time_to_minutes(str(last_act.get("end_time", "")))
        except Exception:
            return False

        win_open, win_close = window
        poi_open, poi_close = self._poi_open_bounds(poi)
        try:
            transports_to_poi, arrival = self._get_transport(
                self.env, city, prev_pos, poi_name, minutes_to_time(start_anchor_min), people)
        except Exception:
            return False
        if transports_to_poi is None or arrival is None:
            return False
        try:
            arrival_min = time_to_minutes(str(arrival))
        except Exception:
            return False

        start_min = max(arrival_min, win_open, poi_open)
        dwell = self._densify_dwell_minutes(poi, kind)
        end_min = start_min + dwell
        if end_min > min(win_close, poi_close):
            return False

        start_time = minutes_to_time(start_min)
        end_time = minutes_to_time(end_min)
        if kind == "attraction":
            activity = self._make_attraction_activity(poi, people, start_time, end_time, transports_to_poi)
        else:
            activity = self._make_meal_activity(kind, poi, people, start_time, end_time, transports_to_poi)

        before = self._activity_counts(plan)
        activities.append(activity)
        try:
            if self._accepted(*check(plan)) and self._activity_counts(plan) > before:
                return True
        except Exception:
            pass
        activities.pop()
        return False

    def _insert_activity(self, plan, day_idx, prev_idx, poi, kind, window, city, people, check):
        activities = plan["itinerary"][day_idx].get("activities", [])
        if prev_idx < 0 or prev_idx + 1 >= len(activities):
            return False
        prev_act = activities[prev_idx]
        next_act = activities[prev_idx + 1]
        prev_pos = self._activity_end_position(prev_act)
        next_pos = self._activity_start_position(next_act)
        poi_name = str(poi.get("name", ""))
        if not prev_pos or not next_pos or not poi_name:
            return False
        try:
            prev_end_min = time_to_minutes(str(prev_act.get("end_time", "")))
            next_start_min = time_to_minutes(str(next_act.get("start_time", "")))
        except Exception:
            return False
        if prev_end_min >= next_start_min:
            return False

        win_open, win_close = window
        poi_open, poi_close = self._poi_open_bounds(poi)
        try:
            transports_in, arrival = self._get_transport(
                self.env, city, prev_pos, poi_name, str(prev_act.get("end_time", "")), people)
        except Exception:
            return False
        if transports_in is None or arrival is None:
            return False
        try:
            arrival_min = time_to_minutes(str(arrival))
        except Exception:
            return False
        start_min = max(arrival_min, win_open, poi_open)
        dwell = self._densify_dwell_minutes(poi, kind)
        end_min = start_min + dwell
        if end_min > min(win_close, poi_close):
            return False

        start_time = minutes_to_time(start_min)
        end_time = minutes_to_time(end_min)
        try:
            transports_out, next_arrival = self._get_transport(
                self.env, city, poi_name, next_pos, end_time, people)
        except Exception:
            return False
        if transports_out is None or next_arrival is None:
            return False
        try:
            if time_to_minutes(str(next_arrival)) > next_start_min:
                return False
        except Exception:
            return False

        if kind == "attraction":
            activity = self._make_attraction_activity(poi, people, start_time, end_time, transports_in)
        else:
            activity = self._make_meal_activity(kind, poi, people, start_time, end_time, transports_in)

        before = self._activity_counts(plan)
        old_next_transports = deepcopy(next_act.get("transports", []))
        next_act["transports"] = transports_out
        activities.insert(prev_idx + 1, activity)
        try:
            if self._accepted(*check(plan)) and self._activity_counts(plan) > before:
                return True
        except Exception:
            pass
        del activities[prev_idx + 1]
        next_act["transports"] = old_next_transports
        return False

    def _extend_window_meals(self, plan, query, constraints, check, restaurants):
        """Swap a bounding intercity to a wider-window option and add the meal it unlocks.

        Purely additive: every existing activity is preserved and the trial is discarded
        unless the full checker accepts it and the activity count rises. This targets
        travel-day DDR -- a last-day dinner reachable after a later return, a day-1
        breakfast reachable after an earlier arrival -- the meal slots the default
        earliest-departure selection closes. Gains are locked in by the monotonic merge.
        """
        if not plan.get("itinerary"):
            return
        start_city = query.get("start_city", "")
        target_city = query.get("target_city", "")
        people = int(query.get("people_number", 1) or 1)
        intercity_mode = constraints.get("intercity_mode", None)
        outbound_pref = return_pref = None
        if isinstance(intercity_mode, dict):
            outbound_pref = intercity_mode.get("outbound", None)
            return_pref = intercity_mode.get("return", None)
        elif isinstance(intercity_mode, str):
            outbound_pref = return_pref = intercity_mode
        if os.environ.get("TPC_DENSIFY_LATE_DINNER", "0") == "1":
            self._swap_return_add_dinner(plan, start_city, target_city, people, return_pref, restaurants, check)
        if os.environ.get("TPC_DENSIFY_EARLY_BREAKFAST", "0") == "1":
            self._swap_outbound_add_breakfast(plan, start_city, target_city, people, outbound_pref, restaurants, check)

    def _swap_return_add_dinner(self, plan, start_city, target_city, people, return_pref, restaurants, check):
        itinerary = plan.get("itinerary", []) or []
        last_idx = len(itinerary) - 1
        if last_idx < 0:
            return
        acts = itinerary[last_idx].get("activities", []) or []
        if len(acts) < 2 or acts[-1].get("type") not in ("airplane", "train"):
            return
        if any(a.get("type") == "dinner" for a in acts):
            return
        try:
            cur_dep = time_to_minutes(str(acts[-1].get("start_time", "")))
        except Exception:
            return
        min_dep = self._env_time_minutes("TPC_DENSIFY_LATE_DINNER_MIN_DEP", "20:30")
        dinner_close = self._env_time_minutes("TPC_DENSIFY_DINNER_WIN_CLOSE", "20:00")
        if cur_dep >= min_dep:
            return
        later = self._get_intercity(
            self.env, target_city, start_city, "00:00", return_pref,
            self._budget_limits, {}, pending_intercity=None, people=people, window="late")
        if later is None:
            return
        try:
            new_dep = time_to_minutes(str(later.get("BeginTime", "")))
        except Exception:
            return
        if new_dep < min_dep or new_dep <= cur_dep:
            return
        trial = deepcopy(plan)
        tacts = trial["itinerary"][last_idx]["activities"]
        prev_pos = self._activity_end_position(tacts[-2])
        try:
            transports, _ = self._get_transport(
                self.env, target_city, prev_pos, later["From"], str(tacts[-2].get("end_time", "")), people)
        except Exception:
            transports = None
        tacts[-1] = self._make_intercity_activity(later, people, transports or [])
        for restaurant in restaurants:
            if not self._norm_text(restaurant.get("name", "")):
                continue
            if self._insert_activity(
                    trial, last_idx, len(tacts) - 2, restaurant, "dinner",
                    (17 * 60, dinner_close), target_city, people, check):
                itinerary[last_idx]["activities"] = trial["itinerary"][last_idx]["activities"]
                return

    def _swap_outbound_add_breakfast(self, plan, start_city, target_city, people, outbound_pref, restaurants, check):
        itinerary = plan.get("itinerary", []) or []
        if not itinerary:
            return
        acts = itinerary[0].get("activities", []) or []
        if len(acts) < 2 or acts[0].get("type") not in ("airplane", "train"):
            return
        if any(a.get("type") == "breakfast" for a in acts):
            return
        try:
            cur_arr = time_to_minutes(str(acts[0].get("end_time", "")))
        except Exception:
            return
        earlier = self._get_intercity(
            self.env, start_city, target_city, "00:00", outbound_pref,
            self._budget_limits, {}, pending_intercity=None, people=people, window="early_arrival")
        if earlier is None:
            return
        try:
            new_dep = time_to_minutes(str(earlier.get("BeginTime", "")))
            new_arr = time_to_minutes(str(earlier.get("EndTime", "")))
            if new_arr < new_dep:
                new_arr += 1440
        except Exception:
            return
        # Breakfast must end by 09:00; require an arrival early enough to seat it with transport.
        if new_arr > time_to_minutes("08:15") or new_arr >= cur_arr:
            return
        trial = deepcopy(plan)
        tacts = trial["itinerary"][0]["activities"]
        tacts[0] = self._make_intercity_activity(earlier, people, [])
        for restaurant in restaurants:
            if not self._norm_text(restaurant.get("name", "")):
                continue
            if self._insert_activity(
                    trial, 0, 0, restaurant, "breakfast",
                    (6 * 60, 9 * 60), target_city, people, check):
                itinerary[0]["activities"] = trial["itinerary"][0]["activities"]
                return

    def _densify_plan(self, plan, query, constraints, check):
        """Insert meals/attractions into proven idle gaps without trading away acceptance.

        Every insertion is gated by the full oracle/schema/commonsense checker and reverted on
        failure, so budget, exclusion, timing, transport, and query-specific hard constraints stay
        correct even though this pass only reasons locally about idle windows.
        """
        try:
            if not self._accepted(*check(plan)):
                return plan
        except Exception:
            return plan
        try:
            from agent.tpc_agent.cp_candidates import build_candidate_context
            ctx = build_candidate_context(
                self, query, constraints or {}, {"attractions": 80, "restaurants": 50, "hotels": 1})
        except Exception:
            return plan

        dense = deepcopy(plan)
        city = query.get("target_city", "")
        people = int(query.get("people_number", 1) or 1)
        constraints = constraints or {}
        self._active_timing_constraints = constraints.get("timing_constraints", []) or []
        self._transport_constraints = {
            "excluded_inner_transport": constraints.get("excluded_inner_transport", []),
            "conditional_transport": constraints.get("conditional_transport", None),
            "taxi_cars_equals": constraints.get("taxi_cars_equals", None),
        }
        self._forced_inner_mode = None
        self._budget_limits = self._extract_budget_limits(constraints)

        restaurants = sorted(ctx.get("restaurants", []) or [], key=lambda r: (r.get("price_cents", 0), r.get("name", "")))
        attractions = list(ctx.get("attractions", []) or [])
        coords = {}
        for row in attractions + restaurants + (ctx.get("hotels", []) or []):
            name = self._norm_text(row.get("name", ""))
            if name and "lat" in row and "lon" in row:
                coords[name] = row

        self._compress_activity_windows(dense, check)

        self._extend_window_meals(dense, query, constraints, check, restaurants)

        used_restaurants = set()
        used_attractions = set()
        for day in dense.get("itinerary", []) or []:
            for activity in day.get("activities", []) or []:
                name = self._norm_text(activity.get("position", ""))
                if activity.get("type") in ("breakfast", "lunch", "dinner") and name:
                    used_restaurants.add(name)
                elif activity.get("type") == "attraction" and name:
                    used_attractions.add(name)

        itinerary = dense.get("itinerary", []) or []
        # Idle-gap attraction packing knobs. The former 130-min threshold / 18:00 cutoff left
        # many real 90-120 min gaps (breakfast->lunch, afternoon->dinner) and all evening slots
        # unfilled; every insertion is still gated by the full checker via _insert_activity.
        attr_gap_min = int(os.environ.get("TPC_DENSIFY_ATTR_GAP_MIN", "75"))
        attr_win_open = int(os.environ.get("TPC_DENSIFY_ATTR_WIN_OPEN", "9")) * 60
        attr_win_close = int(os.environ.get("TPC_DENSIFY_ATTR_WIN_CLOSE", "21")) * 60
        attr_candidate_limit = int(os.environ.get("TPC_DENSIFY_ATTR_CANDIDATES", "24"))
        def _ranked_attractions(anchor_row=None, next_row=None):
            return sorted(
                attractions,
                key=lambda a: (
                    (self._haversine_km(anchor_row, a) if anchor_row is not None else 0.0)
                    + (self._haversine_km(a, next_row) if next_row is not None else 0.0),
                    a.get("price_cents", 0),
                    a.get("name", ""),
                ),
            )[:attr_candidate_limit]

        for day_idx, day in enumerate(itinerary):
            activities = day.get("activities", []) or []
            if not activities:
                continue
            meal_types = {a.get("type") for a in activities if a.get("type") in ("breakfast", "lunch", "dinner")}
            meal_gap_min = max(1, int(os.environ.get("TPC_DENSIFY_MEAL_GAP_MIN", "60")))

            if "breakfast" not in meal_types:
                hotel = self._find_hotel_for_day(dense, day_idx)
                if hotel and self._insert_breakfast(dense, day_idx, hotel, check):
                    meal_types.add("breakfast")
                elif os.environ.get("TPC_DENSIFY_EARLY_BREAKFAST", "0") == "1":
                    r_name = self._insert_restaurant_breakfast(
                        dense, day_idx, restaurants, city, people, check, used_restaurants)
                    if r_name:
                        used_restaurants.add(r_name)
                        meal_types.add("breakfast")

            lunch_close = self._env_time_minutes("TPC_DENSIFY_LUNCH_WIN_CLOSE", "14:00")
            dinner_close = self._env_time_minutes("TPC_DENSIFY_DINNER_WIN_CLOSE", "20:00")
            for meal_type, window in (("lunch", (11 * 60, lunch_close)), ("dinner", (17 * 60, dinner_close))):
                if meal_type in meal_types:
                    continue
                inserted = False
                for restaurant in restaurants:
                    r_name = self._norm_text(restaurant.get("name", ""))
                    if not r_name or r_name in used_restaurants:
                        continue
                    if self._insert_activity_before_first(dense, day_idx, restaurant, meal_type, window, city, people, check):
                        used_restaurants.add(r_name)
                        meal_types.add(meal_type)
                        inserted = True
                        break
                    for prev_idx, _gap_start, _gap_end in self._day_gaps(activities, window[0], window[1], meal_gap_min):
                        if self._insert_activity(dense, day_idx, prev_idx, restaurant, meal_type, window, city, people, check):
                            used_restaurants.add(r_name)
                            meal_types.add(meal_type)
                            inserted = True
                            break
                    if inserted:
                        break
                    if self._insert_activity_after_last(dense, day_idx, restaurant, meal_type, window, city, people, check):
                        used_restaurants.add(r_name)
                        meal_types.add(meal_type)
                        inserted = True
                        break

            while sum(1 for a in activities if a.get("type") == "attraction") < 4:
                gaps = self._day_gaps(activities, attr_win_open, attr_win_close, attr_gap_min)
                inserted = False
                for prev_idx, _gap_start, _gap_end in gaps:
                    prev_name = self._norm_text(self._activity_end_position(activities[prev_idx]))
                    next_name = self._norm_text(self._activity_start_position(activities[prev_idx + 1]))
                    for attr in _ranked_attractions(coords.get(prev_name), coords.get(next_name)):
                        a_name = self._norm_text(attr.get("name", ""))
                        if not a_name or a_name in used_attractions:
                            continue
                        if self._insert_activity(dense, day_idx, prev_idx, attr, "attraction", (attr_win_open, attr_win_close), city, people, check):
                            used_attractions.add(a_name)
                            inserted = True
                            break
                    if inserted:
                        break
                if not inserted:
                    first_name = self._norm_text(self._activity_start_position(activities[0]))
                    first_coords = coords.get(first_name)
                    for attr in _ranked_attractions(first_coords, first_coords):
                        a_name = self._norm_text(attr.get("name", ""))
                        if not a_name or a_name in used_attractions:
                            continue
                        if self._insert_activity_before_first(dense, day_idx, attr, "attraction", (attr_win_open, attr_win_close), city, people, check):
                            used_attractions.add(a_name)
                            inserted = True
                            break
                if not inserted:
                    last_name = self._norm_text(self._activity_end_position(activities[-1]))
                    for attr in _ranked_attractions(coords.get(last_name)):
                        a_name = self._norm_text(attr.get("name", ""))
                        if not a_name or a_name in used_attractions:
                            continue
                        if self._insert_activity_after_last(dense, day_idx, attr, "attraction", (attr_win_open, attr_win_close), city, people, check):
                            used_attractions.add(a_name)
                            inserted = True
                            break
                if not inserted:
                    break

        dense = self._swap_restaurants_for_att(dense, query, constraints, check, restaurants, coords)
        dense = self._swap_attractions_for_att(dense, query, constraints, check, attractions, coords)
        dense = self._upgrade_transport_modes(dense, query, constraints, check)
        return dense

    def _swap_restaurants_for_att(self, plan, query, constraints, check, restaurants, coords):
        """Replace high-transit meal venues with nearer alternatives.

        This complements `_swap_attractions_for_att`: many remaining low-ATT plans
        are dominated by long walks to lunch/dinner while the attraction set is
        already near-optimal. Every swap is acceptance-gated and keeps meal count
        unchanged, so DDR/FPR/C-LPR do not regress.
        """
        if os.environ.get("TPC_DENSIFY_SWAP_MEALS", "1") == "0":
            return plan
        try:
            if not self._accepted(*check(plan)):
                return plan
        except Exception:
            return plan

        city = query.get("target_city", "")
        people = int(query.get("people_number", 1) or 1)
        constraints = constraints or {}

        protected_locations = set()
        for req in constraints.get("required_restaurants", []) or []:
            protected_locations.add(self._norm_text(req))
        for window in constraints.get("activity_time_windows", []) or []:
            if isinstance(window, dict) and window.get("location"):
                protected_locations.add(self._norm_text(window["location"]))
        for stay in constraints.get("stay_duration", []) or []:
            if isinstance(stay, dict) and stay.get("location"):
                protected_locations.add(self._norm_text(stay["location"]))
        for name in constraints.get("position_presence", []) or []:
            if name:
                protected_locations.add(self._norm_text(name))

        cuisine_pref = constraints.get("cuisine_preference", None)
        meal_windows = {
            "breakfast": (6 * 60, self._env_time_minutes("TPC_DENSIFY_BREAKFAST_WIN_CLOSE", "09:00")),
            "lunch": (11 * 60, self._env_time_minutes("TPC_DENSIFY_LUNCH_WIN_CLOSE", "14:00")),
            "dinner": (17 * 60, self._env_time_minutes("TPC_DENSIFY_DINNER_WIN_CLOSE", "20:00")),
        }
        max_swaps = int(os.environ.get("TPC_DENSIFY_MEAL_SWAP_MAX", "8"))
        swap_candidate_limit = int(os.environ.get("TPC_DENSIFY_MEAL_SWAP_CANDIDATES", "16"))
        swaps_done = 0

        used_names = set()
        for day in plan.get("itinerary", []) or []:
            for activity in day.get("activities", []) or []:
                if activity.get("type") in ("breakfast", "lunch", "dinner"):
                    used_names.add(self._norm_text(activity.get("position", "")))

        swappable = []
        for day_idx, day in enumerate(plan.get("itinerary", []) or []):
            activities = day.get("activities", []) or []
            for act_idx, activity in enumerate(activities):
                meal_type = activity.get("type")
                if meal_type not in meal_windows:
                    continue
                if self._safe_float(activity.get("price", 0.0), 0.0) <= 0.0:
                    continue
                pos_name = self._norm_text(activity.get("position", ""))
                if not pos_name:
                    continue
                if any(self._match_constraint_text(pos_name, p) for p in protected_locations):
                    continue
                transit_min = self._inner_activity_minutes(activity)
                swappable.append((transit_min, day_idx, act_idx, pos_name))
        swappable.sort(reverse=True)

        for transit_min, day_idx, act_idx, old_name in swappable:
            if swaps_done >= max_swaps:
                break
            if transit_min <= 10:
                break

            activities = plan["itinerary"][day_idx]["activities"]
            activity = activities[act_idx]
            meal_type = activity.get("type")
            window_open, window_close = meal_windows[meal_type]

            prev_raw_pos = None
            next_raw_pos = None
            if act_idx > 0:
                prev_raw_pos = self._activity_end_position(activities[act_idx - 1])
            if act_idx + 1 < len(activities):
                next_raw_pos = self._activity_start_position(activities[act_idx + 1])
            prev_coord = coords.get(self._norm_text(prev_raw_pos or ""))
            next_coord = coords.get(self._norm_text(next_raw_pos or ""))

            candidates = sorted(
                restaurants,
                key=lambda r: (
                    (self._haversine_km(prev_coord, r) if prev_coord is not None else 0.0)
                    + (self._haversine_km(r, next_coord) if next_coord is not None else 0.0),
                    r.get("price_cents", 0),
                    r.get("name", ""),
                ),
            )[:swap_candidate_limit]

            old_activity = deepcopy(activity)
            old_start_time = str(activity.get("start_time", ""))
            old_end_time = str(activity.get("end_time", ""))
            meal_len = time_to_minutes(old_end_time) - time_to_minutes(old_start_time) if old_start_time and old_end_time else 60
            from_pos = prev_raw_pos or str(activity.get("position", ""))
            if prev_raw_pos and act_idx > 0:
                depart_time = str(activities[act_idx - 1].get("end_time", "08:00"))
            else:
                depart_time = old_start_time

            for cand in candidates:
                cand_name = self._norm_text(cand.get("name", ""))
                cand_actual_name = str(cand.get("name", ""))
                if not cand_name or cand_name == old_name or cand_name in used_names:
                    continue
                if cuisine_pref and not self._match_constraint_text(cand.get("cuisine", ""), cuisine_pref):
                    continue

                cand_open, cand_close = self._poi_open_bounds(cand)
                transports_in, arrival = self._get_transport(
                    self.env, city, from_pos, cand_actual_name, depart_time, people)
                if transports_in is None or arrival is None:
                    continue
                start_min = max(time_to_minutes(arrival), window_open, cand_open)
                end_min = start_min + meal_len
                if end_min > min(window_close, cand_close):
                    continue

                transports_out = None
                if next_raw_pos and act_idx + 1 < len(activities):
                    next_start = str(activities[act_idx + 1].get("start_time", ""))
                    transports_out, next_arrival = self._get_transport(
                        self.env, city, cand_actual_name, next_raw_pos, minutes_to_time(end_min), people)
                    if transports_out is None or next_arrival is None:
                        continue
                    if next_start and time_to_minutes(next_arrival) > time_to_minutes(next_start):
                        continue

                new_activity = self._make_meal_activity(
                    meal_type, cand, people, minutes_to_time(start_min), minutes_to_time(end_min), transports_in)
                new_transit = self._inner_activity_minutes(new_activity)
                if new_transit >= transit_min:
                    continue

                before_key = self._accepted_eval_key(plan)
                old_next_transports = None
                if transports_out is not None and act_idx + 1 < len(activities):
                    old_next_transports = deepcopy(activities[act_idx + 1].get("transports", []))
                    activities[act_idx + 1]["transports"] = transports_out
                activities[act_idx] = new_activity
                try:
                    if self._accepted(*check(plan)) and self._accepted_eval_key(plan) >= before_key:
                        used_names.discard(old_name)
                        used_names.add(cand_name)
                        swaps_done += 1
                        break
                except Exception:
                    pass
                activities[act_idx] = old_activity
                if old_next_transports is not None:
                    activities[act_idx + 1]["transports"] = old_next_transports

        return plan

    def _swap_attractions_for_att(self, plan, query, constraints, check, attractions, coords):
        """Replace high-transit-time attractions with geographically closer alternatives.

        Targets ATT by reducing average innercity_transport_time. Each swap is gated by the
        full checker so hard constraints, budget, and activity counts never regress. Only
        non-required attractions are considered for replacement.
        """
        if os.environ.get("TPC_DENSIFY_SWAP_ATT", "1") == "0":
            return plan
        try:
            if not self._accepted(*check(plan)):
                return plan
        except Exception:
            return plan

        city = query.get("target_city", "")
        people = int(query.get("people_number", 1) or 1)
        constraints = constraints or {}
        required_attractions = set()
        for req in constraints.get("required_attractions", []) or []:
            required_attractions.add(self._norm_text(req))
        for req in constraints.get("required_attraction_types", []) or []:
            required_attractions.add(self._norm_text(req))
        # Also protect attractions named in time windows or stay duration constraints.
        for w in constraints.get("activity_time_windows", []) or []:
            if isinstance(w, dict) and w.get("location"):
                required_attractions.add(self._norm_text(w["location"]))
        for d in constraints.get("stay_duration", []) or []:
            if isinstance(d, dict) and d.get("location"):
                required_attractions.add(self._norm_text(d["location"]))

        max_swaps = int(os.environ.get("TPC_DENSIFY_SWAP_MAX", "8"))
        swap_candidate_limit = int(os.environ.get("TPC_DENSIFY_SWAP_CANDIDATES", "12"))
        swaps_done = 0

        # Collect all current attraction names in the plan to avoid duplicates.
        used_names = set()
        for day in plan.get("itinerary", []) or []:
            for activity in day.get("activities", []) or []:
                if activity.get("type") == "attraction":
                    used_names.add(self._norm_text(activity.get("position", "")))

        # Build ranked list of swappable attractions by transit duration (longest first).
        swappable = []
        for day_idx, day in enumerate(plan.get("itinerary", []) or []):
            activities = day.get("activities", []) or []
            for act_idx, activity in enumerate(activities):
                if activity.get("type") != "attraction":
                    continue
                pos_name = self._norm_text(activity.get("position", ""))
                if not pos_name:
                    continue
                # Don't swap required attractions.
                if any(self._match_constraint_text(pos_name, r) for r in required_attractions):
                    continue
                transit_min = self._inner_activity_minutes(activity)
                swappable.append((transit_min, day_idx, act_idx, pos_name))
        swappable.sort(reverse=True)

        for transit_min, day_idx, act_idx, old_name in swappable:
            if swaps_done >= max_swaps:
                break
            if transit_min <= 10:
                break  # Not worth swapping short transits.

            activities = plan["itinerary"][day_idx]["activities"]
            activity = activities[act_idx]
            # Get raw (non-normalized) position names for transport API.
            prev_raw_pos = None
            next_raw_pos = None
            if act_idx > 0:
                prev_raw_pos = self._activity_end_position(activities[act_idx - 1])
            if act_idx + 1 < len(activities):
                next_raw_pos = self._activity_start_position(activities[act_idx + 1])
            prev_coord = coords.get(self._norm_text(prev_raw_pos or ""))
            next_coord = coords.get(self._norm_text(next_raw_pos or ""))

            # Rank candidate attractions by combined distance to prev + next.
            candidates = sorted(
                attractions,
                key=lambda a: (
                    (self._haversine_km(prev_coord, a) if prev_coord is not None else 0.0)
                    + (self._haversine_km(a, next_coord) if next_coord is not None else 0.0)
                ),
            )[:swap_candidate_limit]

            old_activity = deepcopy(activity)
            old_start_time = str(activity.get("start_time", ""))
            old_end_time = str(activity.get("end_time", ""))
            visit_len = time_to_minutes(old_end_time) - time_to_minutes(old_start_time) if old_start_time and old_end_time else 60

            # Departure point and time for reaching the candidate.
            from_pos = prev_raw_pos or str(activity.get("position", ""))
            if prev_raw_pos and act_idx > 0:
                depart_time = str(activities[act_idx - 1].get("end_time", "08:00"))
            else:
                depart_time = old_start_time

            for cand in candidates:
                cand_name = self._norm_text(cand.get("name", ""))
                cand_actual_name = str(cand.get("name", ""))
                if not cand_name or cand_name == old_name or cand_name in used_names:
                    continue
                # Check open hours.
                cand_open, cand_close = self._poi_open_bounds(cand)
                # Build transport from prev to candidate.
                transports_in, arrival = self._get_transport(
                    self.env, city, from_pos, cand_actual_name, depart_time, people)
                if transports_in is None or arrival is None:
                    continue
                start_min = max(time_to_minutes(arrival), cand_open)
                end_min = start_min + visit_len
                if end_min > cand_close or end_min > 22 * 60:
                    continue
                # Check we can reach the next activity in time.
                transports_out = None
                if next_raw_pos and act_idx + 1 < len(activities):
                    next_start = str(activities[act_idx + 1].get("start_time", ""))
                    transports_out, next_arrival = self._get_transport(
                        self.env, city, cand_actual_name, next_raw_pos, minutes_to_time(end_min), people)
                    if transports_out is None or next_arrival is None:
                        continue
                    if next_start and time_to_minutes(next_arrival) > time_to_minutes(next_start):
                        continue

                # Build replacement activity.
                new_activity = self._make_attraction_activity(
                    cand, people, minutes_to_time(start_min), minutes_to_time(end_min), transports_in)

                # Check new transit is actually shorter.
                new_transit = self._inner_activity_minutes(new_activity)
                if new_transit >= transit_min:
                    continue

                # Try the swap.
                before_key = self._accepted_eval_key(plan)
                old_next_transports = None
                if transports_out is not None and act_idx + 1 < len(activities):
                    old_next_transports = deepcopy(activities[act_idx + 1].get("transports", []))
                    activities[act_idx + 1]["transports"] = transports_out
                activities[act_idx] = new_activity
                try:
                    if self._accepted(*check(plan)) and self._accepted_eval_key(plan) >= before_key:
                        used_names.discard(old_name)
                        used_names.add(cand_name)
                        swaps_done += 1
                        break
                except Exception:
                    pass
                # Revert.
                activities[act_idx] = old_activity
                if old_next_transports is not None:
                    activities[act_idx + 1]["transports"] = old_next_transports

        return plan

    def _rebuild_hop(self, city, from_pos, to_pos, start_time, people, mode):
        """Build one inner-city hop in `mode`, mirroring _get_transport's segment dicts.
        Returns (transports_list, duration_min) or (None, None)."""
        try:
            result = self.env.transportation.goto(city, from_pos, to_pos, start_time, mode)
        except Exception:
            return None, None
        if not isinstance(result, list) or len(result) == 0:
            return None, None
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
            else:
                t["price"] = 0
                t["cost"] = 0
            transports.append(t)
        try:
            dur = time_to_minutes(str(transports[-1]["end_time"])) - time_to_minutes(str(transports[0]["start_time"]))
        except Exception:
            return None, None
        if dur < 0:
            return None, None
        return transports, dur

    def _upgrade_transport_modes(self, plan, query, constraints, check):
        """Acceptance-gated ATT optimizer: swap each inner-city hop to a faster mode, keeping
        the leg's start_time fixed so arrivals only move earlier (no downstream cascade). Each
        hop carries a candidate list (faster modes, fastest first), so a budget-tight query that
        rejects taxi can still fall back to metro. Lowers innercity_transport_time -> lifts ATT
        and never changes attraction/meal counts, so DAV/DDR/FPR/C-LPR cannot regress."""
        try:
            if not self._accepted(*check(plan)):
                return plan
        except Exception:
            return plan
        city = query.get("target_city", "")
        people = int(query.get("people_number", 1) or 1)

        def _legs_minutes(legs):
            tot = 0
            for leg in legs or []:
                try:
                    tot += time_to_minutes(str(leg["end_time"])) - time_to_minutes(str(leg["start_time"]))
                except Exception:
                    pass
            return tot

        hops = []  # (day_idx, act_idx, old_min, [candidate_transports, fastest first])
        for day_idx, day in enumerate(plan.get("itinerary", []) or []):
            activities = day.get("activities", []) or []
            for act_idx, activity in enumerate(activities):
                transports = activity.get("transports", []) or []
                if not transports:
                    continue
                modes_present = {self._norm_text(t.get("mode", "")) for t in transports}
                if not modes_present or (modes_present - {"walk", "metro", "taxi"}):
                    continue
                old_min = self._inner_activity_minutes(activity)
                from_pos = str(transports[0].get("start", "") or "")
                to_pos = str(transports[-1].get("end", "") or "")
                start_time = str(transports[0].get("start_time", "") or "")
                cur_start = str(activity.get("start_time", "") or "")
                if not from_pos or not to_pos or not start_time or from_pos == to_pos:
                    continue
                cands = []
                for mode in ("taxi", "metro"):
                    cand, dur = self._rebuild_hop(city, from_pos, to_pos, start_time, people, mode)
                    if cand is None or dur >= old_min:
                        continue
                    try:
                        if cur_start and time_to_minutes(str(cand[-1]["end_time"])) > time_to_minutes(cur_start):
                            continue
                    except Exception:
                        continue
                    cands.append((dur, cand))
                if cands:
                    cands.sort(key=lambda c: c[0])
                    hops.append((day_idx, act_idx, old_min, [c[1] for c in cands]))
        if not hops:
            return plan

        originals = [
            deepcopy(plan["itinerary"][d]["activities"][a]["transports"])
            for d, a, _o, _cl in hops
        ]
        # Fast path: apply each hop's fastest candidate, check once.
        for d, a, _o, cl in hops:
            plan["itinerary"][d]["activities"][a]["transports"] = cl[0]
        try:
            if self._accepted(*check(plan)):
                return plan
        except Exception:
            pass
        # Fallback: revert, then greedily upgrade by potential saving; per hop try fastest->slowest.
        for (d, a, _o, _cl), orig in zip(hops, originals):
            plan["itinerary"][d]["activities"][a]["transports"] = orig
        order = sorted(
            range(len(hops)),
            key=lambda i: hops[i][2] - _legs_minutes(hops[i][3][0]),
            reverse=True,
        )
        for i in order:
            d, a, _old_min, cl = hops[i]
            orig = plan["itinerary"][d]["activities"][a]["transports"]
            for cand in cl:
                plan["itinerary"][d]["activities"][a]["transports"] = cand
                try:
                    if self._accepted(*check(plan)):
                        break
                except Exception:
                    pass
                plan["itinerary"][d]["activities"][a]["transports"] = orig
        return plan

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

        _ic_late = os.environ.get("TPC_INTERCITY_LATE_RETURN", "0") == "1"
        _ic_early = os.environ.get("TPC_INTERCITY_EARLY_ARRIVAL", "0") == "1"
        outbound = self._get_intercity(
            env, start_city, target_city, "00:00" if _ic_early else "07:00", outbound_pref,
            budget_limits, budget_tracker, people=people,
            window="early_arrival" if _ic_early else None)
        if _ic_late:
            # Latest affordable departure maximizes the last-day in-city window so the
            # densify pass can place breakfast/lunch/dinner and a 4th attraction.
            return_transport = self._get_intercity(
                env, target_city, start_city, "00:00", return_pref, budget_limits,
                budget_tracker, pending_intercity=outbound, people=people, window="late")
        else:
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
        window=None,
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
            affordable = []
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
                            if window is None:
                                return cand
                            affordable.append(cand)
                        if best is None or best_cost is None or cost < best_cost:
                            best = cand
                            best_cost = cost
            except Exception:
                pass
            # Window modes maximize in-destination time among affordable options while
            # preserving transport-type priority (the preferred mode is tried first).
            if window and affordable:
                if window == "late":
                    return max(affordable, key=lambda c: time_to_minutes(str(c.get("BeginTime", "00:00"))))
                if window == "early_arrival":
                    def _arrival_min(c):
                        begin = time_to_minutes(str(c.get("BeginTime", "00:00")))
                        end = time_to_minutes(str(c.get("EndTime", "23:59")))
                        return end + (1440 if end < begin else 0)
                    return min(affordable, key=_arrival_min)
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
            return None, None

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