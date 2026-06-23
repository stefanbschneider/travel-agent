#!/usr/bin/env python
"""Multi-round tail optimization loop for HPC-style runs.

Per round:
1) Rank the current low-score tail and emit a focused split.
2) Solve that focused split with deterministic seed salt.
3) Monotonically merge into results/best.
4) Score and record a round summary.

All artifacts are written under a run directory so overnight cluster runs are
reproducible and auditable.
"""

import argparse
import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys
from typing import Optional


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLITS_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")


def _ts_now() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value))


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _run(cmd, *, env=None, cwd=ROOT, log_path: Optional[str] = None, check=False) -> int:
    if log_path:
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=logf, stderr=subprocess.STDOUT)
            rc = proc.wait()
    else:
        rc = subprocess.call(cmd, cwd=cwd, env=env)
    if check and rc != 0:
        raise RuntimeError("command failed rc={} cmd={}".format(rc, " ".join(cmd)))
    return rc


def _read_metrics(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    def _parse_obj_text(obj_text: str):
        cleaned = re.sub(r"np\.float\d*\(([^()]+)\)", r"\1", obj_text)
        try:
            parsed = json.loads(cleaned)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            try:
                parsed = ast.literal_eval(cleaned)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None

    # Common case: one object-like line per append.
    for line in reversed(lines):
        if line.startswith("{") and "overall" in line:
            parsed = _parse_obj_text(line)
            if parsed is not None:
                return parsed

    # Fallback for append-only files that may contain concatenated objects without newlines.
    text = "".join(lines)
    for match in reversed(list(re.finditer(r"\{[^{}]*overall[^{}]*\}", text, flags=re.IGNORECASE))):
        parsed = _parse_obj_text(match.group(0))
        if parsed is not None:
            return parsed
    return None


def _focus_size(split_name: str) -> int:
    path = os.path.join(SPLITS_DIR, split_name + ".txt")
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="tpc_phase1", help="base split for ranking")
    ap.add_argument("--method", default="best", help="results method dir for ranking")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--top-k", type=int, default=120)
    ap.add_argument("--min-score", type=float, default=99.0)
    ap.add_argument("--restarts", type=int, default=1200)
    ap.add_argument("--budget", type=float, default=300.0)
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--stop-no-improve-rounds", type=int, default=1,
                    help="stop after this many consecutive rounds with no best updates")
    ap.add_argument("--artifacts-root", default=os.path.join("cache", "hpc_tail_runs"))
    ap.add_argument("--run-id", default=None,
                    help="optional stable run id; default uses timestamp")
    ap.add_argument("--seed-prefix", default="tail",
                    help="prefix used for deterministic per-round seed salts")
    args = ap.parse_args()

    run_id = args.run_id or _ts_now()
    run_id = _safe_name(run_id)
    artifacts_root = os.path.join(ROOT, args.artifacts_root)
    run_dir = os.path.join(artifacts_root, run_id)
    rounds_dir = os.path.join(run_dir, "rounds")
    logs_dir = os.path.join(run_dir, "logs")
    _ensure_dir(rounds_dir)
    _ensure_dir(logs_dir)

    run_meta = {
        "run_id": run_id,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "config": {
            "split": args.split,
            "method": args.method,
            "rounds": args.rounds,
            "top_k": args.top_k,
            "min_score": args.min_score,
            "restarts": args.restarts,
            "budget": args.budget,
            "workers": args.workers,
            "stop_no_improve_rounds": args.stop_no_improve_rounds,
            "seed_prefix": args.seed_prefix,
            "artifacts_root": args.artifacts_root,
        },
    }
    with open(os.path.join(run_dir, "run_config.json"), "w", encoding="utf-8") as f:
        json.dump(run_meta, f, ensure_ascii=False, indent=2)

    print("[tail-iterate] run_id={}".format(run_id))
    print("[tail-iterate] artifacts={}".format(os.path.relpath(run_dir, ROOT)))

    no_improve_streak = 0
    round_summaries = []

    for r in range(args.rounds):
        round_name = "r{:02d}".format(r)
        round_dir = os.path.join(rounds_dir, round_name)
        _ensure_dir(round_dir)

        focus_split = "{}_tail_focus_{}_{}".format(args.split, run_id, round_name)
        seed_salt = "{}_{}_{}".format(args.seed_prefix, run_id, round_name)

        rank_log = os.path.join(logs_dir, "{}_rank.log".format(round_name))
        solve_log = os.path.join(logs_dir, "{}_solve.log".format(round_name))
        merge_log = os.path.join(logs_dir, "{}_merge.log".format(round_name))
        score_log = os.path.join(logs_dir, "{}_score.log".format(round_name))

        rank_cmd = [
            sys.executable,
            os.path.join("scripts", "rank_tail.py"),
            "--split", args.split,
            "--method", args.method,
            "--top-k", str(args.top_k),
            "--min-score", str(args.min_score),
            "--focus-split", focus_split,
            "--report-name", "{}_{}_tail_ranking_{}.csv".format(args.split, args.method, round_name),
        ]
        print("[tail-iterate] {} ranking...".format(round_name))
        rc = _run(rank_cmd, log_path=rank_log)
        if rc != 0:
            print("[tail-iterate] {} rank failed rc={}".format(round_name, rc), file=sys.stderr)
            return rc

        focus_count = _focus_size(focus_split)
        if focus_count == 0:
            print("[tail-iterate] {} focus split empty; stopping".format(round_name))
            break

        solve_cmd = [
            sys.executable,
            os.path.join("scripts", "solve.py"),
            "--split", focus_split,
            "--restarts", str(args.restarts),
            "--budget", str(args.budget),
            "--workers", str(args.workers),
            "--seed-salt", seed_salt,
        ]
        print("[tail-iterate] {} solve {} IDs...".format(round_name, focus_count))
        rc = _run(solve_cmd, log_path=solve_log)
        if rc != 0:
            print("[tail-iterate] {} solve failed rc={}".format(round_name, rc), file=sys.stderr)
            return rc

        merge_cmd = [
            sys.executable,
            os.path.join("scripts", "merge.py"),
            "--split", focus_split,
        ]
        print("[tail-iterate] {} merge...".format(round_name))
        rc = _run(merge_cmd, log_path=merge_log)
        if rc != 0:
            print("[tail-iterate] {} merge failed rc={}".format(round_name, rc), file=sys.stderr)
            return rc

        score_cmd = [
            sys.executable,
            os.path.join("scripts", "score.py"),
        ]
        print("[tail-iterate] {} score...".format(round_name))
        rc = _run(score_cmd, log_path=score_log)
        if rc != 0:
            print("[tail-iterate] {} score failed rc={}".format(round_name, rc), file=sys.stderr)
            return rc

        metrics = _read_metrics(os.path.join(ROOT, "your_tpc_scores.json")) or {}

        best_updates = None
        if os.path.exists(merge_log):
            with open(merge_log, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("best:") and "results updated" in line:
                        try:
                            best_updates = int(line.split()[1])
                        except Exception:
                            best_updates = None

        summary = {
            "round": r,
            "round_name": round_name,
            "focus_split": focus_split,
            "focus_count": focus_count,
            "seed_salt": seed_salt,
            "best_updates": best_updates,
            "metrics": metrics,
            "logs": {
                "rank": os.path.relpath(rank_log, ROOT),
                "solve": os.path.relpath(solve_log, ROOT),
                "merge": os.path.relpath(merge_log, ROOT),
                "score": os.path.relpath(score_log, ROOT),
            },
        }
        round_summaries.append(summary)
        with open(os.path.join(round_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(
            "[tail-iterate] {}: focus={} best_updates={} overall={}".format(
                round_name,
                focus_count,
                best_updates,
                metrics.get("overall", "n/a"),
            )
        )

        if best_updates is not None and best_updates <= 0:
            no_improve_streak += 1
        else:
            no_improve_streak = 0

        if no_improve_streak >= max(1, args.stop_no_improve_rounds):
            print("[tail-iterate] stopping after {} no-improve round(s)".format(no_improve_streak))
            break

    out = {
        "run_id": run_id,
        "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        "rounds": round_summaries,
    }
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("[tail-iterate] done. summary={}".format(os.path.relpath(os.path.join(run_dir, "summary.json"), ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
