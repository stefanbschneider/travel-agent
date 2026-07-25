#!/usr/bin/env python3
"""Live progress counter for a running ``make phase2-baseline`` / ``phase2_record_baseline.py`` job.

Read-only: touches no file the harness imports or re-executes, so it is always safe to run
alongside (or instead of) log-scraping, including while a baseline/rehearsal job holds the
Phase 2 source frozen (see docs/tpc_phase2_design.md's "Fast e2e iteration loop" section).

Why not just grep the job's log? ``rehearse_phase2.rehearse()`` prints progress markers from the
*parent* process, but each chunk is a subprocess (``solve_phase2.py``) writing to the same
redirected stdout -- when stdout is a file (not a tty), the parent's own ``print()`` calls are
fully buffered while the child subprocesses' writes land immediately, so log *line order* does not
reliably reflect *event order*. On-disk result-file mtimes do not have this problem.

Why a snapshot of current file counts is not enough on its own: ``rehearse()`` only clears stale
results for **end-to-end** mode between repeats (``clear_method_outputs``, "fresh: cleared N stale
end-to-end result(s)") -- **solver-only** mode is never cleared, so a full n/n solver-only count can
mean "just finished this repeat" or "leftover from repeats/runs ago". ``--watch`` mode resolves this
by counting *write events* (an mtime that increased since the last poll) instead of raw counts, so
it is correct regardless of the clearing asymmetry.

Usage:
    python scripts/phase2_progress.py --split-set val --fold 0 --folds 10 --repeats 2
    python scripts/phase2_progress.py --split-set val --fold 0 --folds 10 --repeats 2 --watch
    python scripts/phase2_progress.py --split-set val --fold 0 --folds 10 --repeats 2 \\
        --watch --interval 30
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MODES = ("end-to-end", "solver-only")


def method_name(mode: str, split_name: str) -> str:
    prefix = "phase2_e2e" if mode == "end-to-end" else "phase2_solver_only"
    return f"{prefix}_{split_name}"


def snapshot_mtimes(results_dir: Path, method: str, uids: list[str]) -> dict[str, float]:
    """Return ``{uid: mtime}`` for uids whose result file currently exists."""
    method_dir = results_dir / method
    out: dict[str, float] = {}
    for uid in uids:
        p = method_dir / f"{uid}.json"
        try:
            out[uid] = p.stat().st_mtime
        except FileNotFoundError:
            continue
    return out


def resolve_fold_uids(*, split_set: str, fold: int, folds: int, seed: int, limit: int | None) -> tuple[str, list[str]]:
    """Mirror phase2_record_baseline.py's fold resolution (read-only, no solver import needed)."""
    import make_phase2_splits as splits_mod
    import rehearse_phase2 as rehearse_mod

    split_name, _is_test = rehearse_mod.resolve_split_set(split_set)
    uids = splits_mod.read_split(split_name)
    fold_uids = rehearse_mod.select_fold(uids, fold=fold, folds=folds, seed=seed)
    if limit:
        fold_uids = fold_uids[: int(limit)]
    return split_name, fold_uids


class ProgressTracker:
    """Accumulates write events across polls so raw (uncleared) file counts never undercount or
    overcount progress. ``total_units`` is ``repeats * len(MODES) * n``."""

    def __init__(self, *, results_dir: Path, split_name: str, uids: list[str], repeats: int):
        self.results_dir = results_dir
        self.split_name = split_name
        self.uids = uids
        self.n = len(uids)
        self.repeats = repeats
        self.total_units = repeats * len(MODES) * self.n
        # Prime from whatever already exists on disk (e.g. the tracker was started mid-job): this
        # is credited as a floor on already-completed work, and only *new* writes from here count
        # as further events -- so a fresh watcher never double-counts, but its overall-percentage
        # estimate can still understate history it didn't observe (end-to-end is cleared between
        # repeats, so an earlier repeat's e2e writes that were overwritten before this tracker
        # started are invisible to it; solver-only is never cleared, so its floor is exact).
        initial = self.current_counts()
        self._last_mtimes: dict[str, dict[str, float]] = initial
        self.write_events = sum(len(v) for v in initial.values())
        self.started_at = time.time()

    def current_counts(self) -> dict[str, dict[str, float]]:
        return {
            mode: snapshot_mtimes(self.results_dir, method_name(mode, self.split_name), self.uids)
            for mode in MODES
        }

    def poll(self) -> dict:
        """Advance the tracker one poll; returns a summary dict for display."""
        counts = self.current_counts()
        new_events = 0
        for mode in MODES:
            prev = self._last_mtimes[mode]
            cur = counts[mode]
            for uid, mtime in cur.items():
                if prev.get(uid) != mtime:
                    new_events += 1
            self._last_mtimes[mode] = cur
        self.write_events += new_events
        elapsed = time.time() - self.started_at
        fraction = min(self.write_events / self.total_units, 1.0) if self.total_units else 1.0
        rate = self.write_events / elapsed if elapsed > 0 else 0.0
        remaining_units = max(self.total_units - self.write_events, 0)
        eta_sec = (remaining_units / rate) if rate > 0 else None
        return {
            "counts": counts,
            "new_events": new_events,
            "write_events": self.write_events,
            "total_units": self.total_units,
            "fraction": fraction,
            "elapsed_sec": elapsed,
            "rate_per_sec": rate,
            "eta_sec": eta_sec,
        }


def _fmt_duration(sec: float | None) -> str:
    if sec is None:
        return "unknown"
    sec = max(int(sec), 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def format_summary(summary: dict, *, n: int, repeats: int, show_rate: bool = True) -> str:
    counts = summary["counts"]
    e2e_n = len(counts["end-to-end"])
    solver_n = len(counts["solver-only"])
    pct = summary["fraction"] * 100.0
    bar_len = 30
    filled = int(round(bar_len * summary["fraction"]))
    bar = "#" * filled + "-" * (bar_len - filled)
    lines = [
        f"[{bar}] {pct:5.1f}%  ({summary['write_events']}/{summary['total_units']} write-events, "
        f"floor-seeded estimate -- see --watch for a live rate/ETA)",
        f"  end-to-end:  {e2e_n:3d}/{n}   solver-only: {solver_n:3d}/{n}   (repeats={repeats})",
    ]
    if show_rate:
        lines.append(
            f"  elapsed watching: {_fmt_duration(summary['elapsed_sec'])}"
            f"   rate: {summary['rate_per_sec']*60:.1f} events/min"
            f"   ETA: {_fmt_duration(summary['eta_sec'])}"
        )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--split-set",
        choices=["val", "test", "familiar_100", "familiar_100_val", "familiar_100_test"],
        default="val",
    )
    p.add_argument("--fold", type=int, default=0)
    p.add_argument("--folds", type=int, default=10)
    p.add_argument("--seed", type=int, default=20260705)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--results-dir", default=str(PROJECT_ROOT / "results"))
    p.add_argument("--watch", action="store_true", help="Poll and print live updates instead of one snapshot.")
    p.add_argument("--interval", type=float, default=30.0, help="Seconds between polls in --watch mode.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    split_name, fold_uids = resolve_fold_uids(
        split_set=args.split_set, fold=args.fold, folds=args.folds, seed=args.seed, limit=args.limit,
    )
    tracker = ProgressTracker(
        results_dir=Path(args.results_dir), split_name=split_name, uids=fold_uids, repeats=args.repeats,
    )
    print(f"Tracking {split_name} fold {args.fold}/{args.folds} (n={tracker.n}), repeats={args.repeats}, "
          f"total_units={tracker.total_units}", flush=True)

    if not args.watch:
        summary = tracker.poll()
        print(format_summary(summary, n=tracker.n, repeats=args.repeats, show_rate=False), flush=True)
        return

    try:
        while True:
            summary = tracker.poll()
            print(format_summary(summary, n=tracker.n, repeats=args.repeats), flush=True)
            print(flush=True)
            if summary["fraction"] >= 1.0:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
