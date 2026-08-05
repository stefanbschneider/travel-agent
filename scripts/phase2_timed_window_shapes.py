#!/usr/bin/env python3
"""Classify the ``timed_visit_named_poi`` residual by *shape* (roadmap P1, Step 0).

``scripts/phase2_solver_failure_attribution.py`` says *which family* blocks a query. It cannot say
*what kind of move* would fix it, and the roadmap's P1 requires exactly that before any code is
written: "classify it by shape (forward-shift, backward-shift, needs-reordering,
infeasible-as-parsed) and count each. Choose a move only if one shape is a large share."

This script does that. For every produced plan it re-evaluates the query's oracle
``hard_logic_py`` clauses with the *official* evaluator (``evaluate_constraints_py``), keeps the
failing clauses classified as ``timed_visit_named_poi``, parses each one back into its
``(activity types, POI name, earliest, end_before)`` tuple, locates the corresponding activity in
the plan, and reports which *move* would be needed:

===========================  =========================================================
shape                        meaning
===========================  =========================================================
``absent_poi``               the POI appears nowhere in the plan -> insertion/reselection
``wrong_type``               the POI is in the plan, but never as a required activity type
``forward_shift``            present, correct type, starts too early -> push later
``backward_shift``           present, correct type, ends too late but starts >= earliest
                             -> pull earlier (no landed move does this)
``shorten``                  present, but its dwell exceeds the whole window -> must shrink
``satisfiable_elsewhere``    another same-POI copy already sits in the window (shouldn't
                             happen: the clause is existential, so the clause would pass)
===========================  =========================================================

For a ``forward_shift``/``backward_shift``/``shorten`` it also records the blocking context: the
neighbour that pins the activity in place, and whether that neighbour is *movable*
(meal/attraction, the block ``_relayout_movable_block`` may re-lay) or *fixed* (an intercity leg or
the overnight accommodation). That distinction is what decides whether a move is implementable at
all.

Diagnostic tooling: it reads local oracle fields only to attribute a rehearsal
(``docs/tpc_phase2_roadmap.md`` operating rule 1), makes no LLM calls, and re-solves nothing.

Usage::

    # classify the residual of a produced plan directory
    .venv/bin/python scripts/phase2_timed_window_shapes.py \
        --plans results/phase2_solver_only_tpc_phase2_familiar_100_val

    # machine-readable dump as well
    .venv/bin/python scripts/phase2_timed_window_shapes.py --plans <dir> --json out.json
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts"), str(PROJECT_ROOT / "chinatravel")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from phase2_solver_failure_attribution import (  # noqa: E402
    FAMILIAR_DATA_GLOB,
    classify_constraint,
)

# Every ``timed_visit_named_poi`` clause in familiar-100 is generated from one template (verified:
# 149/149 match). Parsing it back is therefore exact, not heuristic -- but an unmatched clause is
# reported rather than dropped, so a template change surfaces instead of skewing the counts.
TIMED_VISIT_RE = re.compile(
    r"^result\s*=\s*False\s*\n"
    r"for activity in allactivities\(plan\):\s*\n"
    r"\s*if activity_type\(activity\)"
    r"(?:\s*in\s*\[(?P<types>[^\]]*)\]|\s*==\s*'(?P<type>[a-z]+)')"
    r"\s*and activity_position\(activity\)==\"(?P<poi>[^\"]+)\":\s*\n"
    r"\s*if activity_start_time\(activity\)>=\"(?P<lo>\d\d:\d\d)\""
    r"\s*and activity_end_time\(activity\)<=\"(?P<hi>\d\d:\d\d)\":\s*result\s*=\s*True\s*$"
)

MOVABLE_TYPES = ("breakfast", "lunch", "dinner", "attraction")


def _minutes(hhmm: str) -> int:
    """``"HH:MM" -> minutes-of-day``, accepting the dataset's ``24:00`` end sentinel."""
    hours, _, mins = str(hhmm).partition(":")
    return int(hours) * 60 + int(mins)


def parse_timed_visit(code: str) -> dict | None:
    """Parse one ``timed_visit_named_poi`` clause into ``{types, poi, lo, hi}``; ``None`` if the
    clause does not match the template."""
    match = TIMED_VISIT_RE.match((code or "").strip())
    if not match:
        return None
    if match.group("types") is not None:
        types = tuple(t.strip().strip("'\"") for t in match.group("types").split(",") if t.strip())
    else:
        types = (match.group("type"),)
    return {
        "types": types,
        "poi": match.group("poi"),
        "lo": _minutes(match.group("lo")),
        "hi": _minutes(match.group("hi")),
    }


def _activities(plan: dict):
    """Yield ``(day_idx, act_idx, activity)`` over a plan's itinerary, defensively."""
    for day_idx, day in enumerate(plan.get("itinerary", []) or []):
        for act_idx, activity in enumerate(day.get("activities", []) or []):
            if isinstance(activity, dict):
                yield day_idx, act_idx, activity


def classify_shape(plan: dict, clause: dict) -> dict:
    """Classify what move would satisfy ``clause`` in ``plan``. Pure; unit-tested.

    The oracle clause is existential ("some activity of one of these types, at this POI, inside
    this window"), so the shape is decided by the *best-placed* same-POI, right-type activity: the
    one needing the smallest move. ``None`` is never returned -- an unclassifiable case reports
    ``shape="unclassified"`` so it cannot be silently absorbed into another bucket.
    """
    poi = clause["poi"]
    lo, hi = clause["lo"], clause["hi"]
    span = hi - lo
    at_poi = [(d, a, act) for d, a, act in _activities(plan) if str(act.get("position", "")) == poi]
    if not at_poi:
        return {"shape": "absent_poi", "detail": {}}
    right_type = [(d, a, act) for d, a, act in at_poi if act.get("type") in clause["types"]]
    if not right_type:
        return {
            "shape": "wrong_type",
            "detail": {"present_as": sorted({str(act.get("type")) for _, _, act in at_poi})},
        }

    best = None
    for day_idx, act_idx, act in right_type:
        try:
            start = _minutes(act.get("start_time", ""))
            end = _minutes(act.get("end_time", ""))
        except Exception:
            continue
        dwell = max(0, end - start)
        if start >= lo and end <= hi:
            # Existential clause already satisfied by this copy: the caller only passes *failing*
            # clauses, so this means plan/clause disagree (e.g. a name normalized differently).
            return {"shape": "satisfiable_elsewhere",
                    "detail": {"day": day_idx, "act": act_idx}}
        if dwell > span:
            shape = "shorten"
            cost = dwell - span
        elif start < lo:
            shape = "forward_shift"
            cost = lo - start
        else:
            shape = "backward_shift"
            cost = end - hi
        cand = {
            "shape": shape,
            "detail": {
                "day": day_idx,
                "act": act_idx,
                "type": str(act.get("type")),
                "cur": f"{act.get('start_time')}-{act.get('end_time')}",
                "window": f"{clause['lo'] // 60:02d}:{clause['lo'] % 60:02d}-"
                          f"{clause['hi'] // 60:02d}:{clause['hi'] % 60:02d}",
                "minutes_off": cost,
                "dwell": dwell,
                "span": span,
                **_neighbour_context(plan, day_idx, act_idx),
            },
        }
        if best is None or cost < best["detail"]["minutes_off"]:
            best = cand
    return best or {"shape": "unclassified", "detail": {}}


def _neighbour_context(plan: dict, day_idx: int, act_idx: int) -> dict:
    """What pins this activity in place: the neighbours' types, and whether the whole day's
    meal/attraction block is contiguous (the precondition ``_relayout_movable_block`` enforces)."""
    acts = plan["itinerary"][day_idx].get("activities", []) or []
    prev_type = str(acts[act_idx - 1].get("type")) if act_idx > 0 else None
    next_type = str(acts[act_idx + 1].get("type")) if act_idx + 1 < len(acts) else None
    movable = [i for i, a in enumerate(acts)
               if a.get("type") in MOVABLE_TYPES and str(a.get("position", ""))]
    contiguous = bool(movable) and movable[-1] - movable[0] + 1 == len(movable)
    return {
        "prev_type": prev_type,
        "next_type": next_type,
        "prev_movable": prev_type in MOVABLE_TYPES if prev_type else False,
        "next_movable": next_type in MOVABLE_TYPES if next_type else False,
        "movable_block_contiguous": contiguous,
        "movable_count": len(movable),
        "day_activity_count": len(acts),
    }


def load_records(data_glob: str) -> dict[str, dict]:
    """uid -> the oracle split record (needs ``hard_logic_py``)."""
    out: dict[str, dict] = {}
    for path in sorted(glob.glob(data_glob)):
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
        if record.get("uid"):
            out[record["uid"]] = record
    return out


def analyse(plans_dir: Path, records: dict[str, dict], uids: list[str] | None = None) -> dict:
    """Re-evaluate every plan's oracle clauses and bucket the failing timed-visit ones by shape."""
    from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py

    shapes = Counter()
    shape_queries: dict[str, set[str]] = defaultdict(set)
    per_clause: list[dict] = []
    sole_blocker_uids: set[str] = set()
    unparsed = 0
    evaluated = 0
    plans_missing = 0
    query_pass = 0
    timed_visit_failing_uids: set[str] = set()

    for uid in sorted(uids if uids is not None else records):
        record = records.get(uid)
        if record is None:
            continue
        plan_path = plans_dir / f"{uid}.json"
        if not plan_path.exists():
            plans_missing += 1
            continue
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            plans_missing += 1
            continue
        clauses = list(record.get("hard_logic_py", []) or [])
        if not clauses:
            continue
        verdicts = evaluate_constraints_py(clauses, plan)
        evaluated += 1
        if all(verdicts):
            query_pass += 1
            continue
        failing_families = {
            classify_constraint(clauses[i]) for i, ok in enumerate(verdicts) if not ok
        }
        if failing_families == {"timed_visit_named_poi"}:
            sole_blocker_uids.add(uid)
        for idx, ok in enumerate(verdicts):
            if ok or classify_constraint(clauses[idx]) != "timed_visit_named_poi":
                continue
            timed_visit_failing_uids.add(uid)
            clause = parse_timed_visit(clauses[idx])
            if clause is None:
                unparsed += 1
                continue
            verdict = classify_shape(plan, clause)
            shapes[verdict["shape"]] += 1
            shape_queries[verdict["shape"]].add(uid)
            per_clause.append({
                "uid": uid,
                "clause_index": idx,
                "poi": clause["poi"],
                "types": list(clause["types"]),
                "shape": verdict["shape"],
                "sole_blocker_query": uid in sole_blocker_uids,
                **verdict["detail"],
            })

    return {
        "plans_dir": str(plans_dir),
        "evaluated": evaluated,
        "plans_missing": plans_missing,
        "all_pass": query_pass,
        "timed_visit_failing_queries": len(timed_visit_failing_uids),
        "timed_visit_sole_blocker_queries": len(sole_blocker_uids & timed_visit_failing_uids),
        "unparsed_clauses": unparsed,
        "shapes": {
            shape: {"instances": count, "queries": len(shape_queries[shape])}
            for shape, count in shapes.most_common()
        },
        "sole_blocker_shapes": dict(
            Counter(row["shape"] for row in per_clause if row["sole_blocker_query"]).most_common()
        ),
        "clauses": per_clause,
    }


def format_report(att: dict) -> str:
    lines = [
        f"=== timed_visit_named_poi residual by SHAPE  ({att['plans_dir']}) ===",
        f"  plans evaluated={att['evaluated']}  missing={att['plans_missing']}  "
        f"all_pass={att['all_pass']}",
        f"  queries with >=1 failing timed-visit clause: {att['timed_visit_failing_queries']}"
        f"  (sole logical blocker in {att['timed_visit_sole_blocker_queries']})",
        "",
        f"  {'shape':<24}{'instances':>10}{'queries':>9}{'sole-blocker inst.':>20}",
    ]
    for shape, stats in att["shapes"].items():
        lines.append(
            f"  {shape:<24}{stats['instances']:>10}{stats['queries']:>9}"
            f"{att['sole_blocker_shapes'].get(shape, 0):>20}"
        )
    if att["unparsed_clauses"]:
        lines.append(f"  !! {att['unparsed_clauses']} clause(s) did not match the template")
    lines += ["", "Shape decides the move; see the module docstring. Attribution only."]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plans", required=True, help="directory of produced <uid>.json plans")
    parser.add_argument("--data-glob", default=FAMILIAR_DATA_GLOB,
                        help="oracle split record glob (uid -> hard_logic_py)")
    parser.add_argument("--split", default=None,
                        help="restrict to a split file's uids (e.g. tpc_phase2_familiar_100_val)")
    parser.add_argument("--json", default=None, help="also write the machine-readable attribution")
    parser.add_argument("--detail", action="store_true",
                        help="print one line per failing clause")
    args = parser.parse_args()

    uids = None
    if args.split:
        import make_phase2_splits as splits

        uids = list(splits.read_split(args.split))

    att = analyse(Path(args.plans), load_records(args.data_glob), uids)
    print(format_report(att))
    if args.detail:
        print("\n--- per-clause detail ---")
        for row in att["clauses"]:
            print(f"  {row['shape']:<20} {row['uid'][-12:]} d{row.get('day')} "
                  f"{row.get('cur', '-'):<14} want {row.get('window', '-'):<12} "
                  f"off={row.get('minutes_off', '-')}m prev={row.get('prev_type')} "
                  f"next={row.get('next_type')} {row['poi'][:44]}")
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(att, indent=2), encoding="utf-8")
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
