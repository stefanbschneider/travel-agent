#!/usr/bin/env python3
"""Cross-phrasing generalization probe for the Phase 2 constraint extractor.

Why this exists: the v1 submission scored 33.2473 on the organizers' held-out set while the same
code scores 64.17 on ``tpc_phase2_familiar_100`` and 90.56 on the local released 150-query
``tpc_phase2_test``. Inverting the official weighted sum puts the collapse in C-LPR (per-clause
logical pass rate), not only FPR -- i.e. clauses we never satisfy, which is what an *unextracted*
constraint looks like. Familiar-100 is a rigid numbered-requirements template; this script measures
the no-oracle parser against every locally available *differently phrased* released query set, so
the phrasing-generalization hypothesis becomes a number instead of a guess.

It reports, per query set:

- **inventory** -- query count, natural-language length, oracle clause density, phrasing register
  fingerprints (does the text carry a numbered "Requirements:" list? a bracketed metadata header?);
- **family-level parse quality** -- precision / recall / F1 / value-accuracy against the oracle
  solver-dict, reusing ``scripts.parser_vs_oracle`` unchanged so numbers are comparable with the
  existing ledger;
- **clause-level coverage** -- every oracle ``hard_logic_py`` clause is classified by the verifier
  primitives it calls, then checked against the parsed solver-dict. A clause whose family is absent
  from the parse is a clause we never even try to satisfy: ``clause_coverage`` is the share we do
  extract, and ``clpr_ceiling_if_unextracted_fail`` is the C-LPR upper bound implied by assuming
  every unextracted clause fails.

Measurement only: it imports the shipped parse path read-only and writes nothing outside its
``--out-dir``.

Usage::

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_generalization_probe.py \
        --out-dir results/phase2_baselines/screens/20260806_generalization_probe
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# --- Oracle clause -> constraint-family classification --------------------
#
# ``hard_logic_py`` clauses are Python snippets over the verifier primitives in
# chinatravel/symbol_verification/. Each clause is one C-LPR unit (``evaluate_hard_constraints_v2``
# scores one boolean per ``hard_logic_py`` entry). Each clause is classified by the *accumulator
# variable names* the released generator emits plus the primitives it calls -- both were read off
# every distinct clause signature present in familiar-100, tpc_phase2_test and HF easy/medium/human
# before writing these rules, so the vocabulary is exhaustive for the sets measured here rather
# than guessed.
#
# ``families`` names solver-dict families (the 24-name vocabulary shared by the parsed and oracle
# sides -- verified identical across all six sets) at least one of which must be present in our
# parse for us to have any chance of satisfying that clause kind. An empty tuple means the clause
# is guaranteed by trip metadata the harness always has (day count, party size, ticket counts,
# rooms/room-type defaults derived from ``people_number``), so it needs no extracted family.
CLAUSE_KIND_RULES: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    # (clause_kind, marker substrings (any match), covering solver-dict families)
    ("days", ("day_count(plan)==",), ()),
    ("people", ("people_count(plan)==",), ()),
    ("tickets_match_people", ("activity_tickets(", "metro_tickets("), ()),
    ("taxi_cars", ("taxi_cars(",), ("taxi_cars_equals",)),
    ("rooms", ("room_count(",), ()),
    ("room_type", ("room_type(",), ("room_type",)),
    ("cost_total", ("total_cost",), ("budgets",)),
    ("cost_accommodation", ("accommodation_cost", "hotel_cost"), ("budgets",)),
    ("cost_transport", ("inner_city_transportation_cost",), ("budgets",)),
    ("cost_attraction", ("attraction_cost",), ("budgets",)),
    ("cost_restaurant", ("restaurant_cost", "food_cost"), ("budgets",)),
    ("inner_transport_set", ("inner_city_transportation_set",),
     ("excluded_inner_transport",)),
    ("intercity_transport", ("intercity_transport_set",), ("intercity_mode",)),
    ("intercity_endpoint_mode", ("intercity_transport_go", "intercity_transport_back"),
     ("intercity_mode",)),
    ("intercity_departure_time", ("go_start_time", "go_end_time", "return_start_time",
                                  "back_end_time"), ("activity_time_windows",)),
    ("restaurant_type", ("restaurant_type_set",), ("cuisine_preference", "excluded_cuisine_types")),
    ("attraction_type", ("attraction_type_set",),
     ("required_attraction_types", "excluded_attraction_types")),
    ("accommodation_type", ("accommodation_type_set",),
     ("required_hotel_all_types", "required_hotel_any_types")),
    ("accommodation_name", ("accommodation_name_set",), ("required_hotels", "excluded_hotels")),
    ("restaurant_name", ("restaurant_name_set",),
     ("required_restaurants", "excluded_restaurants", "position_presence")),
    ("attraction_name", ("attraction_name_set",),
     ("required_attractions", "excluded_attractions", "position_presence")),
    ("spatial_hotel_distance", ("poi_distance(",), ("poi_distance_hotel", "hotel_nearby")),
    ("stay_duration", ("activity_time(",), ("stay_duration",)),
    ("required_order", ("idx_activity0", "idx_activity1"), ("required_order",)),
    ("activity_time_window", ("activity_start_time(", "activity_end_time("),
     ("activity_time_windows",)),
]

_DISJUNCTIVE_MARKER = "result_list"


def classify_clause(clause: str) -> tuple[tuple[str, ...], bool]:
    """Return (clause kinds detected, is_disjunctive) for one oracle ``hard_logic_py`` entry.

    A clause can carry several kinds. The released generator emits two shapes:

    - plain: one conjunctive check -> every detected kind must be covered for us to satisfy it;
    - ``result_list`` / ``result = result or r``: a *disjunction* over arms (see
      ``solver_constraints._split_result_list``) -> covering any one arm suffices.
    """
    text = clause or ""
    kinds = tuple(
        kind for kind, markers, _ in CLAUSE_KIND_RULES if any(m in text for m in markers)
    )
    return kinds, (_DISJUNCTIVE_MARKER in text)


_KIND_FAMILIES = {kind: fams for kind, _, fams in CLAUSE_KIND_RULES}


def clause_is_covered(clause: str, parsed_families: set[str]) -> tuple[bool, tuple[str, ...]]:
    """Could our parse ever satisfy this oracle clause? Returns (covered, kinds)."""
    kinds, disjunctive = classify_clause(clause)
    if not kinds:
        return False, ("unclassified",)
    per_kind = []
    for kind in kinds:
        fams = _KIND_FAMILIES.get(kind, ())
        per_kind.append(True if not fams else bool(parsed_families & set(fams)))
    covered = any(per_kind) if disjunctive else all(per_kind)
    return covered, kinds


def clause_gap_kind(clause: str, parsed_families: set[str],
                    oracle_families: set[str]) -> str:
    """Why is an uncovered clause uncovered? ``parse_gap`` vs ``schema_gap``.

    Some oracle clauses have no representation in the 24-name solver-dict vocabulary *at all* --
    e.g. an excluded *accommodation type* -- so the oracle-side ``solver_constraint_variants`` call
    drops them too. Those are a schema limit that is identical on every set and therefore says
    nothing about phrasing. Only ``parse_gap`` -- the oracle dict carries a covering family and our
    no-oracle parse does not -- is evidence about phrasing generalization.
    """
    covered_by_oracle, _ = clause_is_covered(clause, oracle_families)
    return "parse_gap" if covered_by_oracle else "schema_gap"


# --- Phrasing register fingerprints ---------------------------------------

_NUMBERED = re.compile(r"(?:^|\s)\d+\.\s")
_BRACKET_HEADER = re.compile(r"^\s*\[[^\]]{10,}\]")


def phrasing_fingerprint(text: str) -> dict:
    t = text or ""
    numbered = len(_NUMBERED.findall(t))
    return {
        "has_requirements_list": ("Requirement" in t or "requirement" in t) and numbered >= 2,
        "numbered_items": numbered,
        "has_bracket_header": bool(_BRACKET_HEADER.match(t)),
        "chars": len(t),
    }


# --- Data sources ---------------------------------------------------------


def load_local(split: str, lang: str = "en"):
    from chinatravel.data.load_datasets import load_query

    return load_query(argparse.Namespace(splits=split, lang=lang, oracle_translation=True))


def load_hf(hf_split: str):
    from parser_vs_oracle import load_hf_queries

    return load_hf_queries("default", [hf_split])


DEFAULT_SETS = [
    # (label, kind, name)
    ("familiar_100 (control)", "local", "tpc_phase2_familiar_100"),
    ("local_released_150", "local", "tpc_phase2_test"),
    ("hf_easy", "hf", "easy"),
    ("hf_medium", "hf", "medium"),
    ("hf_human", "hf", "human"),
    ("hf_preference_base50", "hf", "preference_base50"),
]


# --- Per-set measurement --------------------------------------------------


def measure_set(label: str, kind: str, name: str, *, limit: int | None = None,
                n_examples: int = 3) -> dict:
    from parser_vs_oracle import _f1, _families, compute_query_diff, query_variants

    ids, data = load_local(name) if kind == "local" else load_hf(name)
    if limit:
        ids = ids[:limit]

    clause_counts, nl_lens = [], []
    fingerprints = Counter()
    numbered_items = []
    rows = []
    clause_kind_total = Counter()
    clause_kind_uncovered = Counter()
    n_clauses = 0
    n_clauses_uncovered = 0
    n_clauses_free = 0  # metadata-guaranteed (days/people/tickets): no family needed
    gap_counts = Counter()
    parse_gap_by_kind = Counter()
    n_parse_gap = 0
    n_queries_parse_gap = 0
    per_query_clause_cov = []

    for uid in ids:
        q = dict(data[uid])
        q.setdefault("uid", uid)
        clauses = q.get("hard_logic_py") or []
        clause_counts.append(len(clauses))
        nl = q.get("nature_language") or ""
        nl_lens.append(len(nl))
        fp = phrasing_fingerprint(nl)
        fingerprints["requirements_list"] += int(fp["has_requirements_list"])
        fingerprints["bracket_header"] += int(fp["has_bracket_header"])
        numbered_items.append(fp["numbered_items"])

        row = compute_query_diff(q, disjunction=True, branch_aware=True)
        rows.append(row)

        # Clause-level coverage: does the parse carry a family that could satisfy each clause?
        parsed_variants, oracle_variants = query_variants(q, disjunction=True)
        parsed_fams: set[str] = set()
        for v in parsed_variants:
            parsed_fams |= _families(v)
        oracle_fams: set[str] = set()
        for v in oracle_variants:
            oracle_fams |= _families(v)
        covered_here = 0
        query_parse_gap = False
        for clause in clauses:
            covered, kinds = clause_is_covered(clause, parsed_fams)
            n_clauses += 1
            for kind in kinds:
                clause_kind_total[kind] += 1
            if covered:
                covered_here += 1
                if all(not _KIND_FAMILIES.get(k, ()) for k in kinds):
                    n_clauses_free += 1
            else:
                n_clauses_uncovered += 1
                gap = clause_gap_kind(clause, parsed_fams, oracle_fams)
                gap_counts[gap] += 1
                if gap == "parse_gap":
                    n_parse_gap += 1
                    query_parse_gap = True
                    for kind in kinds:
                        parse_gap_by_kind[kind] += 1
                for kind in kinds:
                    clause_kind_uncovered[kind] += 1
        if query_parse_gap:
            n_queries_parse_gap += 1
        if clauses:
            per_query_clause_cov.append(covered_here / len(clauses))

    mean_p = statistics.mean(r["precision"] for r in rows) if rows else 0.0
    mean_r = statistics.mean(r["recall"] for r in rows) if rows else 0.0

    examples = []
    for uid in ids[:n_examples]:
        q = data[uid]
        examples.append({
            "uid": uid,
            "days": q.get("days"),
            "people_number": q.get("people_number"),
            "n_oracle_clauses": len(q.get("hard_logic_py") or []),
            "nature_language": (q.get("nature_language") or "")[:600],
        })

    covered = n_clauses - n_clauses_uncovered
    return {
        "label": label,
        "source": {"kind": kind, "name": name},
        "n": len(ids),
        "inventory": {
            "nl_chars_mean": round(statistics.mean(nl_lens), 1) if nl_lens else 0,
            "nl_chars_median": statistics.median(nl_lens) if nl_lens else 0,
            "oracle_clauses_mean": round(statistics.mean(clause_counts), 2) if clause_counts else 0,
            "oracle_clauses_median": statistics.median(clause_counts) if clause_counts else 0,
            "oracle_clauses_min": min(clause_counts) if clause_counts else 0,
            "oracle_clauses_max": max(clause_counts) if clause_counts else 0,
            "pct_with_numbered_requirements_list": round(
                100.0 * fingerprints["requirements_list"] / len(ids), 1) if ids else 0,
            "pct_with_bracket_header": round(
                100.0 * fingerprints["bracket_header"] / len(ids), 1) if ids else 0,
            "numbered_items_mean": round(statistics.mean(numbered_items), 2) if numbered_items else 0,
        },
        "family_parse": {
            "precision": round(mean_p, 4),
            "recall": round(mean_r, 4),
            "f1": round(_f1(mean_p, mean_r), 4),
            "value_accuracy": round(statistics.mean(r["value_accuracy"] for r in rows), 4) if rows else 0,
            "totals": {k: sum(r[k] for r in rows)
                       for k in ("matched", "missing", "spurious", "wrong_value", "defaulted")},
            "queries_with_any_missing_family": sum(1 for r in rows if r["missing"] > 0),
            "pct_queries_with_any_missing_family": round(
                100.0 * sum(1 for r in rows if r["missing"] > 0) / len(rows), 1) if rows else 0,
            "disjunction_flattened": sum(1 for r in rows if r["disjunction_flattened"]),
        },
        "clause_coverage": {
            "n_oracle_clauses": n_clauses,
            "n_metadata_guaranteed": n_clauses_free,
            "n_covered": covered,
            "n_uncovered": n_clauses_uncovered,
            "clause_coverage": round(covered / n_clauses, 4) if n_clauses else 1.0,
            "clpr_ceiling_if_unextracted_fail": round(100.0 * covered / n_clauses, 2) if n_clauses else 100.0,
            # Only parse gaps are phrasing evidence: a schema gap is a vocabulary limit identical on
            # every set. This ceiling is the one to compare across sets.
            "n_parse_gap": n_parse_gap,
            "n_schema_gap": gap_counts.get("schema_gap", 0),
            "parse_gap_rate": round(n_parse_gap / n_clauses, 4) if n_clauses else 0.0,
            "clpr_ceiling_parse_gap_only": round(100.0 * (n_clauses - n_parse_gap) / n_clauses, 2) if n_clauses else 100.0,
            "parse_gap_by_kind": dict(parse_gap_by_kind.most_common()),
            # FPR is all-or-nothing per query, so a single unextracted clause forfeits the whole
            # query's 0.40-weighted FPR credit. This is the implied FPR ceiling.
            "n_queries_with_parse_gap": n_queries_parse_gap,
            "pct_queries_with_parse_gap": round(100.0 * n_queries_parse_gap / len(ids), 1) if ids else 0.0,
            "fpr_ceiling_from_parse_gaps": round(100.0 * (len(ids) - n_queries_parse_gap) / len(ids), 2) if ids else 100.0,
            "macro_clause_coverage": round(statistics.mean(per_query_clause_cov), 4) if per_query_clause_cov else 1.0,
            "by_kind_total": dict(clause_kind_total.most_common()),
            "by_kind_uncovered": dict(clause_kind_uncovered.most_common()),
        },
        "family_stats": _family_rollup(rows),
        "examples": examples,
    }


def _family_rollup(rows: list[dict], top: int = 15) -> list[dict]:
    from parser_vs_oracle import _aggregate_family_stats

    stats = _aggregate_family_stats(rows)
    ranked = sorted(stats, key=lambda s: (-(s["missing"] + s["wrong_value"]), -s["spurious"],
                                          s["family"]))
    return [
        {k: s[k] for k in ("family", "matched", "missing", "spurious", "wrong_value",
                           "example_missing_uids", "example_wrong_value_uids")}
        for s in ranked[:top]
        if s["missing"] or s["wrong_value"] or s["spurious"]
    ]


# --- "What would fixing family X buy?" ------------------------------------
#
# The candidate fix from the 2026-08-06 probe: teach parse_budget the bare "a budget of N RMB"
# phrasing and parse_room_type the plain "two twin rooms" / "big bed room" phrasing. Both are
# value-clean (a number; the English words single/twin), so unlike the name/type families their
# effect is not masked by the HF sets' Chinese oracle literals.
DEFAULT_FIX_KINDS = ("cost_total", "cost_accommodation", "cost_restaurant", "cost_transport",
                     "cost_attraction", "room_type")

_CJK = re.compile(r"[\u4e00-\u9fff]")


def fix_headroom(label: str, kind: str, name: str, *, fix_kinds=DEFAULT_FIX_KINDS,
                 limit: int | None = None) -> dict:
    """Ceilings before and after a hypothetical fix to ``fix_kinds``.

    A clause whose *only* uncovered kinds are in ``fix_kinds`` is assumed closed by the fix; a
    clause with any other uncovered kind is not. Residual gaps are additionally split by whether the
    oracle clause literal is CJK: a CJK-literal clause cannot pass under ``en`` scoring whatever the
    parser does (``attraction_type()`` returns English labels), so only the ASCII-literal residual is
    actionable headroom.
    """
    from parser_vs_oracle import _families, query_variants

    ids, data = load_local(name) if kind == "local" else load_hf(name)
    if limit:
        ids = ids[:limit]
    fixed = set(fix_kinds)

    n_cl = gap = gap_after = gap_ascii = gap_ascii_after = 0
    q_gap = q_gap_after = 0
    residual = Counter()
    residual_ascii = Counter()
    for uid in ids:
        q = dict(data[uid])
        q.setdefault("uid", uid)
        parsed_variants, oracle_variants = query_variants(q, disjunction=True)
        pf: set[str] = set()
        for v in parsed_variants:
            pf |= _families(v)
        of: set[str] = set()
        for v in oracle_variants:
            of |= _families(v)
        g = ga = False
        for clause in q.get("hard_logic_py") or []:
            n_cl += 1
            ascii_only = not _CJK.search(clause)
            covered, kinds = clause_is_covered(clause, pf)
            if covered or clause_gap_kind(clause, pf, of) != "parse_gap":
                continue
            gap += 1
            g = True
            gap_ascii += ascii_only
            remaining = set(kinds) - fixed
            if remaining:
                gap_after += 1
                ga = True
                gap_ascii_after += ascii_only
                for k in remaining:
                    residual[k] += 1
                    if ascii_only:
                        residual_ascii[k] += 1
        q_gap += g
        q_gap_after += ga

    n = len(ids)
    return {
        "label": label,
        "source": {"kind": kind, "name": name},
        "fix_kinds": sorted(fixed),
        "n": n,
        "n_clauses": n_cl,
        "parse_gap": gap,
        "parse_gap_after_fix": gap_after,
        "parse_gap_cjk_literal": gap - gap_ascii,
        "parse_gap_ascii_literal": gap_ascii,
        "parse_gap_ascii_literal_after_fix": gap_ascii_after,
        "queries_with_gap": q_gap,
        "queries_with_gap_after_fix": q_gap_after,
        "clpr_ceiling_now": round(100.0 * (n_cl - gap) / n_cl, 2) if n_cl else 100.0,
        "clpr_ceiling_after_fix": round(100.0 * (n_cl - gap_after) / n_cl, 2) if n_cl else 100.0,
        "fpr_ceiling_now": round(100.0 * (n - q_gap) / n, 2) if n else 100.0,
        "fpr_ceiling_after_fix": round(100.0 * (n - q_gap_after) / n, 2) if n else 100.0,
        "residual_by_kind": dict(residual.most_common()),
        "residual_by_kind_ascii_literal_only": dict(residual_ascii.most_common()),
    }


# --- P18: the standing phrasing-generalization gate ------------------------
#
# R22 (docs/tpc_phase2_eval.md#r22--the-standing-phrasing-tripwire-open-2-min-run-with-every-parser-change)
# was, until P18, "run the probe and read the table by eye". This turns that habit into a checked
# floor file: ``results/phase2_baselines/phrasing_generalization_floor.json`` records, per set, the
# last known-good ``n_parse_gap`` (must never rise) alongside ``n_oracle_clauses`` (a snapshot
# fingerprint -- if the released/HF data itself changed shape, the gap counts are no longer
# comparable and the check must skip that set, never fail it).


def load_floor(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("floor", data)


def check_floor(report: dict, floor: dict) -> tuple[list[str], list[str]]:
    """Compare ``report`` against a recorded floor. Returns ``(violations, skipped)``.

    A violation is a set whose ``n_parse_gap`` rose above its recorded floor, or a set present on
    one side but not the other (a structural drift the gate must not silently ignore). A skip is a
    set whose ``n_oracle_clauses`` no longer matches the floor's recorded snapshot -- the dataset
    revision moved, so the gap counts are not comparable and this is not evidence of a regression.
    """
    violations, skipped = [], []
    report_names = {s["source"]["name"] for s in report["sets"]}
    floor_names = set(floor)
    for missing in report_names - floor_names:
        violations.append(f"{missing}: measured but has no floor entry (add one, see --update-floor)")
    for stale in floor_names - report_names:
        violations.append(f"{stale}: has a floor entry but was not measured this run")

    for s in report["sets"]:
        name = s["source"]["name"]
        if name not in floor:
            continue
        recorded = floor[name]  # always {"n_parse_gap": int, "n_oracle_clauses": int} -- write_floor's shape
        current_gap = s["clause_coverage"]["n_parse_gap"]
        current_clauses = s["clause_coverage"]["n_oracle_clauses"]
        recorded_clauses = recorded.get("n_oracle_clauses")
        if recorded_clauses is not None and recorded_clauses != current_clauses:
            skipped.append(
                f"{s['label']} ({name}): n_oracle_clauses changed {recorded_clauses} -> "
                f"{current_clauses} -- dataset snapshot drifted, gap counts not comparable"
            )
            continue
        recorded_gap = recorded["n_parse_gap"]
        if current_gap > recorded_gap:
            violations.append(
                f"{s['label']} ({name}): parse-gap clauses rose {recorded_gap} -> {current_gap} "
                f"(n_oracle_clauses={current_clauses})"
            )
    return violations, skipped


def _git_sha() -> str | None:
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT,
                              capture_output=True, text=True, timeout=5,
                              check=True).stdout.strip()
    except Exception:
        return None


def write_floor(report: dict, path: Path, *, existing: dict | None = None) -> dict:
    """Ratchet-down-only: a set's recorded gap count only ever decreases here. If the current run
    regressed a set, its old (lower) floor value is kept, so the next --check-floor still fails --
    ``--update-floor`` can never launder a regression, only tighten the gate after a real fix."""
    existing = existing or {}
    new_floor = {}
    for s in report["sets"]:
        name = s["source"]["name"]
        current_gap = s["clause_coverage"]["n_parse_gap"]
        current_clauses = s["clause_coverage"]["n_oracle_clauses"]
        prev = existing.get(name)
        if prev and prev.get("n_oracle_clauses") == current_clauses:
            new_gap = min(current_gap, prev["n_parse_gap"])
            if current_gap > prev["n_parse_gap"]:
                print(f"[probe] --update-floor: {name} regressed ({prev['n_parse_gap']} -> "
                      f"{current_gap}); keeping the lower recorded floor ({new_gap})",
                      file=sys.stderr)
        else:
            new_gap = current_gap
        new_floor[name] = {"n_parse_gap": new_gap, "n_oracle_clauses": current_clauses}
    doc = {"_meta": {"generated": None, "git_sha": _git_sha(),
                     "note": "Frozen floor for the P18/R22 phrasing-generalization gate. "
                             "tpc_phase2_familiar_100 must stay pinned at 0. Other sets: a parser "
                             "change may lower a count but must never raise it -- see "
                             "docs/tpc_phase2_roadmap.md#p18--make-phrasing-robustness-a-gate."},
           "floor": new_floor}
    import datetime
    doc["_meta"]["generated"] = datetime.date.today().isoformat()
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=None, help="Write probe.json / summary.md here.")
    ap.add_argument("--limit", type=int, default=None, help="Cap queries per set (debug).")
    ap.add_argument("--only", nargs="*", default=None, help="Restrict to these set labels.")
    ap.add_argument("--fix-kinds", nargs="*", default=list(DEFAULT_FIX_KINDS),
                    help="Clause kinds a hypothetical parser fix would close, for the headroom "
                         f"table. Default: {' '.join(DEFAULT_FIX_KINDS)}")
    ap.add_argument("--check-floor", default=None,
                    help="Path to a floor JSON (see "
                         "results/phase2_baselines/phrasing_generalization_floor.json). Exit 1 if "
                         "any set's parse-gap count rose above its recorded floor. Incompatible "
                         "with --only, which would make unmeasured sets silently pass.")
    ap.add_argument("--update-floor", action="store_true",
                    help="With --check-floor, overwrite it with this run's counts instead of "
                         "checking. Ratchet-down only (see write_floor) -- never raises a set's "
                         "recorded floor, so it can tighten the gate but never launder a "
                         "regression.")
    args = ap.parse_args()

    if args.only and args.check_floor:
        ap.error("--check-floor measures every DEFAULT_SETS entry; --only would leave unmeasured "
                 "sets silently unchecked. Run the full probe for --check-floor.")
    if args.limit and args.check_floor:
        ap.error("--check-floor compares n_oracle_clauses against the recorded floor to detect "
                 "dataset drift; --limit shrinks every set's clause count, which would make every "
                 "set look drifted and skip -- a silent, vacuous PASS. Run the full probe for "
                 "--check-floor.")

    sets = DEFAULT_SETS
    if args.only:
        wanted = set(args.only)
        sets = [s for s in sets if s[0] in wanted or s[2] in wanted]

    report = {"sets": [], "fix_headroom": []}
    for label, kind, name in sets:
        print(f"[probe] measuring {label} ({kind}:{name}) ...", file=sys.stderr)
        report["sets"].append(measure_set(label, kind, name, limit=args.limit))
        report["fix_headroom"].append(
            fix_headroom(label, kind, name, fix_kinds=tuple(args.fix_kinds), limit=args.limit)
        )

    if args.check_floor:
        floor_path = Path(args.check_floor)
        if args.update_floor:
            existing = load_floor(floor_path) if floor_path.exists() else {}
            write_floor(report, floor_path, existing=existing)
            print(f"[probe] wrote floor to {floor_path}", file=sys.stderr)
        else:
            floor = load_floor(floor_path)
            violations, skipped = check_floor(report, floor)
            for msg in skipped:
                print(f"[probe] SKIPPED (snapshot drift, not a regression): {msg}", file=sys.stderr)
            if violations:
                print("[probe] PHRASING GENERALIZATION GATE: FAIL", file=sys.stderr)
                for v in violations:
                    print(f"  - {v}", file=sys.stderr)
                sys.exit(1)
            print("[probe] PHRASING GENERALIZATION GATE: PASS "
                 "(no set rose above its recorded floor)", file=sys.stderr)

    out = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out_dir:
        d = Path(args.out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "probe.json").write_text(out, encoding="utf-8")
        (d / "summary.md").write_text(render_markdown(report), encoding="utf-8")
        (d / "fix_headroom.json").write_text(
            json.dumps({h["label"]: h for h in report["fix_headroom"]},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "residual_gaps_after_fix.json").write_text(
            json.dumps({h["label"]: {"residual_all": h["residual_by_kind"],
                                     "residual_ascii_literal_only":
                                         h["residual_by_kind_ascii_literal_only"]}
                        for h in report["fix_headroom"]},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[probe] wrote {d}/probe.json, summary.md, fix_headroom.json, "
              f"residual_gaps_after_fix.json", file=sys.stderr)
    print(render_markdown(report))
    print()
    print(render_fix_markdown(report))


def render_markdown(report: dict) -> str:
    lines = ["| set | n | nl chars | oracle clauses/q | numbered req list | parse P | parse R | parse F1 | clause coverage | parse-gap clauses | C-LPR ceiling (parse gap) | queries w/ parse gap | FPR ceiling (parse gap) |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in report["sets"]:
        inv, fp, cc = s["inventory"], s["family_parse"], s["clause_coverage"]
        lines.append(
            f"| {s['label']} | {s['n']} | {inv['nl_chars_mean']} | {inv['oracle_clauses_mean']} | "
            f"{inv['pct_with_numbered_requirements_list']}% | {fp['precision']} | {fp['recall']} | "
            f"{fp['f1']} | {cc['clause_coverage']} | "
            f"{cc['n_parse_gap']}/{cc['n_oracle_clauses']} ({100.0*cc['parse_gap_rate']:.1f}%) | "
            f"{cc['clpr_ceiling_parse_gap_only']} | {cc['pct_queries_with_parse_gap']}% | "
            f"{cc['fpr_ceiling_from_parse_gaps']} |"
        )
    return "\n".join(lines)


def render_fix_markdown(report: dict) -> str:
    rows = report.get("fix_headroom") or []
    if not rows:
        return ""
    lines = [f"Headroom if `{'`, `'.join(rows[0]['fix_kinds'])}` were extracted correctly:",
             "",
             "| set | parse-gap clauses | queries w/ gap | C-LPR ceiling | FPR ceiling | residual (ASCII-literal only) |",
             "| --- | --- | --- | --- | --- | --- |"]
    for h in rows:
        lines.append(
            f"| {h['label']} | {h['parse_gap']} -> {h['parse_gap_after_fix']} | "
            f"{h['queries_with_gap']} -> {h['queries_with_gap_after_fix']} | "
            f"{h['clpr_ceiling_now']} -> {h['clpr_ceiling_after_fix']} | "
            f"{h['fpr_ceiling_now']} -> {h['fpr_ceiling_after_fix']} | "
            f"{h['residual_by_kind_ascii_literal_only'] or '{}'} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
