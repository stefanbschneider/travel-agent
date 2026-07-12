#!/usr/bin/env python3
"""Continuous eval worker for VM 2 (plan-2 Step 4): turns every pushed commit on
``origin/stefan/phase2`` into one canonical ground-truth ledger row, unattended.

A dumb loop -- no daemon framework: fetch, resolve the newest sha, check whether it already has
a ledger row (skip if so), evaluate it via the pinned-worktree runner (``phase2_eval_at.py``,
plan-2 Step 1), and publish the row to a dedicated ``phase2-eval-ledger`` branch via its own
worktree (so publication never races the coding VM's ``stefan/phase2`` work).

Usage (VM 2, unattended):
    nohup .venv/bin/python scripts/phase2_eval_worker.py >> ~/phase2_eval_worker.log 2>&1 &

Usage (either VM, one-shot / inspection):
    scripts/phase2_eval_worker.py --once --dry-run   # print the plan, run nothing
    scripts/phase2_eval_worker.py --once             # evaluate the current newest sha once, exit
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import phase2_diff_eval as diff_eval_mod  # noqa: E402 -- reuse PARSE_ONLY_ALLOWLIST verbatim

DEFAULT_BRANCH = "stefan/phase2"
DEFAULT_LEDGER_BRANCH = "phase2-eval-ledger"
DEFAULT_LEDGER_WORKTREE = Path("/tmp/phase2_eval_ledger")
CANONICAL_LABEL = "ci-300s"
DET_LABEL = "ci-300s-det"
DEFAULT_BUDGET_SEC = 300.0
DEFAULT_FOLD = 0
DEFAULT_FOLDS = 10  # n=85 at fold 0
DEFAULT_PARALLEL = 3
DEFAULT_REPEATS = 1  # every repeat pair measured so far had std 0.0 -- see plan-2 Step 4
DEFAULT_POLL_INTERVAL_SEC = 600
DEFAULT_PIDFILE = Path("/tmp/phase2_eval_worker.pid")


# --- Pure helpers (unit-tested) --------------------------------------------


def sha_already_evaluated(history_rows: list[dict[str, Any]], *, sha: str, label: str) -> bool:
    """True if the ledger already has a row for this exact (git_sha, label) pair."""
    return any(
        row.get("git_sha") == sha and row.get("label") == label for row in history_rows
    )


def pick_labels_to_run(
    history_rows: list[dict[str, Any]], *, sha: str, touched_parsing: bool,
) -> list[str]:
    """Which canonical labels this sha still needs a ledger row for.

    Always wants ``ci-300s``. Wants ``ci-300s-det`` too, but only when the sha touched a
    parse-only module (same allowlist as Step 2) -- an unattended worker with unbounded time
    between pushes has "spare time before the next push" by construction, so plan-2 Step 4's
    "if there is spare time" condition simplifies to just the touched-parsing check here.
    """
    labels = []
    if not sha_already_evaluated(history_rows, sha=sha, label=CANONICAL_LABEL):
        labels.append(CANONICAL_LABEL)
    if touched_parsing and not sha_already_evaluated(history_rows, sha=sha, label=DET_LABEL):
        labels.append(DET_LABEL)
    return labels


def changed_files_between(a: str, b: str, *, cwd: Path = PROJECT_ROOT) -> list[str]:
    out = subprocess.check_output(["git", "diff", "--name-only", a, b], cwd=cwd, text=True)
    return [line.strip() for line in out.splitlines() if line.strip()]


def sha_touched_parsing(sha: str, *, cwd: Path = PROJECT_ROOT) -> bool:
    """Did this commit (vs its parent) touch a parse-only module (Step 2's allowlist, minus the
    tests/ exemption -- a test-only commit doesn't need a fresh det-vs-LLM anchor)."""
    try:
        changed = changed_files_between(f"{sha}^", sha, cwd=cwd)
    except subprocess.CalledProcessError:
        return False  # e.g. sha is a root commit with no parent -- never happens in practice here
    return any(f in diff_eval_mod.PARSE_ONLY_ALLOWLIST for f in changed)


def read_history_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def pidfile_holder_alive(pidfile: Path) -> int | None:
    """Return the live PID recorded in ``pidfile``, or None if the file is absent/stale."""
    if not pidfile.exists():
        return None
    try:
        pid = int(pidfile.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid  # exists, owned by someone else -- still alive from our point of view
    return pid


# --- Git plumbing (thin wrappers; not unit-tested against a real remote) ---


def git(*args: str, cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def resolve_latest_sha(*, branch: str = DEFAULT_BRANCH, cwd: Path = PROJECT_ROOT) -> str:
    git("fetch", "origin", cwd=cwd)
    return git("rev-parse", f"origin/{branch}", cwd=cwd)


def ensure_ledger_worktree(
    *, main_repo: Path = PROJECT_ROOT, worktree_dir: Path = DEFAULT_LEDGER_WORKTREE,
    ledger_branch: str = DEFAULT_LEDGER_BRANCH, base_branch: str = DEFAULT_BRANCH,
) -> Path:
    """Create (if missing) a persistent worktree checked out to ``ledger_branch``, branching it
    from ``origin/<base_branch>`` the first time. Idempotent."""
    if worktree_dir.exists():
        return worktree_dir
    subprocess.run(["git", "fetch", "origin"], cwd=main_repo, check=True, capture_output=True, text=True)
    remote_branches = git("branch", "-r", cwd=main_repo)
    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    if f"origin/{ledger_branch}" in remote_branches:
        subprocess.run(
            ["git", "worktree", "add", "-B", ledger_branch, str(worktree_dir),
             f"origin/{ledger_branch}"],
            cwd=main_repo, check=True, capture_output=True, text=True,
        )
    else:
        subprocess.run(
            ["git", "worktree", "add", "-b", ledger_branch, str(worktree_dir),
             f"origin/{base_branch}"],
            cwd=main_repo, check=True, capture_output=True, text=True,
        )
    return worktree_dir


def commit_and_push_ledger(
    worktree_dir: Path, *, message: str, branch: str = DEFAULT_LEDGER_BRANCH, retries: int = 5,
) -> bool:
    """Commit whatever the recorder just wrote under ``worktree_dir`` and push, retrying with
    ``pull --rebase`` on a non-fast-forward (another push landed first). Ledger rows are
    uniquely named and history.jsonl is append-only, so a rebase here is always clean as long as
    only this worker writes this branch."""
    subprocess.run(["git", "add", "-A"], cwd=worktree_dir, check=True, capture_output=True, text=True)
    status = git("status", "--porcelain", cwd=worktree_dir)
    if not status:
        return True  # nothing to commit (shouldn't normally happen, but not an error)
    subprocess.run(
        ["git", "commit", "-q", "-m", message], cwd=worktree_dir, check=True,
        capture_output=True, text=True,
    )
    for attempt in range(retries):
        push = subprocess.run(
            ["git", "push", "origin", f"HEAD:{branch}"], cwd=worktree_dir,
            capture_output=True, text=True,
        )
        if push.returncode == 0:
            return True
        subprocess.run(
            ["git", "pull", "--rebase", "origin", branch], cwd=worktree_dir, check=True,
            capture_output=True, text=True,
        )
    return False


# --- One eval-at invocation --------------------------------------------------


def build_eval_at_cmd(
    *, sha: str, label: str, ledger_dir: Path, python_exe: Path,
    budget_sec: float = DEFAULT_BUDGET_SEC, fold: int = DEFAULT_FOLD,
    folds: int = DEFAULT_FOLDS, repeats: int = DEFAULT_REPEATS, parallel: int = DEFAULT_PARALLEL,
) -> list[str]:
    """Pure command assembly (split out from the run path so it's unit-testable)."""
    eval_at = SCRIPTS_DIR / "phase2_eval_at.py"
    return [
        str(python_exe), str(eval_at), "--sha", sha, "--ledger-dir", str(ledger_dir),
        "--",
        "--split-set", "val", "--fold", str(fold), "--folds", str(folds),
        "--budget-sec", str(budget_sec), "--repeats", str(repeats), "--parallel", str(parallel),
        "--label", label,
    ]


def run_eval_at(cmd: list[str], *, env: dict[str, str] | None = None) -> int:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=full_env)
    return proc.returncode


# --- Orchestration (one iteration) ------------------------------------------


def run_once(
    *,
    dry_run: bool = False,
    branch: str = DEFAULT_BRANCH,
    ledger_branch: str = DEFAULT_LEDGER_BRANCH,
    ledger_worktree: Path = DEFAULT_LEDGER_WORKTREE,
    python_exe: Path | None = None,
    resolve_sha_fn: Callable[[], str] = None,
    ensure_ledger_fn: Callable[[], Path] = None,
    run_eval_at_fn: Callable[[list[str], dict[str, str] | None], int] = run_eval_at,
    commit_push_fn: Callable[[Path, str], bool] = None,
) -> dict[str, Any]:
    """Run exactly one worker iteration. Dependency-injected so tests can fake git/subprocess
    without a real remote; the CLI wires the real implementations (see ``main``)."""
    python_exe = python_exe or (PROJECT_ROOT / ".venv" / "bin" / "python")
    resolve_sha_fn = resolve_sha_fn or (lambda: resolve_latest_sha(branch=branch))
    ensure_ledger_fn = ensure_ledger_fn or (
        lambda: ensure_ledger_worktree(worktree_dir=ledger_worktree, ledger_branch=ledger_branch,
                                        base_branch=branch)
    )
    commit_push_fn = commit_push_fn or (
        lambda wt, msg: commit_and_push_ledger(wt, message=msg, branch=ledger_branch)
    )

    sha = resolve_sha_fn()
    ledger_dir = ensure_ledger_fn() / "docs" / "phase2_baselines"
    history = read_history_jsonl(ledger_dir / "history.jsonl")
    touched_parsing = sha_touched_parsing(sha)
    labels = pick_labels_to_run(history, sha=sha, touched_parsing=touched_parsing)

    plan = {"sha": sha, "touched_parsing": touched_parsing, "labels": labels}
    if dry_run or not labels:
        return {**plan, "ran": [], "dry_run": dry_run}

    ran = []
    for label in labels:
        env = {"TPC_P2_LLM_PARSE": "0"} if label == DET_LABEL else None
        cmd = build_eval_at_cmd(sha=sha, label=label, ledger_dir=ledger_dir, python_exe=python_exe)
        rc = run_eval_at_fn(cmd, env)
        ran.append({"label": label, "returncode": rc})
        if rc == 0:
            commit_push_fn(ledger_worktree, f"phase2-eval: {label} @ {sha[:8]}")
    return {**plan, "ran": ran, "dry_run": dry_run}


# --- CLI ---------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--branch", default=DEFAULT_BRANCH)
    p.add_argument("--ledger-branch", default=DEFAULT_LEDGER_BRANCH)
    p.add_argument("--ledger-worktree", default=str(DEFAULT_LEDGER_WORKTREE))
    p.add_argument("--once", action="store_true", help="Run a single iteration and exit.")
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print the plan (sha, labels that would run) without running or pushing anything.",
    )
    p.add_argument("--poll-interval-sec", type=float, default=DEFAULT_POLL_INTERVAL_SEC)
    p.add_argument("--pidfile", default=str(DEFAULT_PIDFILE))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    pidfile = Path(args.pidfile)

    holder = pidfile_holder_alive(pidfile)
    if holder is not None:
        print(f"error: another worker instance is running (pid {holder}, {pidfile})", file=sys.stderr)
        return 1
    if not args.dry_run:
        pidfile.write_text(str(os.getpid()), encoding="utf-8")

    try:
        while True:
            result = run_once(
                dry_run=args.dry_run, branch=args.branch, ledger_branch=args.ledger_branch,
                ledger_worktree=Path(args.ledger_worktree),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.once:
                return 0
            time.sleep(args.poll_interval_sec)
    finally:
        if not args.dry_run and pidfile.exists():
            pidfile.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
