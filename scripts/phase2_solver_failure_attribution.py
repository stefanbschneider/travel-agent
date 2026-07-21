#!/usr/bin/env python3
"""Attribute Phase 2 *solver-only* failures to constraint families (diagnostic-only).

The solver-only axis feeds oracle constraints to a bounded solve, so any failure it produces is
pure solver/search headroom -- parsing is removed. A committed baseline run
(``results/phase2_baselines/runs/<run_id>.json``) records, per query, which oracle
``hard_logic_py`` clause passed or failed (``logical_details`` -> ``logic_py_<N>`` with ``N`` the
index into the query's ``hard_logic_py`` list; ``nan`` is right-padding) and which commonsense
category failed (``commonsense_details``). This script joins those per-clause verdicts against the
split's oracle constraints, classifies every clause into a family, and reports which families the
solver actually fails on.

This is **attribution tooling**, not a promotable measurement and not part of the agent path: it
reads local oracle fields only to *score/attribute a rehearsal*, which the operating rules allow
(docs/tpc_phase2_roadmap.md, rule 1). It makes no LLM calls and re-solves nothing.

Usage:
    python3 scripts/phase2_solver_failure_attribution.py                 # latest familiar row
    python3 scripts/phase2_solver_failure_attribution.py --run results/phase2_baselines/runs/<id>.json
    python3 scripts/phase2_solver_failure_attribution.py --mode end-to-end
    python3 scripts/phase2_solver_failure_attribution.py --json out.json  # machine-readable dump
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Where the imported official familiar-100 records live (uid -> hard_logic_py).
FAMILIAR_DATA_GLOB = str(
    PROJECT_ROOT
    / "chinatravel/data/en/TPC_IJCAI_2026_phase2_familiar_100_data/phase2_familiar_*.json"
)
DEFAULT_RUN = str(PROJECT_ROOT / "results/phase2_baselines/runs/20260718T155006Z.json")


# --- Constraint family classifier (pure, unit-tested) ---------------------------------------
#
# Each oracle ``hard_logic_py`` clause is a small Python snippet with a stable, template-generated
# shape. We classify by the helper functions and set-algebra it uses. ``not({...}&X)`` is an
# *exclusion* (X must avoid the named set); ``{...}<=X`` / truthy ``{...}&X`` is a *requirement*.


def classify_constraint(code: str) -> str:
    """Map one ``hard_logic_py`` snippet to a coarse constraint family name.

    Returns a stable family slug. Unrecognized shapes return ``"unclassified"`` so the caller can
    surface (and we can extend) the residual rather than silently mislabel it.
    """
    c = code or ""

    # Structural / trip-shape constraints.
    if "day_count(" in c:
        return "structural_days"
    if "people_count(" in c:
        return "structural_people"

    # Timed visit at a *named* POI: activity_position(...)==\"Name\" gated by a start/end window.
    # This is the "pin a timed visit at a named POI" pattern (roadmap G8).
    if "activity_position(activity)==" in c and (
        "activity_start_time(" in c or "activity_end_time(" in c
    ):
        return "timed_visit_named_poi"

    # Ticket / room counts (per-activity equality against the party size).
    if "activity_tickets(" in c or "metro_tickets(" in c:
        return "ticket_count"
    if "room_count(" in c:
        return "room_count"

    is_excl = "not(" in c

    # Name-set membership families (attraction / restaurant / accommodation).
    if "attraction_name_set" in c:
        return "excluded_attractions" if is_excl else "required_attractions"
    if "restaurant_name_set" in c:
        return "excluded_restaurants" if is_excl else "required_restaurants"
    if "accommodation_name_set" in c:
        return "excluded_hotels" if is_excl else "required_hotels"

    # Type / cuisine set families.
    if "attraction_type_set" in c:
        return "excluded_attraction_types" if is_excl else "required_attraction_types"
    if "restaurant_type_set" in c or "cuisine" in c or "food_type" in c:
        return "excluded_cuisine_types" if is_excl else "required_cuisine_types"

    # Budgets (bucketed by the cost accumulator variable).
    if "accommodation_cost" in c:
        return "budget_accommodation"
    if "restaurant_cost" in c:
        return "budget_dining"
    if "total_cost" in c:
        return "budget_total"
    if "sightseeing" in c or "attraction_cost" in c:
        return "budget_sightseeing"

    # Intercity transport mode (train / airplane selection).
    if "intercity" in c and ("train" in c or "airplane" in c):
        return "intercity_mode"

    # Inner-city transport families.
    if "taxi" in c:
        return "taxi_cars"
    if "innercity_transport" in c:
        return "excluded_inner_transport" if is_excl else "inner_transport"

    return "unclassified"


# --- Loaders --------------------------------------------------------------------------------


def load_hard_logic_by_uid(data_glob: str = FAMILIAR_DATA_GLOB) -> dict[str, list[str]]:
    """uid -> its ordered ``hard_logic_py`` clause list, from the imported split records."""
    out: dict[str, list[str]] = {}
    for f in sorted(glob.glob(data_glob)):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        uid = d.get("uid")
        if uid:
            out[uid] = list(d.get("hard_logic_py", []))
    return out


def _is_nan(v) -> bool:
    return isinstance(v, float) and math.isnan(v)


def failed_logic_indices(detail_row: dict) -> list[int]:
    """Indices ``N`` where ``logic_py_<N>`` failed (==0). ``nan`` padding is ignored."""
    idx = []
    for k, v in detail_row.items():
        if not k.startswith("logic_py_"):
            continue
        if _is_nan(v):
            continue
        if int(v) == 0:
            idx.append(int(k.rsplit("_", 1)[1]))
    return sorted(idx)


def failed_commonsense_categories(detail_row: dict) -> list[str]:
    """Commonsense category names that failed for this query.

    Commonsense uses the *inverted* sign convention vs logical: a category value of ``0`` means no
    violation (pass) and a non-zero value counts violations (fail). A query passes commonsense only
    when every category is ``0`` (verified: 76 all-zero rows == commonsense_pass_count).
    """
    out = []
    for k, v in detail_row.items():
        if k == "data_id":
            continue
        if _is_nan(v):
            continue
        if int(v) != 0:
            out.append(k)
    return out


# --- Attribution ----------------------------------------------------------------------------


def attribute(run: dict, hard_logic: dict[str, list[str]], mode: str) -> dict:
    """Join per-clause verdicts against oracle constraints; tally failures by family."""
    raw = run["rehearsal"]["modes"][mode]["raw"]
    n = raw["evaluated"]
    all_pass_ids = set(raw.get("all_pass_ids", []))
    logical = {r["data_id"]: r for r in raw.get("logical_details", [])}
    commonsense = {r["data_id"]: r for r in raw.get("commonsense_details", [])}

    # instances: total failed clauses per family (a query can carry several of one family).
    # queries: distinct queries with >=1 failed clause of that family.
    # sole_blocker: queries where this family is the ONLY logical family failing (highest leverage
    #   -- fixing it flips the query from fail to logical-pass on its own).
    inst = Counter()
    queries = defaultdict(set)
    cs_inst = Counter()
    cs_queries = defaultdict(set)
    per_query_failed_families: dict[str, set] = {}

    failing_uids = [u for u in logical if u not in all_pass_ids]

    for uid in failing_uids:
        fams = set()
        for idx in failed_logic_indices(logical[uid]):
            clauses = hard_logic.get(uid, [])
            fam = classify_constraint(clauses[idx]) if idx < len(clauses) else "index_oob"
            inst[fam] += 1
            queries[fam].add(uid)
            fams.add(fam)
        per_query_failed_families[uid] = fams
        for cat in failed_commonsense_categories(commonsense.get(uid, {})):
            cs_inst[cat] += 1
            cs_queries[cat].add(uid)

    sole = Counter()
    for uid, fams in per_query_failed_families.items():
        if len(fams) == 1:
            sole[next(iter(fams))] += 1

    return {
        "mode": mode,
        "n": n,
        "all_pass": len(all_pass_ids),
        "fpr": round(100.0 * len(all_pass_ids) / n, 2) if n else 0.0,
        "failing_query_count": len(failing_uids),
        "logical": {
            fam: {
                "failed_instances": inst[fam],
                "failing_queries": len(queries[fam]),
                "sole_blocker_queries": sole[fam],
                "uids": sorted(queries[fam]),
            }
            for fam in sorted(inst, key=lambda f: (-queries[f].__len__(), -inst[f]))
        },
        "commonsense": {
            cat: {"failed_instances": cs_inst[cat], "failing_queries": len(cs_queries[cat])}
            for cat in sorted(cs_inst, key=lambda c: -cs_queries[c].__len__())
        },
    }


# --- Reporting ------------------------------------------------------------------------------


def format_report(att: dict) -> str:
    lines = []
    lines.append(
        f"=== Phase 2 {att['mode']} failure attribution "
        f"(n={att['n']}, FPR={att['fpr']}, all_pass={att['all_pass']}, "
        f"failing_queries={att['failing_query_count']}) ==="
    )
    lines.append("")
    lines.append("LOGICAL failures by family (ranked by # failing queries):")
    lines.append(
        f"  {'family':<28}{'queries':>9}{'instances':>11}{'sole_blocker':>14}"
    )
    for fam, s in att["logical"].items():
        lines.append(
            f"  {fam:<28}{s['failing_queries']:>9}{s['failed_instances']:>11}"
            f"{s['sole_blocker_queries']:>14}"
        )
    lines.append("")
    lines.append("COMMONSENSE failures by category (ranked by # failing queries):")
    if att["commonsense"]:
        for cat, s in att["commonsense"].items():
            lines.append(f"  {s['failing_queries']:>4} queries  {cat}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(
        "Note: sole_blocker = queries where this is the ONLY logical family failing; fixing it "
        "alone flips the query to logical-pass. Attribution only, not a promotable metric."
    )
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", default=DEFAULT_RUN, help="baseline run JSON to attribute")
    p.add_argument("--mode", default="solver-only", choices=["solver-only", "end-to-end"])
    p.add_argument("--data-glob", default=FAMILIAR_DATA_GLOB, help="split record glob (uid -> hard_logic_py)")
    p.add_argument("--json", default=None, help="also write the machine-readable attribution here")
    args = p.parse_args()

    with open(args.run, encoding="utf-8") as fh:
        run = json.load(fh)
    hard_logic = load_hard_logic_by_uid(args.data_glob)
    att = attribute(run, hard_logic, args.mode)
    print(format_report(att))
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(att, fh, indent=2)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
