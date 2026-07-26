#!/usr/bin/env python3
"""Size the Phase 2 *commonsense-first* lever offline from a committed baseline row.

Why this exists: ``eval_tpc.py`` scores C-LPR as ``conditional_micro_logi`` from
``evaluate_hard_constraints_v2(..., env_pass_id=commonsense_pass_id)`` -- the per-clause logical
credit of a query is counted **only if that query also passes the commonsense checker**, while the
denominator stays the full clause count of the batch (see
``chinatravel/evaluation/hard_constraint.py``). EPR-macro is likewise all-or-nothing per query. So a
commonsense-invalid emitted plan throws away its logical partial credit (weight ``0.25``) *and* its
EPR-macro point (weight ``0.10``) even when its logical verdicts are mostly passing.

This script quantifies that loss from an already-committed row: no re-solve, no LLM, no network. It
reads local oracle-derived per-clause verdicts to *attribute a rehearsal*, which the operating rules
allow (docs/tpc_phase2_roadmap.md, rule 1); it is diagnostic tooling, never a promotable measurement.

Secondary output: the DAV/ATT/DDR of the all-pass plans, because ``eval_tpc.cal_default_pr_score``
averages preference **only over ``all_pass_id``** -- that caps what any packing/densify work can be
worth and decides whether it deserves time at all.

Usage:
    .venv/bin/python scripts/phase2_commonsense_headroom.py
    .venv/bin/python scripts/phase2_commonsense_headroom.py --mode end-to-end
    .venv/bin/python scripts/phase2_commonsense_headroom.py --row results/phase2_baselines/runs/<id>.json
    .venv/bin/python scripts/phase2_commonsense_headroom.py --json out.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_ROW = str(PROJECT_ROOT / "results/phase2_baselines/runs/20260724T192503Z.json")
MODES = ("end-to-end", "solver-only")

# Official overall weights (eval_tpc.py): 0.10 MicEPR + 0.10 MacEPR + 0.25 C-LPR + 0.40 FPR
# + 0.05 DAV + 0.05 ATT + 0.05 DDR.
W_MIC_EPR = 0.10
W_MAC_EPR = 0.10
W_CLPR = 0.25
W_FPR = 0.40
W_PREF_EACH = 0.05

MEAL_TYPES = ("breakfast", "lunch", "dinner")


# --- pure helpers (unit-tested) --------------------------------------------------------------


def _is_nan(value) -> bool:
    return isinstance(value, float) and math.isnan(value)


def logical_counts(logical_row: dict) -> tuple[int, int]:
    """Return ``(passed, applicable)`` clause counts for one ``logical_details`` row.

    ``logic_py_<N>`` values are ``1``/``0`` for real clauses and ``NaN`` for right-padding of the
    batch-wide widest query, exactly as ``evaluate_hard_constraints_v2`` builds the frame. Padding
    must not enter either count.
    """
    passed = applicable = 0
    for key, value in (logical_row or {}).items():
        if not key.startswith("logic_py_"):
            continue
        if value is None or _is_nan(value):
            continue
        applicable += 1
        try:
            passed += 1 if int(value) == 1 else 0
        except (TypeError, ValueError):
            continue
    return passed, applicable


def failed_commonsense_columns(commonsense_row: dict) -> list[str]:
    """Names of the official commonsense columns that failed (value ``1``) for one uid."""
    failed = []
    for key, value in (commonsense_row or {}).items():
        if key == "data_id":
            continue
        try:
            if int(value) == 1:
                failed.append(key)
        except (TypeError, ValueError):
            continue
    return failed


def project_commonsense_first(raw: dict) -> dict:
    """Project the score effect of making every commonsense-failing plan commonsense-valid.

    Holds each query's logical verdicts, the FPR, and the preference metrics fixed; only the
    commonsense gate flips. Under that hypothesis C-LPR rises to the unconditional ``logical_micro``
    (the conditional numerator gains exactly the clauses of the previously-excluded queries while the
    denominator is unchanged), and both EPR terms become ``100``.

    Returns a dict of observed values, projected values, and the implied per-weight deltas.
    """
    commonsense_details = raw.get("commonsense_details") or []
    logical_details = raw.get("logical_details") or []
    logical_by_uid = {row.get("data_id"): row for row in logical_details}

    failing = []
    for row in commonsense_details:
        uid = row.get("data_id")
        failed_cols = failed_commonsense_columns(row)
        if not failed_cols:
            continue
        passed, applicable = logical_counts(logical_by_uid.get(uid, {}))
        failing.append(
            {
                "uid": uid,
                "failed_columns": failed_cols,
                "logic_passed": passed,
                "logic_applicable": applicable,
                "logic_fraction": (passed / applicable) if applicable else None,
            }
        )

    observed_mic_epr = float(raw.get("commonsense_micro", 0.0) or 0.0)
    observed_mac_epr = float(raw.get("commonsense_macro", 0.0) or 0.0)
    observed_clpr = float(raw.get("conditional_logical_micro", 0.0) or 0.0)
    logical_micro = float(raw.get("logical_micro", 0.0) or 0.0)

    # C-LPR ceiling under the hypothesis == unconditional logical micro.
    projected_clpr = logical_micro
    delta_clpr = W_CLPR * (projected_clpr - observed_clpr)
    delta_mac_epr = W_MAC_EPR * (100.0 - observed_mac_epr)
    delta_mic_epr = W_MIC_EPR * (100.0 - observed_mic_epr)

    return {
        "n": len(commonsense_details),
        "commonsense_pass_count": raw.get("commonsense_pass_count"),
        "failing": failing,
        "observed": {
            "mic_epr": observed_mic_epr,
            "mac_epr": observed_mac_epr,
            "clpr": observed_clpr,
            "logical_micro": logical_micro,
            "fpr": float(raw.get("all_pass_count", 0) or 0)
            / max(len(commonsense_details), 1)
            * 100.0,
        },
        "projected": {
            "mic_epr": 100.0,
            "mac_epr": 100.0,
            "clpr": projected_clpr,
        },
        "delta_overall": {
            "clpr": delta_clpr,
            "mac_epr": delta_mac_epr,
            "mic_epr": delta_mic_epr,
            "total": delta_clpr + delta_mac_epr + delta_mic_epr,
            "total_conservative_mic_epr_held": delta_clpr + delta_mac_epr,
        },
    }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _minutes(time_str: str) -> float | None:
    try:
        hours, minutes = str(time_str).split("次日")[-1].split(":")
        return float(hours) * 60.0 + float(minutes)
    except Exception:
        return None


def preference_scores(plan: dict) -> dict | None:
    """Per-plan DAV/ATT/DDR using eval_tpc's DEFAULT_PR formulas.

    DAV = attractions / (4 * days); ATT = (-1/105) * mean innercity leg minutes + 8/7;
    DDR = (meals / days) / 3. Each clamped to [0, 1] like ``_clamp_score`` in ``eval_tpc.py``.
    """
    itinerary = (plan or {}).get("itinerary")
    if not isinstance(itinerary, list) or not itinerary:
        return None

    days = len(itinerary)
    attractions = meals = 0
    leg_minutes_total = 0.0
    activities_with_transport = 0

    for day in itinerary:
        for activity in (day or {}).get("activities", []) or []:
            if not isinstance(activity, dict):
                continue
            act_type = activity.get("type")
            if act_type == "attraction":
                attractions += 1
            elif act_type in MEAL_TYPES:
                meals += 1
            transports = activity.get("transports") or []
            if transports:
                activities_with_transport += 1
                for leg in transports:
                    start = _minutes((leg or {}).get("start_time"))
                    end = _minutes((leg or {}).get("end_time"))
                    if start is not None and end is not None:
                        leg_minutes_total += end - start

    avg_leg = (leg_minutes_total / activities_with_transport) if activities_with_transport else -1.0
    return {
        "dav": _clamp01(attractions / (4.0 * days)),
        "att": _clamp01((-1.0 / 105.0) * avg_leg + 8.0 / 7.0),
        "ddr": _clamp01((meals / days) / 3.0),
        "attractions": attractions,
        "meals": meals,
        "days": days,
    }


# --- reporting -------------------------------------------------------------------------------


def _mode_raw(row: dict, mode: str) -> dict | None:
    modes = ((row.get("rehearsal") or {}).get("modes") or {})
    entry = modes.get(mode)
    if not isinstance(entry, dict):
        return None
    raw = entry.get("raw")
    return raw if isinstance(raw, dict) else None


def _report_mode(row: dict, mode: str, *, results_dir: Path, verbose: bool) -> dict | None:
    raw = _mode_raw(row, mode)
    if raw is None:
        print(f"\n[{mode}] not present in this row; skipped.")
        return None

    projection = project_commonsense_first(raw)
    obs, proj, delta = projection["observed"], projection["projected"], projection["delta_overall"]

    print(f"\n=== {mode} (n={projection['n']}) ===")
    print(
        f"commonsense pass {projection['commonsense_pass_count']}/{projection['n']}, "
        f"{len(projection['failing'])} failing plan(s)"
    )
    if verbose and projection["failing"]:
        print(f"{'uid':<52} {'logic':>9}  failed commonsense columns")
        for item in sorted(projection["failing"], key=lambda d: -(d["logic_fraction"] or 0.0)):
            frac = item["logic_fraction"]
            frac_str = "n/a" if frac is None else f"{item['logic_passed']}/{item['logic_applicable']}"
            print(f"{str(item['uid']):<52} {frac_str:>9}  {', '.join(item['failed_columns'])}")

    print(
        "\nobserved   MicEPR {:.2f}  MacEPR {:.2f}  C-LPR {:.2f}  (logical_micro {:.2f}, FPR {:.2f})".format(
            obs["mic_epr"], obs["mac_epr"], obs["clpr"], obs["logical_micro"], obs["fpr"]
        )
    )
    print(
        "projected  MicEPR {:.2f}  MacEPR {:.2f}  C-LPR {:.2f}   [FPR and preference held fixed]".format(
            proj["mic_epr"], proj["mac_epr"], proj["clpr"]
        )
    )
    print(
        "overall delta: C-LPR {:+.2f} + MacEPR {:+.2f} + MicEPR {:+.2f} = {:+.2f} "
        "({:+.2f} if MicEPR held)".format(
            delta["clpr"],
            delta["mac_epr"],
            delta["mic_epr"],
            delta["total"],
            delta["total_conservative_mic_epr_held"],
        )
    )

    preference = _report_preference(raw, results_dir=results_dir, mode=mode)
    projection["preference"] = preference
    return projection


def _report_preference(raw: dict, *, results_dir: Path, mode: str) -> dict | None:
    all_pass_ids = raw.get("all_pass_ids") or []
    if not all_pass_ids:
        return None

    scored, skipped = [], 0
    for uid in all_pass_ids:
        path = results_dir / f"{uid}.json"
        if not path.exists():
            skipped += 1
            continue
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            skipped += 1
            continue
        scores = preference_scores(plan)
        if scores is None:
            skipped += 1
            continue
        scored.append(scores)

    if not scored:
        print(
            f"\npreference: no plan files readable under {results_dir} "
            f"({skipped} skipped) -- cannot size the packing option for {mode}."
        )
        return None

    mean_dav = sum(s["dav"] for s in scored) / len(scored) * 100.0
    mean_att = sum(s["att"] for s in scored) / len(scored) * 100.0
    mean_ddr = sum(s["ddr"] for s in scored) / len(scored) * 100.0
    # Two accounting conventions, and they differ by the pass rate:
    #   * eval_tpc's official aggregate averages DAV/ATT/DDR over all-pass queries *only* and then
    #     applies 0.05 each, so perfecting them is worth the full 0.05*(300 - sum).
    #   * the rehearsal row's overall_true is a mean of per-query weighted scores, where a failing
    #     query contributes 0 preference, so the same work moves that number by pass_rate x as much.
    pass_rate = len(all_pass_ids) / max(len(raw.get("commonsense_details") or []), 1)
    headroom_official = W_PREF_EACH * (300.0 - (mean_dav + mean_att + mean_ddr))
    headroom_per_query_mean = headroom_official * pass_rate

    print(
        "\npreference on all-pass plans (n={}, {} skipped): DAV {:.2f}  ATT {:.2f}  DDR {:.2f}".format(
            len(scored), skipped, mean_dav, mean_att, mean_ddr
        )
    )
    print(
        "packing headroom if perfected: {:.2f} points on eval_tpc's official aggregate "
        "(preference averaged over all-pass queries only), {:.2f} on this row's per-query "
        "overall_true mean at a {:.0%} pass rate".format(
            headroom_official, headroom_per_query_mean, pass_rate
        )
    )
    return {
        "n_scored": len(scored),
        "skipped": skipped,
        "dav": mean_dav,
        "att": mean_att,
        "ddr": mean_ddr,
        "headroom_official_points": headroom_official,
        "headroom_per_query_mean_points": headroom_per_query_mean,
        "pass_rate": pass_rate,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--row", default=DEFAULT_ROW, help="committed baseline row JSON")
    parser.add_argument("--mode", choices=(*MODES, "both"), default="both")
    parser.add_argument(
        "--results-dir",
        default=None,
        help="directory of emitted plans for the preference sizing "
        "(default results/phase2_e2e_<split_name>)",
    )
    parser.add_argument("--json", default=None, help="also write the machine-readable projection here")
    parser.add_argument(
        "--quiet", action="store_true", help="omit the per-uid table, print aggregates only"
    )
    args = parser.parse_args()

    row_path = Path(args.row)
    if not row_path.is_absolute():
        row_path = PROJECT_ROOT / row_path
    row = json.loads(row_path.read_text(encoding="utf-8"))

    split_name = row.get("split_name", "")
    results_dir = (
        Path(args.results_dir)
        if args.results_dir
        else PROJECT_ROOT / "results" / f"phase2_e2e_{split_name}"
    )

    print(f"row: {os.path.relpath(row_path, PROJECT_ROOT)}")
    print(
        f"split {split_name}  sha {str(row.get('git_sha', ''))[:8]}  "
        f"budget {row.get('budget_sec')}s  repeats {row.get('repeats')}"
    )
    print(
        "\nAssumption: every commonsense-failing plan becomes commonsense-valid with its logical\n"
        "verdicts, the FPR, and the preference metrics unchanged. That is the ceiling of the\n"
        "commonsense-first lever, not a prediction of what one evening captures."
    )

    modes = MODES if args.mode == "both" else (args.mode,)
    out: dict = {"row": str(row_path), "modes": {}}
    for mode in modes:
        projection = _report_mode(row, mode, results_dir=results_dir, verbose=not args.quiet)
        if projection is not None:
            out["modes"][mode] = projection

    e2e = out["modes"].get("end-to-end")
    if e2e is not None:
        quality = (((row.get("rehearsal") or {}).get("modes") or {}).get("end-to-end") or {}).get(
            "quality"
        ) or {}
        baseline_overall = float((quality.get("overall_true") or {}).get("mean", 0.0) or 0.0)
        delta = e2e["delta_overall"]["total"]
        print(
            "\nprojected overall_true {:.2f} -> {:.2f} (commonsense lever, logic held)".format(
                baseline_overall, baseline_overall + delta
            )
        )
        print(
            "  (row overall_true is a mean of per-query weighted scores, so this component-level\n"
            "   projection is a sizing estimate, not an exact recomputation)"
        )
        out["projected_overall_true"] = baseline_overall + delta
        out["baseline_overall_true"] = baseline_overall

    if args.json:
        json_path = Path(args.json)
        if not json_path.is_absolute():
            json_path = PROJECT_ROOT / json_path
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {os.path.relpath(json_path, PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
