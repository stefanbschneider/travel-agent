#!/usr/bin/env python
"""Run the shipped Phase 2 system exactly as the organizers will, then score it officially.

This is the end-to-end evaluation for the 5-hour whole-run envelope. It deliberately runs the
*submission path itself* -- `agent_env/scripts/solve_script_with_harness.py` in a subprocess --
rather than reimplementing it, so what we measure is what we ship. The alternative (the chunked
per-query-budget rehearsal in `scripts/rehearse_phase2.py`) answers a different question now:
it measures per-query solver quality at a fixed budget, not what the scheduler achieves inside a
shared envelope.

Three steps, timed separately:

1. **run** -- the harness command, with the envelope and worker count the submission would use;
2. **score** -- `eval_tpc.py` on the resulting method directory, which writes the official metric
   decomposition (we read its numbers rather than computing our own -- see CLAUDE.md's evaluator
   parity invariant);
3. **record** -- a row under `results/phase2_baselines/full_runs/`, carrying everything needed to
   decide whether two rows are comparable.

Rows from this script are comparable to each other, never to the per-query-budget rows in
`results/phase2_baselines/runs/`: different budget contract, different parallelism, different
scheduler. See docs/tpc_phase2_eval.md.

Usage:
    python scripts/phase2_full_run.py --dry-run
    python scripts/phase2_full_run.py --label "first 5h parallel run"
    python scripts/phase2_full_run.py --split tpc_phase2_familiar_100_val --total-budget-sec 3600
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

FULL_RUN_DIR = ROOT / "results" / "phase2_baselines" / "full_runs"
SCORES_FILE = ROOT / "your_tpc_scores.json"
HARNESS = "agent_env/scripts/solve_script_with_harness.py"
DEFAULT_SPLIT = "tpc_phase2_familiar_100"
DEFAULT_TOTAL_BUDGET_SEC = 5 * 60 * 60


def run_git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def evaluator_parity_sha() -> str:
    source = (ROOT / "scripts" / "phase2_record_baseline.py").read_text(encoding="utf-8")
    match = re.search(r'EVALUATOR_PARITY_SHA\s*=\s*"([^"]+)"', source)
    return match.group(1) if match else "unknown"


def default_workers() -> int:
    sys.path.insert(0, str(ROOT))
    from chinatravel.agent.phase2 import sweeps

    return sweeps.default_workers()


def stream(cmd: list[str], log_path: Path) -> tuple[int, float]:
    """Run a command, tee it to ``log_path``, and return (exit code, wall seconds)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            # The sweep scheduler's own progress lines are the interesting ones during a 5h run.
            if line.startswith("[sweep]") or line.startswith("Overall Score"):
                print(line.rstrip(), flush=True)
        code = process.wait()
    return code, time.monotonic() - started


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--split", default=DEFAULT_SPLIT)
    ap.add_argument("--method", default=None, help="Default: phase2_e2e_<split>.")
    ap.add_argument(
        "--total-budget-sec",
        type=float,
        default=DEFAULT_TOTAL_BUDGET_SEC,
        help="Whole-run wall-clock envelope. Default: the organizers' 5 hours.",
    )
    ap.add_argument("--workers", type=int, default=None, help="Default: CPU count - 1.")
    ap.add_argument("--label", default="", help="Free-text label recorded with the row.")
    ap.add_argument(
        "--fresh",
        action="store_true",
        default=True,
        help="Delete the method's existing results first (default).",
    )
    ap.add_argument(
        "--resume",
        dest="fresh",
        action="store_false",
        help="Keep existing plans and let the scheduler improve on them.",
    )
    ap.add_argument(
        "--skip-run", action="store_true", help="Score and record existing results; do not solve."
    )
    ap.add_argument("--dry-run", action="store_true", help="Print the commands and exit.")
    args = ap.parse_args()

    method = args.method or f"phase2_e2e_{args.split}"
    workers = args.workers or default_workers()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    method_dir = ROOT / "results" / method
    log_dir = ROOT / "cache" / "phase2_full_runs" / run_id

    run_cmd = [
        sys.executable,
        HARNESS,
        "--split",
        args.split,
        "--total-budget-sec",
        str(args.total_budget_sec),
        "--workers",
        str(workers),
        "--method",
        method,
    ]
    if not args.fresh:
        run_cmd.append("--resume")
    score_cmd = [sys.executable, "eval_tpc.py", "--splits", args.split, "--method", method]

    print(f"run   : {' '.join(run_cmd)}")
    print(f"score : {' '.join(score_cmd)}")
    print(
        f"budget: {args.total_budget_sec / 3600:.2f} h total, {workers} workers, "
        f"method {method}, fresh={args.fresh}"
    )
    if args.dry_run:
        print("(dry run: nothing executed)")
        return 0

    run_wall = 0.0
    if not args.skip_run:
        if args.fresh and method_dir.exists():
            shutil.rmtree(method_dir)
        code, run_wall = stream(run_cmd, log_dir / "run.log")
        if code != 0:
            print(f"run failed with exit code {code}; see {log_dir / 'run.log'}", file=sys.stderr)
            return code
        print(f"run finished in {run_wall / 3600:.2f} h ({run_wall:.0f}s)")

    if SCORES_FILE.exists():
        SCORES_FILE.unlink()  # never report a stale score as this run's
    code, score_wall = stream(score_cmd, log_dir / "score.log")
    if code != 0:
        print(f"scoring failed with exit code {code}; see {log_dir / 'score.log'}", file=sys.stderr)
        return code
    scores = read_json(SCORES_FILE)

    plans = sorted(method_dir.glob("*.json")) if method_dir.exists() else []
    empty_plans = 0
    for path in plans:
        plan = read_json(path)
        if not isinstance(plan, dict) or not plan.get("itinerary"):
            empty_plans += 1

    run_summary = read_json(
        ROOT / "agent_env" / "runs" / method / f"{args.split}_summary.json"
    )
    row = {
        "run_id": run_id,
        "kind": "full_run",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": run_git("rev-parse", "HEAD"),
        "git_dirty": bool(run_git("status", "--porcelain")),
        "evaluator_parity": evaluator_parity_sha(),
        "label": args.label,
        "split": args.split,
        "method": method,
        "total_budget_sec": args.total_budget_sec,
        "workers": workers,
        "fresh": args.fresh,
        "run_wall_sec": round(run_wall, 1),
        "run_wall_frac_of_budget": (
            round(run_wall / args.total_budget_sec, 4) if args.total_budget_sec else None
        ),
        "score_wall_sec": round(score_wall, 1),
        "plans_written": len(plans),
        "empty_plans": empty_plans,
        "official_scores": scores,
        "overall": (scores or {}).get("overall"),
        "sweeps": run_summary,
        "host": {
            "cpu_count": os.cpu_count(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
    }
    FULL_RUN_DIR.mkdir(parents=True, exist_ok=True)
    row_path = FULL_RUN_DIR / f"{run_id}.json"
    row_path.write_text(json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\nrecorded {row_path.relative_to(ROOT)}")
    print(f"  overall            {row['overall']}")
    print(f"  plans / empty      {len(plans)} / {empty_plans}")
    print(
        f"  wall               {run_wall / 3600:.2f} h of "
        f"{args.total_budget_sec / 3600:.2f} h envelope"
    )
    if run_summary:
        print(
            f"  constraints_ok     {run_summary.get('constraints_ok')} / "
            f"{run_summary.get('queries')} (oracle-free self-score)"
        )
        for record in run_summary.get("passes", []):
            print(
                f"    pass {record['index']} {record['kind']:<7} "
                f"{record['queries']:>3} x {record['budget_sec']:>6.0f}s -> "
                f"improved {record['improved']:>3} in {record['elapsed_sec'] / 60:.1f} min"
            )
    if row["git_dirty"]:
        print("  WARNING: working tree was dirty; this row is not reproducible from a commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
