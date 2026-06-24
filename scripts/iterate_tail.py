#!/usr/bin/env python
"""Multi-round tail optimization loop for HPC-style runs.

Per round:
1) Rank the current low-score tail and emit a focused split.
2) Solve that focused split with deterministic seed salt.
3) Monotonically merge into results/best and record focus-subset metrics.
4) Score the full base split once after the loop.

All artifacts are written under a run directory so overnight cluster runs are
reproducible and auditable.
"""

import argparse
import ast
import datetime as dt
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Optional


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPLITS_DIR = os.path.join(ROOT, "chinatravel", "evaluation", "default_splits")


def _ts_now() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value))


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _run(
    cmd,
    *,
    env=None,
    cwd=ROOT,
    log_path: Optional[str] = None,
    check=False,
    heartbeat_sec: float = 0.0,
    heartbeat_label: Optional[str] = None,
    stream_output: bool = False,
) -> int:
    started = time.monotonic()
    if heartbeat_label:
        label = heartbeat_label
    elif len(cmd) > 1:
        label = os.path.basename(str(cmd[1]))
    else:
        label = "command"

    if log_path and (heartbeat_sec > 0 or stream_output):
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            q = queue.Queue()
            sentinel = object()

            def _reader():
                try:
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        q.put(line)
                finally:
                    q.put(sentinel)

            t = threading.Thread(target=_reader, daemon=True)
            t.start()

            next_heartbeat = None
            if heartbeat_sec > 0:
                next_heartbeat = time.monotonic() + max(1.0, float(heartbeat_sec))

            while True:
                try:
                    item = q.get(timeout=0.5)
                except queue.Empty:
                    item = None

                if item is sentinel:
                    break
                if isinstance(item, str):
                    logf.write(item)
                    if stream_output:
                        # Prefix streamed lines so long runs are easier to scan in one terminal.
                        print("[tail-iterate] {} | {}".format(label, item.rstrip("\n")))

                if next_heartbeat is not None and time.monotonic() >= next_heartbeat:
                    elapsed = int(time.monotonic() - started)
                    print("[tail-iterate] {} still running... {}s elapsed".format(label, elapsed))
                    next_heartbeat = time.monotonic() + max(1.0, float(heartbeat_sec))

            rc = proc.wait()
            elapsed = int(time.monotonic() - started)
            print("[tail-iterate] {} finished rc={} ({}s)".format(label, rc, elapsed))
    elif log_path:
        with open(log_path, "w", encoding="utf-8") as logf:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=logf, stderr=subprocess.STDOUT)
            rc = proc.wait()
    else:
        rc = subprocess.call(cmd, cwd=cwd, env=env)
        if heartbeat_sec > 0:
            elapsed = int(time.monotonic() - started)
            print("[tail-iterate] {} finished rc={} ({}s)".format(label, rc, elapsed))

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


def _read_json_if_exists(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_existing_round_summaries(rounds_dir: str, max_rounds: int):
    summaries = []
    for r in range(max_rounds):
        round_name = "r{:02d}".format(r)
        summary_path = os.path.join(rounds_dir, round_name, "summary.json")
        data = _read_json_if_exists(summary_path)
        if not isinstance(data, dict):
            break
        if data.get("round") != r:
            break
        summaries.append(data)
    return summaries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", default="tpc_phase1", help="base split for ranking")
    ap.add_argument("--method", default="best", help="results method dir for ranking")
    ap.add_argument(
        "--rank-mode",
        choices=["tail", "unsolved", "preference"],
        default="tail",
        help="which subset to rank each round: mixed low-score tail, unresolved constraint tail, or already-solved low-preference queries",
    )
    ap.add_argument(
        "--runner",
        choices=["solve", "densify"],
        default="solve",
        help="solve: rerun TPCAgent search on the focus split; densify: improve already-solved plans only",
    )
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
    ap.add_argument("--resume", action="store_true",
                    help="resume an existing run-id from artifacts if available")
    ap.add_argument("--skip-existing", action="store_true",
                    help="pass --skip to solve.py to avoid recomputing existing per-query outputs")
    ap.add_argument("--heartbeat-sec", type=float, default=60.0,
                    help="print a heartbeat line while long subprocesses are running (0 disables)")
    ap.add_argument("--stream-solve-log", action="store_true",
                    help="stream solve.py output to terminal while also writing solve log file")
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
            "rank_mode": args.rank_mode,
            "runner": args.runner,
            "rounds": args.rounds,
            "top_k": args.top_k,
            "min_score": args.min_score,
            "restarts": args.restarts,
            "budget": args.budget,
            "workers": args.workers,
            "stop_no_improve_rounds": args.stop_no_improve_rounds,
            "seed_prefix": args.seed_prefix,
            "artifacts_root": args.artifacts_root,
            "resume": bool(args.resume),
            "skip_existing": bool(args.skip_existing),
        },
        "solver_env": {
            "TPC_USE_CP_SOLVER": os.environ.get("TPC_USE_CP_SOLVER", None),
            "TPC_CP_AFTER_PASS": os.environ.get("TPC_CP_AFTER_PASS", None),
            "TPC_CP_FOUR_SLOT_SHARE": os.environ.get("TPC_CP_FOUR_SLOT_SHARE", None),
            "TPC_CP_FOUR_SLOT_ROUNDS": os.environ.get("TPC_CP_FOUR_SLOT_ROUNDS", None),
            "TPC_CP_TIME_LIMIT_SEC": os.environ.get("TPC_CP_TIME_LIMIT_SEC", None),
            "TPC_SOLVE_BUDGET_SEC": os.environ.get("TPC_SOLVE_BUDGET_SEC", None),
            "TPC_MAX_RESTARTS": os.environ.get("TPC_MAX_RESTARTS", None),
        },
    }
    run_config_path = os.path.join(run_dir, "run_config.json")
    if not args.resume or not os.path.exists(run_config_path):
        with open(run_config_path, "w", encoding="utf-8") as f:
            json.dump(run_meta, f, ensure_ascii=False, indent=2)

    print("[tail-iterate] run_id={}".format(run_id))
    print("[tail-iterate] artifacts={}".format(os.path.relpath(run_dir, ROOT)))

    existing = _load_existing_round_summaries(rounds_dir, args.rounds) if args.resume else []
    start_round = len(existing)
    round_summaries = list(existing)
    no_improve_streak = 0
    if existing:
        # Continue streak from the tail of existing completed rounds.
        for s in reversed(existing):
            best_updates = s.get("best_updates")
            if best_updates is None:
                break
            if int(best_updates) <= 0:
                no_improve_streak += 1
            else:
                break
        print("[tail-iterate] resume: found {} completed round(s), next={}".format(len(existing), start_round))

    for r in range(start_round, args.rounds):
        round_name = "r{:02d}".format(r)
        round_dir = os.path.join(rounds_dir, round_name)
        _ensure_dir(round_dir)

        focus_split = "{}_tail_focus_{}_{}".format(args.split, run_id, round_name)
        seed_salt = "{}_{}_{}".format(args.seed_prefix, run_id, round_name)

        rank_log = os.path.join(logs_dir, "{}_rank.log".format(round_name))
        solve_log = os.path.join(logs_dir, "{}_solve.log".format(round_name))
        merge_log = os.path.join(logs_dir, "{}_merge.log".format(round_name))

        rank_cmd = [
            sys.executable,
            os.path.join("scripts", "rank_tail.py"),
            "--split", args.split,
            "--method", args.method,
            "--mode", args.rank_mode,
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

        if args.runner == "solve":
            work_cmd = [
                sys.executable,
                os.path.join("scripts", "solve.py"),
                "--split", focus_split,
                "--restarts", str(args.restarts),
                "--budget", str(args.budget),
                "--workers", str(args.workers),
                "--seed-salt", seed_salt,
            ]
            if args.skip_existing:
                work_cmd.append("--skip")
        else:
            work_cmd = [
                sys.executable,
                os.path.join("scripts", "densify.py"),
                "--split", focus_split,
                "--workers", str(args.workers),
            ]
        print("[tail-iterate] {} {} {} IDs...".format(round_name, args.runner, focus_count))
        rc = _run(
            work_cmd,
            log_path=solve_log,
            heartbeat_sec=args.heartbeat_sec,
            heartbeat_label="{} {}".format(round_name, args.runner),
            stream_output=args.stream_solve_log,
        )
        if rc != 0:
            print("[tail-iterate] {} {} failed rc={}".format(round_name, args.runner, rc), file=sys.stderr)
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
            "rank_mode": args.rank_mode,
            "runner": args.runner,
            "best_updates": best_updates,
            "metrics_source": "merge_focus",
            "metrics": metrics,
            "logs": {
                "rank": os.path.relpath(rank_log, ROOT),
                "solve": os.path.relpath(solve_log, ROOT),
                "merge": os.path.relpath(merge_log, ROOT),
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

    final_metrics = None
    final_score_log = os.path.join(logs_dir, "final_score.log")
    if round_summaries:
        print("[tail-iterate] final full-set score on {}...".format(args.split))
        final_score_cmd = [
            sys.executable,
            os.path.join("scripts", "score.py"),
            "--split", args.split,
        ]
        rc = _run(
            final_score_cmd,
            log_path=final_score_log,
            heartbeat_sec=args.heartbeat_sec,
            heartbeat_label="final score",
        )
        if rc == 0:
            final_metrics = _read_metrics(os.path.join(ROOT, "your_tpc_scores.json"))
        else:
            print("[tail-iterate] final score failed rc={}".format(rc), file=sys.stderr)

    out = {
        "run_id": run_id,
        "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
        "final_score_split": args.split,
        "final_metrics": final_metrics,
        "rounds": round_summaries,
    }
    with open(os.path.join(run_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("[tail-iterate] done. summary={}".format(os.path.relpath(os.path.join(run_dir, "summary.json"), ROOT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
