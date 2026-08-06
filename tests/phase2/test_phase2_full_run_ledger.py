"""Roadmap P2: aggregating the per-attempt ledger into the committed whole-run row.

``scripts/phase2_full_run.py``'s ``aggregate_attempt_ledger`` reads every query's
``agent_env/runs/<method>/<uid>/attempts.jsonl`` (written by ``run_sweeps_split``'s ``on_result``,
see ``test_attempt_ledger.py``) and rolls it into one summary dict for the committed row, so the
technical report's distributions and timings are plottable from the row alone. These tests check
the aggregation against a hand-computed fixture rather than a live run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
for _p in (str(PROJECT_ROOT), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import phase2_full_run as pfr  # noqa: E402


def _write_ledger(work_root: Path, uid: str, records: list[dict]) -> None:
    run_dir = work_root / uid
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / pfr.ATTEMPT_LEDGER_FILENAME).open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def test_aggregate_attempt_ledger_matches_a_hand_computed_fixture(tmp_path):
    work_root = tmp_path / "runs" / "method"

    # q1: two attempts, triage then repair; repair is kept (first_accept_attempt = 2).
    _write_ledger(work_root, "q1", [
        {"pass_index": 1, "pass_kind": "triage", "wall_sec": 3.0, "restarts_used": 0,
         "stop_reason": "accepted_stop", "kept": False},
        {"pass_index": 2, "pass_kind": "repair", "wall_sec": 60.0, "restarts_used": 40,
         "stop_reason": "budget", "kept": True},
    ])
    # q2: one attempt, triage, kept immediately (first_accept_attempt = 1).
    _write_ledger(work_root, "q2", [
        {"pass_index": 1, "pass_kind": "triage", "wall_sec": 5.0, "restarts_used": 1,
         "stop_reason": "accepted_stop", "kept": True},
    ])
    # q3: no ledger at all (never solved, e.g. envelope ran out before it was reached).

    uids = ["q1", "q2", "q3"]
    summary = pfr.aggregate_attempt_ledger(work_root, uids)

    # Hand-computed expectations:
    # attempts_per_query = [2, 1, 0] -> min 0, mean 1.0, max 2
    # wall_sec across all 3 recorded attempts = [3.0, 60.0, 5.0] -> min 3.0, mean 22.666..., max 60.0
    # restarts_used = [0, 40, 1] -> min 0, mean 13.666..., max 40
    # stop_reason histogram: accepted_stop x2, budget x1
    # first_accept_attempt: q1 -> 2, q2 -> 1 (q3 contributes nothing, it has no records)
    assert summary["queries"] == 3
    assert summary["queries_with_attempts"] == 2

    apq = summary["attempts_per_query"]
    assert apq["count"] == 3
    assert apq["min"] == 0
    assert apq["max"] == 2
    assert apq["mean"] == (2 + 1 + 0) / 3

    wall = summary["wall_sec_per_attempt"]
    assert wall["count"] == 3
    assert wall["min"] == 3.0
    assert wall["max"] == 60.0
    assert wall["mean"] == (3.0 + 60.0 + 5.0) / 3

    restarts = summary["restarts_used_per_attempt"]
    assert restarts["count"] == 3
    assert restarts["min"] == 0
    assert restarts["max"] == 40
    assert restarts["mean"] == (0 + 40 + 1) / 3

    assert summary["stop_reason_histogram"] == {"accepted_stop": 2, "budget": 1}

    first_accept = summary["first_accept_attempt"]
    assert first_accept["count"] == 2
    assert first_accept["min"] == 1
    assert first_accept["max"] == 2
    assert first_accept["mean"] == (2 + 1) / 2


def test_aggregate_attempt_ledger_all_missing_returns_empty_distributions(tmp_path):
    work_root = tmp_path / "runs" / "method_empty"
    summary = pfr.aggregate_attempt_ledger(work_root, ["a", "b"])

    assert summary["queries"] == 2
    assert summary["queries_with_attempts"] == 0
    assert summary["attempts_per_query"]["mean"] == 0.0
    assert summary["wall_sec_per_attempt"] == {"count": 0, "min": None, "mean": None, "max": None}
    assert summary["restarts_used_per_attempt"] == {
        "count": 0, "min": None, "mean": None, "max": None
    }
    assert summary["stop_reason_histogram"] == {}
    assert summary["first_accept_attempt"] == {
        "count": 0, "min": None, "mean": None, "max": None
    }


def test_aggregate_attempt_ledger_ignores_malformed_lines(tmp_path):
    work_root = tmp_path / "runs" / "method_malformed"
    run_dir = work_root / "q1"
    run_dir.mkdir(parents=True)
    with (run_dir / pfr.ATTEMPT_LEDGER_FILENAME).open("w", encoding="utf-8") as f:
        f.write(json.dumps({"pass_index": 1, "pass_kind": "triage", "wall_sec": 1.0,
                             "restarts_used": 0, "stop_reason": "accepted_stop",
                             "kept": True}) + "\n")
        f.write("not-json\n")
        f.write("\n")  # blank line, must be skipped too

    summary = pfr.aggregate_attempt_ledger(work_root, ["q1"])
    assert summary["attempts_per_query"]["max"] == 1
    assert summary["wall_sec_per_attempt"]["count"] == 1
