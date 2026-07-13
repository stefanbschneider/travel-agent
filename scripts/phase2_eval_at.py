#!/usr/bin/env python3
"""Run a Phase 2 eval command against a pinned git worktree checkout (plan-2 Step 1).

Long evals (``scripts/phase2_record_baseline.py``) re-import on-disk code mid-run in their
chunked subprocesses, and the recorder's ``_git_sha()`` stamps ``git rev-parse HEAD`` at *write*
time -- so any commit landing in the main tree while a long eval is running silently produces a
mixed-code, mislabeled ledger row. Running the eval against an explicit ``git worktree`` checkout
of a pinned sha fixes both problems: the main tree is free to keep developing, and the row's
``git_sha`` is truthful by construction (it is the sha that was actually checked out and solved
against, not whatever HEAD happens to be when the recorder finishes writing).

Usage:
    scripts/phase2_eval_at.py --sha <ref> [--keep] -- <phase2_record_baseline.py args...>

Example:
    scripts/phase2_eval_at.py --sha HEAD -- --split-set val --fold 0 --budget-sec 100 \
        --label fastfpr-mychange --parallel 3
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKTREE_ROOT = Path("/tmp/phase2_eval")

# Gitignored state the rehearsal reads/writes (see .gitignore) that a fresh worktree checkout
# would otherwise start empty: the LLM response + parser-vs-oracle caches, per-method result
# JSON + run telemetry, and the LLM API key file. ``.env`` is tracked in this repo (force-added
# by fac88ca0) but some older shas predate that commit and would check out without it -- symlink
# it unconditionally so every pinned eval can reach the configured backend regardless of sha.
# ``chinatravel/data/`` is fully committed, so the worktree already has it without symlinking.
SHARED_RELPATHS = ["cache", "results", "agent_env/runs", ".env"]

DEFAULT_LEDGER_DIR = PROJECT_ROOT / "docs" / "phase2_baselines"


def _git_output(*args: str, cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def resolve_sha(ref: str) -> str:
    """Resolve ``ref`` to a full sha in the main repo (before the worktree exists)."""
    return _git_output("rev-parse", ref, cwd=PROJECT_ROOT)


def short_sha(sha: str) -> str:
    return _git_output("rev-parse", "--short", sha, cwd=PROJECT_ROOT)


def create_worktree(sha: str, *, worktree_root: Path = WORKTREE_ROOT) -> Path:
    """``git worktree add`` a detached checkout of ``sha`` under ``worktree_root``."""
    worktree_dir = worktree_root / short_sha(sha)
    if worktree_dir.exists():
        raise RuntimeError(
            f"{worktree_dir} already exists -- remove a stale worktree first: "
            f"git worktree remove --force {worktree_dir}"
        )
    worktree_root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", str(worktree_dir), sha, "--detach"],
        cwd=PROJECT_ROOT, check=True,
    )
    return worktree_dir


def link_shared_state(
    worktree_dir: Path, *, main_repo: Path = PROJECT_ROOT, relpaths=SHARED_RELPATHS
) -> None:
    """Replace each gitignored path the worktree checked out (missing, or an empty tracked dir)
    with a symlink to ``main_repo``'s copy, so the pinned checkout shares cache/results state
    instead of starting cold."""
    for rel in relpaths:
        src = main_repo / rel
        if not src.exists():
            continue  # e.g. agent_env/runs doesn't exist until the first run anywhere
        dst = worktree_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink():
            dst.unlink()
        elif dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists():
            dst.unlink()
        dst.symlink_to(src, target_is_directory=src.is_dir())


def remove_worktree(worktree_dir: Path, *, main_repo: Path = PROJECT_ROOT) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_dir)],
        cwd=main_repo, check=True,
    )


def build_recorder_cmd(
    *, python_exe: Path, worktree_dir: Path, recorder_args: list[str], ledger_dir: Path
) -> list[str]:
    """Pure command-line assembly (split out from ``run_recorder`` so it's unit-testable without
    actually spawning a subprocess)."""
    recorder = worktree_dir / "scripts" / "phase2_record_baseline.py"
    cmd = [str(python_exe), str(recorder)]
    has_history_dir = any(
        a == "--history-dir" or a.startswith("--history-dir=") for a in recorder_args
    )
    if not has_history_dir:
        cmd += ["--history-dir", str(ledger_dir)]
    cmd += recorder_args
    return cmd


def run_recorder(
    worktree_dir: Path,
    recorder_args: list[str],
    *,
    python_exe: Path | None = None,
    ledger_dir: Path = DEFAULT_LEDGER_DIR,
) -> int:
    python_exe = python_exe or (PROJECT_ROOT / ".venv" / "bin" / "python")
    cmd = build_recorder_cmd(
        python_exe=python_exe, worktree_dir=worktree_dir, recorder_args=recorder_args,
        ledger_dir=ledger_dir,
    )
    proc = subprocess.run(cmd, cwd=str(worktree_dir))
    return proc.returncode


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--sha", required=True, help="Git ref/sha to pin the eval to.")
    p.add_argument(
        "--keep", action="store_true",
        help="Keep the worktree after a successful run (for debugging); always kept on failure.",
    )
    p.add_argument(
        "--ledger-dir", default=str(DEFAULT_LEDGER_DIR),
        help="Where the recorder writes history.jsonl/latest.*/runs/ (default: main repo's "
        "docs/phase2_baselines, so pinned-worktree rows land alongside normal ones).",
    )
    p.add_argument(
        "recorder_args", nargs=argparse.REMAINDER,
        help="Args passed through to scripts/phase2_record_baseline.py -- prefix with `--` to "
        "separate them from this script's own flags, e.g.: "
        "phase2_eval_at.py --sha HEAD -- --limit 2 --budget-sec 10",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    recorder_args = list(args.recorder_args)
    if recorder_args and recorder_args[0] == "--":
        recorder_args = recorder_args[1:]

    sha = resolve_sha(args.sha)
    worktree_dir = create_worktree(sha)
    rc = 1
    try:
        link_shared_state(worktree_dir)
        rc = run_recorder(worktree_dir, recorder_args, ledger_dir=Path(args.ledger_dir))
    finally:
        if rc == 0 and not args.keep:
            remove_worktree(worktree_dir)
        else:
            state = "kept (--keep)" if rc == 0 else f"kept (rc={rc}, inspect before retrying)"
            print(f"[phase2_eval_at] worktree {state}: {worktree_dir}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
