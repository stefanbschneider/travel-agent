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
runner_mod = _load_script_module("solve_phase2", "agent_env/scripts/solve_phase2.py")


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


def _count_parse_failures(telemetries: list[dict]) -> dict[str, int]:
    n = len(telemetries)
    parse_failed = 0
    for t in telemetries:
        err = str(t.get("error") or "")
        if "parse:" in err:
            parse_failed += 1
    return {
        "n": n,
        "completed": n - parse_failed,
        "failed": parse_failed,
        "timed_out": sum(1 for t in telemetries if bool(t.get("parse_timed_out"))),
    }


def _completion_summary(telemetries: list[dict]) -> dict[str, float | int]:
    n = len(telemetries)
    if n == 0:
        return {
            "n": 0,
            "completed_without_timeout": 0,
            "interrupted": 0,
            "timed_out": 0,
            "recovered_from_timeout": 0,
            "recovered_from_error": 0,
            "used_fallback": 0,
            "valid_output": 0,
            "completed_without_timeout_rate": 0.0,
        }

    completed_without_timeout = 0
    timed_out = 0
    recovered_from_timeout = 0
    recovered_from_error = 0
    used_fallback = 0
    valid_output = 0

    for t in telemetries:
        to = bool(t.get("timed_out"))
        err = t.get("error")
        done = t.get("completed_without_timeout")
        if done is None:
            done = (not to) and (err in (None, ""))

        completed_without_timeout += 1 if bool(done) else 0
        timed_out += 1 if to else 0
        recovered_from_timeout += 1 if bool(t.get("solve_recovered_from_timeout") or t.get("recovered_from_timeout")) else 0
        recovered_from_error += 1 if bool(t.get("solve_recovered_from_error") or t.get("recovered_from_error")) else 0
        used_fallback += 1 if bool(t.get("used_fallback")) else 0
        valid_output += 1 if bool(t.get("valid_output")) else 0

    interrupted = n - completed_without_timeout
    return {
        "n": n,
        "completed_without_timeout": completed_without_timeout,
        "interrupted": interrupted,
        "timed_out": timed_out,
        "recovered_from_timeout": recovered_from_timeout,
        "recovered_from_error": recovered_from_error,
        "used_fallback": used_fallback,
        "valid_output": valid_output,
        "completed_without_timeout_rate": float(completed_without_timeout) / float(n),
    }


def _repeat_scores(rehearsal: dict[str, Any]) -> dict[str, float]:
    """Extract the four headline scores from one rehearsal report (for variance across repeats)."""
    modes = rehearsal.get("modes", {})
    return {
        "e2e_fpr": float(modes.get("end-to-end", {}).get("fpr", 0.0)),
        "solver_only_fpr": float(modes.get("solver-only", {}).get("fpr", 0.0)),
        "e2e_overall_true": float(
            modes.get("end-to-end", {}).get("quality", {}).get("overall_true", {}).get("mean", 0.0)
        ),
        "solver_only_overall_true": float(
            modes.get("solver-only", {}).get("quality", {}).get("overall_true", {}).get("mean", 0.0)
        ),
    }


def _variance_summary(rehearsals: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean/std of the headline scores across repeat runs.

    The organizers run each harness 5x and average, so run-to-run score variance is a
    first-class metric even on the deterministic path (budget-boundary effects).
    """
    import statistics

    per_repeat = [_repeat_scores(r) for r in rehearsals]
    keys = ["e2e_fpr", "solver_only_fpr", "e2e_overall_true", "solver_only_overall_true"]
    summary: dict[str, Any] = {"repeats": len(per_repeat), "per_repeat": per_repeat}
    for key in keys:
        vals = [r[key] for r in per_repeat]
        summary[f"{key}_mean"] = statistics.fmean(vals) if vals else 0.0
        summary[f"{key}_std"] = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return summary


def _to_history_row(record: dict[str, Any]) -> dict[str, Any]:
    rehearsal = record.get("rehearsal", {})
    modes = rehearsal.get("modes", {})
    ceiling = float(rehearsal.get("ceiling", {}).get("fpr", 0.0))
    solver = float(modes.get("solver-only", {}).get("fpr", 0.0))
    e2e = float(modes.get("end-to-end", {}).get("fpr", 0.0))
    ceiling_quality = rehearsal.get("ceiling", {}).get("quality", {})
    solver_quality = modes.get("solver-only", {}).get("quality", {})
    e2e_quality = modes.get("end-to-end", {}).get("quality", {})

    ceiling_overall_true = float(
        ceiling_quality.get("overall_true", {}).get("mean", 0.0)
    )
    solver_overall_true = float(
        solver_quality.get("overall_true", {}).get("mean", 0.0)
    )
    e2e_overall_true = float(
        e2e_quality.get("overall_true", {}).get("mean", 0.0)
    )

    ceiling_overall_parsed = float(
        ceiling_quality.get("overall_parsed", {}).get("mean", 0.0)
    )
    solver_overall_parsed = float(
        solver_quality.get("overall_parsed", {}).get("mean", 0.0)
    )
    e2e_overall_parsed = float(
        e2e_quality.get("overall_parsed", {}).get("mean", 0.0)
    )

    parser = record.get("parser", {})
    behavioral = parser.get("behavioral", {}) if isinstance(parser, dict) else {}

    parser_full = record.get("parser_full", {})
    parser_full_behavioral = (
        parser_full.get("behavioral", {}) if isinstance(parser_full, dict) else {}
    )

    llm_config = record.get("llm_config", {}) if isinstance(record, dict) else {}
    llm_backend = str(llm_config.get("backend") or "none")

    timing = record.get("timing", {})
    stage = timing.get("per_stage", {}) if isinstance(timing, dict) else {}
    completion = record.get("completion", {}) if isinstance(record, dict) else {}
    parse_completion = completion.get("parse", {}) if isinstance(completion, dict) else {}
    e2e_completion = completion.get("end_to_end", {}) if isinstance(completion, dict) else {}
    solver_completion = completion.get("solver_only", {}) if isinstance(completion, dict) else {}

    variance = record.get("variance", {}) if isinstance(record, dict) else {}

    return {
        "run_id": record.get("run_id", ""),
        "timestamp_utc": record.get("timestamp_utc", ""),
        "git_sha": record.get("git_sha", ""),
        "label": record.get("label", ""),
        "repeats": int(record.get("repeats", 1) or 1),
        "fresh": bool(record.get("fresh", False)),
        "e2e_fpr_std": float(variance.get("e2e_fpr_std", 0.0)),
        "solver_only_fpr_std": float(variance.get("solver_only_fpr_std", 0.0)),
        "e2e_overall_true_std": float(variance.get("e2e_overall_true_std", 0.0)),
        "solver_only_overall_true_std": float(variance.get("solver_only_overall_true_std", 0.0)),
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
        "ceiling_overall_true": ceiling_overall_true,
        "solver_only_overall_true": solver_overall_true,
        "end_to_end_overall_true": e2e_overall_true,
        "overall_true_solver_headroom": ceiling_overall_true - solver_overall_true,
        "overall_true_parsing_loss": solver_overall_true - e2e_overall_true,
        "ceiling_overall_parsed": ceiling_overall_parsed,
        "solver_only_overall_parsed": solver_overall_parsed,
        "end_to_end_overall_parsed": e2e_overall_parsed,
        "overall_parsed_solver_headroom": ceiling_overall_parsed - solver_overall_parsed,
        "overall_parsed_parsing_loss": solver_overall_parsed - e2e_overall_parsed,
        "parser_precision": float(parser.get("precision", 0.0)),
        "parser_recall": float(parser.get("recall", 0.0)),
        "parser_f1": float(parser.get("f1", 0.0)),
        "parser_value_accuracy": float(parser.get("value_accuracy", 0.0)),
        "parser_disjunction_flattened": int(parser.get("disjunction_flattened", 0)),
        "behavioral_agreement_rate": float(behavioral.get("agreement_rate", 0.0)),
        "parser_full_n": int(parser_full.get("n", 0)),
        "parser_full_precision": float(parser_full.get("precision", 0.0)),
        "parser_full_recall": float(parser_full.get("recall", 0.0)),
        "parser_full_f1": float(parser_full.get("f1", 0.0)),
        "parser_full_value_accuracy": float(parser_full.get("value_accuracy", 0.0)),
        "parser_full_disjunction_flattened": int(parser_full.get("disjunction_flattened", 0)),
        "parser_full_behavioral_agreement_rate": float(
            parser_full_behavioral.get("agreement_rate", 0.0)
        ),
        "llm_backend": llm_backend,
        "llm_parse": llm_backend != "none",
        "timing_total_p50": float(timing.get("total_p50", 0.0)),
        "timing_total_p95": float(timing.get("total_p95", 0.0)),
        "timing_valid_output_rate": float(timing.get("valid_output_rate", 0.0)),
        "timing_timed_out": int(timing.get("timed_out", 0)),
        "timing_used_fallback": int(timing.get("used_fallback", 0)),
        "timing_budget_overruns": int(timing.get("budget_overruns", 0)),
        "timing_llm_parse_attempted": int(timing.get("llm_parse_attempted", 0)),
        "timing_llm_parse_failed": int(timing.get("llm_parse_failed", 0)),
        "timing_parse_p95": float(stage.get("parse", {}).get("p95", 0.0)),
        "timing_solve_p95": float(stage.get("solve", {}).get("p95", 0.0)),
        "timing_improve_p95": float(stage.get("improve", {}).get("p95", 0.0)),
        "timing_finalize_p95": float(stage.get("finalize", {}).get("p95", 0.0)),
        "parse_completed": int(parse_completion.get("completed", 0)),
        "parse_failed": int(parse_completion.get("failed", 0)),
        "parse_timed_out": int(parse_completion.get("timed_out", 0)),
        "e2e_completed_without_timeout": int(e2e_completion.get("completed_without_timeout", 0)),
        "e2e_timed_out": int(e2e_completion.get("timed_out", 0)),
        "solver_completed_without_timeout": int(solver_completion.get("completed_without_timeout", 0)),
        "solver_timed_out": int(solver_completion.get("timed_out", 0)),
        "solver_recovered_from_timeout": int(solver_completion.get("recovered_from_timeout", 0)),
        "solver_used_fallback": int(solver_completion.get("used_fallback", 0)),
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
        "label",
        "repeats",
        "fresh",
        "e2e_fpr_std",
        "solver_only_fpr_std",
        "e2e_overall_true_std",
        "solver_only_overall_true_std",
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
        "ceiling_overall_true",
        "solver_only_overall_true",
        "end_to_end_overall_true",
        "overall_true_solver_headroom",
        "overall_true_parsing_loss",
        "ceiling_overall_parsed",
        "solver_only_overall_parsed",
        "end_to_end_overall_parsed",
        "overall_parsed_solver_headroom",
        "overall_parsed_parsing_loss",
        "parser_precision",
        "parser_recall",
        "parser_f1",
        "parser_value_accuracy",
        "parser_disjunction_flattened",
        "behavioral_agreement_rate",
        "parser_full_n",
        "parser_full_precision",
        "parser_full_recall",
        "parser_full_f1",
        "parser_full_value_accuracy",
        "parser_full_disjunction_flattened",
        "parser_full_behavioral_agreement_rate",
        "llm_backend",
        "llm_parse",
        "timing_total_p50",
        "timing_total_p95",
        "timing_valid_output_rate",
        "timing_timed_out",
        "timing_used_fallback",
        "timing_budget_overruns",
        "timing_llm_parse_attempted",
        "timing_llm_parse_failed",
        "timing_parse_p95",
        "timing_solve_p95",
        "timing_improve_p95",
        "timing_finalize_p95",
        "parse_completed",
        "parse_failed",
        "parse_timed_out",
        "e2e_completed_without_timeout",
        "e2e_timed_out",
        "solver_completed_without_timeout",
        "solver_timed_out",
        "solver_recovered_from_timeout",
        "solver_used_fallback",
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

    ceiling_q = rehearsal.get("ceiling", {}).get("quality", {})
    solver_q = modes.get("solver-only", {}).get("quality", {})
    e2e_q = modes.get("end-to-end", {}).get("quality", {})

    ceiling_true = float(ceiling_q.get("overall_true", {}).get("mean", 0.0))
    solver_true = float(solver_q.get("overall_true", {}).get("mean", 0.0))
    e2e_true = float(e2e_q.get("overall_true", {}).get("mean", 0.0))

    ceiling_parsed = float(ceiling_q.get("overall_parsed", {}).get("mean", 0.0))
    solver_parsed = float(solver_q.get("overall_parsed", {}).get("mean", 0.0))
    e2e_parsed = float(e2e_q.get("overall_parsed", {}).get("mean", 0.0))

    parser = record.get("parser", {})
    behavioral = parser.get("behavioral", {}) if isinstance(parser, dict) else {}
    parser_full = record.get("parser_full", {})
    parser_full_behavioral = (
        parser_full.get("behavioral", {}) if isinstance(parser_full, dict) else {}
    )
    llm_config = record.get("llm_config", {}) if isinstance(record, dict) else {}
    timing = record.get("timing", {})
    variance = record.get("variance", {}) if isinstance(record, dict) else {}
    completion = record.get("completion", {}) if isinstance(record, dict) else {}
    parse_completion = completion.get("parse", {}) if isinstance(completion, dict) else {}
    e2e_completion = completion.get("end_to_end", {}) if isinstance(completion, dict) else {}
    solver_completion = completion.get("solver_only", {}) if isinstance(completion, dict) else {}

    lines = [
        "# Phase 2 Baseline (Latest)",
        "",
        f"- run_id: {record.get('run_id', '')}",
        f"- timestamp_utc: {record.get('timestamp_utc', '')}",
        f"- git_sha: {record.get('git_sha', '')}",
        f"- split: {record.get('split_name', '')} (set={record.get('split_set', '')}, fold={record.get('fold', 0)}/{record.get('folds', 0)}, n={record.get('n', 0)})",
        f"- budget_sec: {record.get('budget_sec', 0.0)}",
        f"- label: {record.get('label', '') or '(none)'}",
        f"- repeats: {int(record.get('repeats', 1) or 1)} (fresh={bool(record.get('fresh', False))})",
        "",
        "## Rehearsal Attribution (FPR)",
        "",
        f"- ceiling_fpr: {ceiling:.4f}",
        f"- solver_only_fpr: {solver:.4f}",
        f"- end_to_end_fpr: {e2e:.4f}",
        f"- solver_headroom: {ceiling - solver:.4f}",
        f"- parsing_loss: {solver - e2e:.4f}",
        "",
        "## Run-To-Run Variance (across repeats)",
        "",
        f"- repeats: {int(variance.get('repeats', 1) or 1)}",
        f"- e2e_fpr mean/std: {float(variance.get('e2e_fpr_mean', 0.0)):.4f} / {float(variance.get('e2e_fpr_std', 0.0)):.4f}",
        f"- solver_only_fpr mean/std: {float(variance.get('solver_only_fpr_mean', 0.0)):.4f} / {float(variance.get('solver_only_fpr_std', 0.0)):.4f}",
        f"- e2e_overall_true mean/std: {float(variance.get('e2e_overall_true_mean', 0.0)):.4f} / {float(variance.get('e2e_overall_true_std', 0.0)):.4f}",
        f"- solver_only_overall_true mean/std: {float(variance.get('solver_only_overall_true_mean', 0.0)):.4f} / {float(variance.get('solver_only_overall_true_std', 0.0)):.4f}",
        "",
        "## Rehearsal Attribution (Continuous Score)",
        "",
        f"- ceiling_overall_true_mean: {ceiling_true:.4f}",
        f"- solver_only_overall_true_mean: {solver_true:.4f}",
        f"- end_to_end_overall_true_mean: {e2e_true:.4f}",
        f"- overall_true_solver_headroom: {ceiling_true - solver_true:.4f}",
        f"- overall_true_parsing_loss: {solver_true - e2e_true:.4f}",
        f"- ceiling_overall_parsed_mean: {ceiling_parsed:.4f}",
        f"- solver_only_overall_parsed_mean: {solver_parsed:.4f}",
        f"- end_to_end_overall_parsed_mean: {e2e_parsed:.4f}",
        f"- overall_parsed_solver_headroom: {ceiling_parsed - solver_parsed:.4f}",
        f"- overall_parsed_parsing_loss: {solver_parsed - e2e_parsed:.4f}",
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
        "## Parser Vs Oracle (full val, n={0}) -- headline signal, solver-free".format(
            int(parser_full.get("n", 0))
        ),
        "",
        f"- precision: {float(parser_full.get('precision', 0.0)):.4f}",
        f"- recall: {float(parser_full.get('recall', 0.0)):.4f}",
        f"- f1: {float(parser_full.get('f1', 0.0)):.4f}",
        f"- value_accuracy: {float(parser_full.get('value_accuracy', 0.0)):.4f}",
        f"- disjunction_flattened: {int(parser_full.get('disjunction_flattened', 0))}",
        f"- behavioral_agreement_rate: {float(parser_full_behavioral.get('agreement_rate', 0.0)):.4f}",
        "",
        "## LLM Parse Config",
        "",
        f"- backend: {llm_config.get('backend', 'none')}",
        f"- model: {llm_config.get('model') or '(n/a)'}",
        "",
        "## Timing And Reliability",
        "",
        f"- total_p50_sec: {float(timing.get('total_p50', 0.0)):.4f}",
        f"- total_p95_sec: {float(timing.get('total_p95', 0.0)):.4f}",
        f"- valid_output_rate: {float(timing.get('valid_output_rate', 0.0)):.4f}",
        f"- timed_out: {int(timing.get('timed_out', 0))}",
        f"- used_fallback: {int(timing.get('used_fallback', 0))}",
        f"- budget_overruns: {int(timing.get('budget_overruns', 0))}",
        f"- llm_parse_attempted: {int(timing.get('llm_parse_attempted', 0))}",
        f"- llm_parse_failed: {int(timing.get('llm_parse_failed', 0))}",
        "",
        "## Completion Status",
        "",
        f"- parse_completed: {int(parse_completion.get('completed', 0))}/{int(parse_completion.get('n', 0))}",
        f"- parse_failed: {int(parse_completion.get('failed', 0))}",
        f"- parse_timed_out: {int(parse_completion.get('timed_out', 0))}",
        f"- end_to_end_completed_without_timeout: {int(e2e_completion.get('completed_without_timeout', 0))}/{int(e2e_completion.get('n', 0))}",
        f"- end_to_end_timed_out: {int(e2e_completion.get('timed_out', 0))}",
        f"- solver_only_completed_without_timeout: {int(solver_completion.get('completed_without_timeout', 0))}/{int(solver_completion.get('n', 0))}",
        f"- solver_only_timed_out: {int(solver_completion.get('timed_out', 0))}",
        f"- solver_only_recovered_from_timeout: {int(solver_completion.get('recovered_from_timeout', 0))}",
        f"- solver_only_used_fallback: {int(solver_completion.get('used_fallback', 0))}",
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
    p.add_argument(
        "--label",
        default="",
        help="Free-form tag stored with the run (e.g. 'baseline-60s', 'smoke'). Rows with n < 10 "
        "are auto-labeled 'smoke' when no label is given.",
    )
    p.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Run the rehearsal N times (fresh each time) and record run-to-run score variance. "
        "Organizers average 5 runs, so variance matters even on the deterministic path.",
    )
    p.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Allow resuming stale end-to-end results instead of clearing them first. Off by "
        "default because stale plans from older code/budgets contaminate baseline rows.",
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

    fresh = not args.reuse_existing
    repeats = max(int(args.repeats), 1)
    label = args.label or ("smoke" if len(fold_info.uids) < 10 else "")
    if len(fold_info.uids) < 10:
        print(
            f"WARNING: n={len(fold_info.uids)} < 10 — this row is a smoke run, not a baseline "
            "(single-query flakes flip FPR between 0 and 100)."
        )

    rehearsals: list[dict] = []
    for i in range(repeats):
        if repeats > 1:
            print(f"--- repeat {i + 1}/{repeats} ---")
        rehearsals.append(
            rehearse_mod.rehearse(
                modes=("end-to-end", "solver-only"),
                split_set=args.split_set,
                fold=args.fold,
                folds=args.folds,
                seed=args.seed,
                budget_sec=args.budget_sec,
                limit=args.limit,
                lang=args.lang,
                fresh=fresh,
            )
        )
    rehearsal = rehearsals[-1]
    variance = _variance_summary(rehearsals)

    parser = parser_mod.run_report(
        fold_info.split_name,
        uids=fold_info.uids,
        behavioral=True,
        lang=args.lang,
        disjunction=True,
        branch_aware=args.branch_aware,
    )

    # Parser metrics on the fold alone are only as representative as the fold: a small seeded
    # fold can miss every uid a parser fix touched (see roadmap-1c/step2, where full-val
    # behavioral agreement moved 0.706->0.757 while the n=20 fold row stayed flat). The full val
    # split is solver-free (diff-only, no solve), so always measuring it here is cheap
    # (~20s at n=850) and is the headline signal; the fold-scoped "parser" above stays for
    # continuity with earlier ledger rows.
    parser_full = parser_mod.run_report(
        fold_info.split_name,
        uids=None,
        behavioral=True,
        lang=args.lang,
        disjunction=True,
        branch_aware=args.branch_aware,
    )

    llm_cfg = runner_mod._phase2_llm_config()

    e2e_method = f"phase2_e2e_{fold_info.split_name}"
    solver_method = f"phase2_solver_only_{fold_info.split_name}"
    e2e_telemetries, e2e_missing = _collect_selected_telemetry(e2e_method, fold_info.uids)
    solver_telemetries, solver_missing = _collect_selected_telemetry(solver_method, fold_info.uids)
    timing = timing_mod.aggregate_timings(e2e_telemetries, budget_sec=args.budget_sec)
    completion = {
        "parse": _count_parse_failures(e2e_telemetries),
        "end_to_end": _completion_summary(e2e_telemetries),
        "solver_only": _completion_summary(solver_telemetries),
    }

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
        "label": label,
        "repeats": repeats,
        "fresh": fresh,
        "variance": variance,
        "rehearsal": rehearsal,
        "parser": parser,
        "parser_full": parser_full,
        "llm_config": {
            "backend": llm_cfg.get("backend", "none"),
            "model": llm_cfg.get("model"),
        },
        "timing": timing,
        "completion": completion,
        "timing_source": {
            "method": e2e_method,
            "selected_uids": len(fold_info.uids),
            "telemetry_found": len(e2e_telemetries),
            "telemetry_missing": len(e2e_missing),
            "missing_uids": e2e_missing[:20],
        },
        "solver_only_timing_source": {
            "method": solver_method,
            "selected_uids": len(fold_info.uids),
            "telemetry_found": len(solver_telemetries),
            "telemetry_missing": len(solver_missing),
            "missing_uids": solver_missing[:20],
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
