"""The packaged path must work on a tree that has never been run in.

This is the check that would have caught the ``cache/phase2_solve`` race (PR #60): every worker
process built a ``TPCAgent`` against the same missing directory, one created it, and the rest
raised ``FileExistsError`` *inside the ProcessPoolExecutor initializer* -- which breaks the pool
and makes the run emit the pre-written empty fallback for every query.

**Why an ordinary test could not catch it.** The failure only reproduces cold. A development tree
always has ``cache/phase2_solve`` from an earlier run, and so does the second run in any tree, so
every local run, every committed ``full_runs/`` row and the whole unit suite passed while the
packaged archive was broken. The two ingredients are a **pristine working directory** and
**more than one worker** -- this module supplies both.

**What this test can and cannot do.** It reliably catches *deterministic* cold-start breakage --
a directory nothing ever creates, an import that only resolves in a warm tree, a data file missing
from the package -- and it asserts that no worker died during start-up, whatever the cause. It
does **not** reliably catch the narrow race that prompted it: measured against the known-broken
code it fired on roughly one run in four, because ``ProcessPoolExecutor`` ramps workers up lazily
rather than starting them together, and raising the worker count made that *worse*, not better.

The reliable regression guard for that specific mechanism is the deterministic unit test in
``test_log_dir_race.py``, which forces the losing worker's view instead of hoping to observe it.
The two are complements: this one covers the class, that one pins the instance.

Marked ``integration`` because it runs the real solver against a real ``WorldEnv``. It is not
optional before a submission -- see ``docs/reference/competition.md``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENTRY_POINT = PROJECT_ROOT / "agent_env" / "scripts" / "solve_script_with_harness.py"
METHOD = "phase2_cold_start_test"
# The race fires during worker start-up, so the solve only has to be long enough to get there --
# but long enough that this query reliably yields a real plan, or the empty-itinerary assertion
# below would be flaky for an innocent reason. Triage is capped by TPC_P2_TRIAGE_CAP_SEC, not by
# --budget-sec (which sets max_query_sec, and does not bound the triage pass).
TRIAGE_CAP_SEC = "30"
# Bounds the whole run. Without it the default 5-hour envelope keeps scheduling repair/polish
# passes over the single query long after the start-up path this guards has been exercised.
TOTAL_BUDGET_SEC = "75"
# Forced rather than inherited: with one worker there is no race to lose, so a small CI runner
# would silently turn this into a no-op.
WORKERS = "3"
# Must exceed WORKERS. ProcessPoolExecutor spawns workers lazily, one per submitted task, so a
# single-query run starts a single worker and no start-up race can occur at all -- an earlier
# draft of this test passed against the known-broken code for exactly that reason.
LIMIT = "6"


@pytest.fixture
def results_dir():
    path = PROJECT_ROOT / "results" / METHOD
    shutil.rmtree(path, ignore_errors=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def first_json_object(text: str) -> dict:
    """Decode the summary object, ignoring the log lines printed around it."""
    start = text.index("{")
    return json.JSONDecoder().raw_decode(text[start:])[0]


@pytest.mark.integration
def test_cold_start_with_multiple_workers_produces_real_plans(tmp_path, results_dir):
    """Run the organizers' entry point from a directory that has never been run in.

    ``cache/phase2_solve`` resolves relative to the working directory, so a fresh ``cwd`` is what
    makes this cold -- the same state as a freshly unpacked submission archive.
    """
    cache_dir = tmp_path / "cache" / "phase2_solve"
    assert not cache_dir.exists(), "precondition: the shared cache directory must start absent"

    env = {**os.environ, "TPC_P2_TRIAGE_CAP_SEC": TRIAGE_CAP_SEC}
    completed = subprocess.run(
        [
            sys.executable,
            str(ENTRY_POINT),
            "--split",
            "tpc_phase2_familiar_100_val",
            "--limit",
            LIMIT,
            "--total-budget-sec",
            TOTAL_BUDGET_SEC,
            "--method",
            METHOD,
            "--work-dir",
            str(tmp_path / "runs"),
            "--workers",
            WORKERS,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )

    assert completed.returncode == 0, (
        f"cold-start run failed\n--- stdout ---\n{completed.stdout[-3000:]}\n"
        f"--- stderr ---\n{completed.stderr[-3000:]}"
    )

    # The generalizing assertion. A worker that dies during start-up takes the pool with it, and
    # the run still exits 0 while quietly emitting empty fallbacks -- so exit status alone proves
    # nothing. Any cause counts, not just the FileExistsError that prompted this test.
    assert "Exception in initializer" not in completed.stderr, (
        "a worker died during start-up; the pool is broken and every plan is a fallback\n"
        f"--- stderr ---\n{completed.stderr[-3000:]}"
    )

    assert cache_dir.is_dir(), "workers never created the shared cache directory"

    summary = first_json_object(completed.stdout)
    passes = summary.get("passes") or []
    assert passes, f"no pass ran: {summary}"
    assert all(p["failed"] == 0 for p in passes), f"a pass reported failures: {passes}"
    assert any(p["completed"] > 0 for p in passes), f"no query completed: {passes}"

    plans = sorted(results_dir.glob("*.json"))
    assert len(plans) == int(LIMIT), f"expected {LIMIT} plans in {results_dir}, got {len(plans)}"
    empty = [p.name for p in plans if not json.loads(p.read_text(encoding="utf-8")).get("itinerary")]
    assert not empty, (
        f"{len(empty)} of {len(plans)} plans are the empty pre-written fallback rather than solved "
        f"plans -- the hallmark of a broken worker pool: {empty}"
    )
