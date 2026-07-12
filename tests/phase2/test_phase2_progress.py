"""Unit tests for the live progress counter (scripts/phase2_progress.py).

Read-only tool, no solver/WorldEnv needed -- exercised against a temp results dir with
hand-fabricated result files and mtimes.
"""

from __future__ import annotations

import os
import time

import phase2_progress as P


def _touch(path, mtime=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_snapshot_mtimes_only_counts_existing_uids(tmp_path):
    method_dir = tmp_path / "phase2_e2e_tpc_phase2_val"
    _touch(method_dir / "a.json")
    _touch(method_dir / "b.json")
    got = P.snapshot_mtimes(tmp_path, "phase2_e2e_tpc_phase2_val", ["a", "b", "c"])
    assert set(got.keys()) == {"a", "b"}


def test_tracker_seeds_from_existing_files(tmp_path):
    split = "tpc_phase2_val"
    _touch(tmp_path / f"phase2_e2e_{split}" / "a.json")
    _touch(tmp_path / f"phase2_solver_only_{split}" / "a.json")
    _touch(tmp_path / f"phase2_solver_only_{split}" / "b.json")
    tracker = P.ProgressTracker(results_dir=tmp_path, split_name=split, uids=["a", "b"], repeats=1)
    assert tracker.write_events == 3  # 1 e2e + 2 solver-only, credited as a floor
    assert tracker.total_units == 1 * 2 * 2  # repeats * modes * n


def test_poll_detects_new_file_as_one_event(tmp_path):
    split = "tpc_phase2_val"
    tracker = P.ProgressTracker(results_dir=tmp_path, split_name=split, uids=["a", "b"], repeats=1)
    assert tracker.write_events == 0
    _touch(tmp_path / f"phase2_e2e_{split}" / "a.json")
    summary = tracker.poll()
    assert summary["new_events"] == 1
    assert tracker.write_events == 1


def test_poll_detects_rewrite_as_a_new_event_not_a_duplicate(tmp_path):
    split = "tpc_phase2_val"
    p = tmp_path / f"phase2_e2e_{split}" / "a.json"
    _touch(p, mtime=1000.0)
    tracker = P.ProgressTracker(results_dir=tmp_path, split_name=split, uids=["a"], repeats=1)
    assert tracker.write_events == 1  # seeded from the existing file

    # Unchanged mtime -> no new event.
    summary = tracker.poll()
    assert summary["new_events"] == 0
    assert tracker.write_events == 1

    # Rewritten (e.g. cleared + resolved again next repeat) -> counts as one more event.
    _touch(p, mtime=2000.0)
    summary = tracker.poll()
    assert summary["new_events"] == 1
    assert tracker.write_events == 2


def test_fraction_and_eta_present_in_summary(tmp_path):
    split = "tpc_phase2_val"
    tracker = P.ProgressTracker(results_dir=tmp_path, split_name=split, uids=["a", "b"], repeats=1)
    time.sleep(0.01)
    _touch(tmp_path / f"phase2_e2e_{split}" / "a.json")
    summary = tracker.poll()
    assert 0.0 <= summary["fraction"] <= 1.0
    assert summary["elapsed_sec"] > 0
    text = P.format_summary(summary, n=tracker.n, repeats=tracker.repeats)
    assert "end-to-end" in text and "solver-only" in text
