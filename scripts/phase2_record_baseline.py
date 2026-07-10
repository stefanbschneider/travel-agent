#!/usr/bin/env python3
# pyright: reportMissingImports=false
"""Run and persist a deterministic Phase 2 baseline snapshot.

This script establishes a reproducible baseline run on a validation fold, then stores
compact, commit-friendly trend artifacts under docs/phase2_baselines/:

- history.jsonl: append-only one JSON object per run
- history.csv: tabular projection for quick diffing/plotting
- latest.json: full latest run record
- latest.md: human-readable latest summary

Raw per-query artifacts remain in existing run/result paths managed by the harness.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "chinatravel") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "chinatravel"))


def _load_script_module(module_name: str, rel_path: str):
    module_path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module {module_name} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


split_mod = _load_script_module("make_phase2_splits", "scripts/make_phase2_splits.py")
parser_mod = _load_script_module("parser_vs_oracle", "scripts/parser_vs_oracle.py")
timing_mod = _load_script_module("phase2_timing", "scripts/phase2_timing.py")
rehearse_mod = _load_script_module("rehearse_phase2", "scripts/rehearse_phase2.py")


DEFAULT_HISTORY_DIR = PROJECT_ROOT / "docs" / "phase2_baselines"
HISTORY_JSONL = "history.jsonl"
HISTORY_CSV = "history.csv"
LATEST_JSON = "latest.json"
LATEST_MD = "latest.md"


@dataclass
class FoldSelection:
    split_name: str
    uids: list[str]


def _utc_now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True
        ).strip()
        return out
    except Exception:
        return "unknown"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_fold(split_set: str, fold: int, folds: int, seed: int, limit: int | None) -> FoldSelection:
    split_name, _is_test = rehearse_mod.resolve_split_set(split_set)
    uids = split_mod.read_split(split_name)
    selected = rehearse_mod.select_fold(uids, fold=fold, folds=folds, seed=seed)
    if limit is not None:
        selected = selected[: int(limit)]
    return FoldSelection(split_name=split_name, uids=selected)


def _collect_selected_telemetry(method: str, uids: list[str]) -> tuple[list[dict], list[str]]:
    run_root = PROJECT_ROOT / "agent_env" / "runs" / method
    telemetries: list[dict] = []
    missing: list[str] = []
    for uid in uids:
        tp = run_root / uid / "telemetry.json"
        if not tp.exists():
            missing.append(uid)
            continue
        try:
            telemetries.append(_load_json(tp))
        except Exception:
            missing.append(uid)
    return telemetries, missing


def _to_history_row(record: dict[str, Any]) -> dict[str, Any]:
    rehearsal = record.get("rehearsal", {})
    modes = rehearsal.get("modes", {})
    ceiling = float(rehearsal.get("ceiling", {}).get("fpr", 0.0))
    solver = float(modes.get("solver-only", {}).get("fpr", 0.0))
    e2e = float(modes.get("end-to-end", {}).get("fpr", 0.0))

    parser = record.get("parser", {})
    behavioral = parser.get("behavioral", {}) if isinstance(parser, dict) else {}

    timing = record.get("timing", {})
    stage = timing.get("per_stage", {}) if isinstance(timing, dict) else {}

    return {
        "run_id": record.get("run_id", ""),
        "timestamp_utc": record.get("timestamp_utc", ""),
        "git_sha": record.get("git_sha", ""),
        "split_set": record.get("split_set", ""),
        "split_name": record.get("split_name", ""),
        "fold": int(record.get("fold", 0)),
        "folds": int(record.get("folds", 0)),
        "seed": int(record.get("seed", 0)),
        "limit": record.get("limit"),
        "n": int(record.get("n", 0)),
        "budget_sec": float(record.get("budget_sec", 0.0)),
        "ceiling_fpr": ceiling,
        "solver_only_fpr": solver,
        "end_to_end_fpr": e2e,
        "solver_headroom": ceiling - solver,
        "parsing_loss": solver - e2e,
        "parser_precision": float(parser.get("precision", 0.0)),
        "parser_recall": float(parser.get("recall", 0.0)),
        "parser_f1": float(parser.get("f1", 0.0)),
        "parser_value_accuracy": float(parser.get("value_accuracy", 0.0)),
        "parser_disjunction_flattened": int(parser.get("disjunction_flattened", 0)),
        "behavioral_agreement_rate": float(behavioral.get("agreement_rate", 0.0)),
        "timing_total_p50": float(timing.get("total_p50", 0.0)),
        "timing_total_p95": float(timing.get("total_p95", 0.0)),
        "timing_valid_output_rate": float(timing.get("valid_output_rate", 0.0)),
        "timing_timed_out": int(timing.get("timed_out", 0)),
        "timing_used_fallback": int(timing.get("used_fallback", 0)),
        "timing_budget_overruns": int(timing.get("budget_overruns", 0)),
        "timing_parse_p95": float(stage.get("parse", {}).get("p95", 0.0)),
        "timing_solve_p95": float(stage.get("solve", {}).get("p95", 0.0)),
        "timing_improve_p95": float(stage.get("improve", {}).get("p95", 0.0)),
        "timing_finalize_p95": float(stage.get("finalize", {}).get("p95", 0.0)),
    }


def _read_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _write_history_csv(path: Path, records: list[dict[str, Any]]) -> None:
    rows = [_to_history_row(r) for r in records]
    fieldnames = [
        "run_id",
        "timestamp_utc",
        "git_sha",
        "split_set",
        "split_name",
        "fold",
        "folds",
        "seed",
        "limit",
        "n",
        "budget_sec",
        "ceiling_fpr",
        "solver_only_fpr",
        "end_to_end_fpr",
        "solver_headroom",
        "parsing_loss",
        "parser_precision",
        "parser_recall",
        "parser_f1",
        "parser_value_accuracy",
        "parser_disjunction_flattened",
        "behavioral_agreement_rate",
        "timing_total_p50",
        "timing_total_p95",
        "timing_valid_output_rate",
        "timing_timed_out",
        "timing_used_fallback",
        "timing_budget_overruns",
        "timing_parse_p95",
        "timing_solve_p95",
        "timing_improve_p95",
        "timing_finalize_p95",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_latest_md(path: Path, record: dict[str, Any]) -> None:
    rehearsal = record.get("rehearsal", {})
    modes = rehearsal.get("modes", {})
    ceiling = float(rehearsal.get("ceiling", {}).get("fpr", 0.0))
    solver = float(modes.get("solver-only", {}).get("fpr", 0.0))
    e2e = float(modes.get("end-to-end", {}).get("fpr", 0.0))

    parser = record.get("parser", {})
    behavioral = parser.get("behavioral", {}) if isinstance(parser, dict) else {}
    timing = record.get("timing", {})

    lines = [
        "# Phase 2 Baseline (Latest)",
        "",
        f"- run_id: {record.get('run_id', '')}",
        f"- timestamp_utc: {record.get('timestamp_utc', '')}",
        f"- git_sha: {record.get('git_sha', '')}",
        f"- split: {record.get('split_name', '')} (set={record.get('split_set', '')}, fold={record.get('fold', 0)}/{record.get('folds', 0)}, n={record.get('n', 0)})",
        f"- budget_sec: {record.get('budget_sec', 0.0)}",
        "",
        "## Rehearsal Attribution (FPR)",
        "",
        f"- ceiling_fpr: {ceiling:.4f}",
        f"- solver_only_fpr: {solver:.4f}",
        f"- end_to_end_fpr: {e2e:.4f}",
        f"- solver_headroom: {ceiling - solver:.4f}",
        f"- parsing_loss: {solver - e2e:.4f}",
        "",
        "## Parser Vs Oracle",
        "",
        f"- precision: {float(parser.get('precision', 0.0)):.4f}",
        f"- recall: {float(parser.get('recall', 0.0)):.4f}",
        f"- f1: {float(parser.get('f1', 0.0)):.4f}",
        f"- value_accuracy: {float(parser.get('value_accuracy', 0.0)):.4f}",
        f"- disjunction_flattened: {int(parser.get('disjunction_flattened', 0))}",
        f"- behavioral_agreement_rate: {float(behavioral.get('agreement_rate', 0.0)):.4f}",
        "",
        "## Timing And Reliability",
        "",
        f"- total_p50_sec: {float(timing.get('total_p50', 0.0)):.4f}",
        f"- total_p95_sec: {float(timing.get('total_p95', 0.0)):.4f}",
        f"- valid_output_rate: {float(timing.get('valid_output_rate', 0.0)):.4f}",
        f"- timed_out: {int(timing.get('timed_out', 0))}",
        f"- used_fallback: {int(timing.get('used_fallback', 0))}",
        f"- budget_overruns: {int(timing.get('budget_overruns', 0))}",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split-set", choices=["val", "test"], default="val")
    p.add_argument("--fold", type=int, default=0)
    p.add_argument("--folds", type=int, default=rehearse_mod.DEFAULT_FOLDS)
    p.add_argument("--seed", type=int, default=rehearse_mod.DEFAULT_SEED)
    p.add_argument("--budget-sec", type=float, default=120.0)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--lang", choices=["en", "zh"], default="en")
    p.add_argument("--run-id", default=None)
    p.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR))
    p.add_argument(
        "--branch-aware",
        action="store_true",
        help="Use branch-aware parser-vs-oracle scoring (paired branch matching).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    split_mod.write_splits(
        split_mod.read_split(split_mod.SOURCE_SPLIT),
        force=False,
    )

    run_id = args.run_id or _utc_now_id()
    timestamp_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")

    fold_info = _resolve_fold(
        split_set=args.split_set,
        fold=args.fold,
        folds=args.folds,
        seed=args.seed,
        limit=args.limit,
    )

    rehearsal = rehearse_mod.rehearse(
        modes=("end-to-end", "solver-only"),
        split_set=args.split_set,
        fold=args.fold,
        folds=args.folds,
        seed=args.seed,
        budget_sec=args.budget_sec,
        limit=args.limit,
        lang=args.lang,
    )

    parser = parser_mod.run_report(
        fold_info.split_name,
        uids=fold_info.uids,
        behavioral=True,
        lang=args.lang,
        disjunction=True,
        branch_aware=args.branch_aware,
    )

    e2e_method = f"phase2_e2e_{fold_info.split_name}"
    telemetries, missing = _collect_selected_telemetry(e2e_method, fold_info.uids)
    timing = timing_mod.aggregate_timings(telemetries, budget_sec=args.budget_sec)

    record = {
        "run_id": run_id,
        "timestamp_utc": timestamp_utc,
        "git_sha": _git_sha(),
        "split_set": args.split_set,
        "split_name": fold_info.split_name,
        "fold": args.fold,
        "folds": args.folds,
        "seed": args.seed,
        "budget_sec": float(args.budget_sec),
        "limit": args.limit,
        "n": len(fold_info.uids),
        "lang": args.lang,
        "branch_aware": bool(args.branch_aware),
        "rehearsal": rehearsal,
        "parser": parser,
        "timing": timing,
        "timing_source": {
            "method": e2e_method,
            "selected_uids": len(fold_info.uids),
            "telemetry_found": len(telemetries),
            "telemetry_missing": len(missing),
            "missing_uids": missing[:20],
        },
    }

    history_dir = Path(args.history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / HISTORY_JSONL
    csv_path = history_dir / HISTORY_CSV
    latest_json = history_dir / LATEST_JSON
    latest_md = history_dir / LATEST_MD
    runs_dir = history_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    with history_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    full_history = _read_history(history_path)
    _write_history_csv(csv_path, full_history)

    latest_json.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_latest_md(latest_md, record)
    (runs_dir / f"{run_id}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(_to_history_row(record), ensure_ascii=False, indent=2))
    print(f"Wrote: {history_path}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {latest_json}")
    print(f"Wrote: {latest_md}")
    print(f"Wrote: {runs_dir / f'{run_id}.json'}")


if __name__ == "__main__":
    main()
