"""Unit and integration tests for scripts/phase2_eval_at.py.

The integration test builds a throwaway synthetic git repository with a fake recorder. It can
commit during an evaluation and assert git-sha truthfulness without mutating real project history.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import phase2_eval_at as ea


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)


# --- build_recorder_cmd (pure) ---------------------------------------------


def test_build_recorder_cmd_injects_history_dir_when_absent():
    cmd = ea.build_recorder_cmd(
        python_exe=Path("/venv/python"),
        worktree_dir=Path("/tmp/wt/abc123"),
        recorder_args=["--limit", "2"],
        ledger_dir=Path("/repo/results/phase2_baselines"),
    )
    assert cmd == [
        "/venv/python",
        "/tmp/wt/abc123/scripts/phase2_record_baseline.py",
        "--history-dir", "/repo/results/phase2_baselines",
        "--limit", "2",
    ]


def test_build_recorder_cmd_respects_explicit_history_dir():
    cmd = ea.build_recorder_cmd(
        python_exe=Path("/venv/python"),
        worktree_dir=Path("/tmp/wt/abc123"),
        recorder_args=["--history-dir", "/custom", "--limit", "2"],
        ledger_dir=Path("/repo/results/phase2_baselines"),
    )
    assert cmd.count("--history-dir") == 1
    assert "/custom" in cmd
    assert "/repo/results/phase2_baselines" not in cmd


def test_build_recorder_cmd_respects_history_dir_equals_form():
    cmd = ea.build_recorder_cmd(
        python_exe=Path("/venv/python"),
        worktree_dir=Path("/tmp/wt/abc123"),
        recorder_args=["--history-dir=/custom"],
        ledger_dir=Path("/repo/results/phase2_baselines"),
    )
    assert cmd.count("--history-dir") == 0  # folded into the "--history-dir=/custom" token
    assert "--history-dir=/custom" in cmd


# --- link_shared_state (filesystem, no git) --------------------------------


def test_link_shared_state_symlinks_missing_and_tracked_paths(tmp_path):
    main_repo = tmp_path / "main"
    worktree_dir = tmp_path / "worktree"
    (main_repo / "cache").mkdir(parents=True)
    (main_repo / "cache" / "warm.json").write_text("{}")
    (main_repo / "results").mkdir()
    (main_repo / ".env").write_text("KEY=1")
    # agent_env/runs deliberately absent from main_repo -- link_shared_state must skip it, not fail.

    # Simulate what `git worktree add` checked out: an empty results/ dir (tracked subpaths would
    # exist for the real repo, but the point here is that *something* is already on disk) and no
    # cache/ or .env at all (both are ignored/newer than some pinned shas).
    (worktree_dir / "results").mkdir(parents=True)

    ea.link_shared_state(worktree_dir, main_repo=main_repo)

    assert (worktree_dir / "cache").is_symlink()
    assert (worktree_dir / "cache" / "warm.json").read_text() == "{}"
    assert (worktree_dir / "results").is_symlink()
    assert (worktree_dir / ".env").is_symlink()
    assert (worktree_dir / ".env").read_text() == "KEY=1"
    assert not (worktree_dir / "agent_env" / "runs").exists()


def test_link_shared_state_symlinks_backend_config_toml(tmp_path):
    # Regression: the LLM backend is configured in the gitignored agent_env/config.toml. If it is
    # not shared into the pinned worktree, resolve_llm_client_and_flags falls back to backend=none
    # and the pinned eval silently runs the deterministic (no-LLM) parser (2026-07-21).
    main_repo = tmp_path / "main"
    worktree_dir = tmp_path / "worktree"
    (main_repo / "agent_env").mkdir(parents=True)
    (main_repo / "agent_env" / "config.toml").write_text("[phase2.llm]\nbackend = 'deepinfra'\n")
    worktree_dir.mkdir()

    ea.link_shared_state(worktree_dir, main_repo=main_repo)

    linked = worktree_dir / "agent_env" / "config.toml"
    assert linked.is_symlink()
    assert "deepinfra" in linked.read_text()


def test_link_shared_state_is_idempotent(tmp_path):
    main_repo = tmp_path / "main"
    worktree_dir = tmp_path / "worktree"
    (main_repo / "cache").mkdir(parents=True)
    worktree_dir.mkdir()

    ea.link_shared_state(worktree_dir, main_repo=main_repo)
    ea.link_shared_state(worktree_dir, main_repo=main_repo)  # must not raise on rerun

    assert (worktree_dir / "cache").is_symlink()
    assert (worktree_dir / "cache").resolve() == (main_repo / "cache").resolve()


# --- create_worktree / remove_worktree (real git, throwaway repo) ----------


def test_create_worktree_checks_out_pinned_sha(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "f.txt").write_text("v1")
    _git("add", "f.txt", cwd=repo)
    _git("commit", "-q", "-m", "v1", cwd=repo)
    sha_v1 = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()

    (repo / "f.txt").write_text("v2")
    _git("commit", "-q", "-a", "-m", "v2", cwd=repo)

    worktree_root = tmp_path / "worktrees"
    orig_project_root = ea.PROJECT_ROOT
    ea.PROJECT_ROOT = repo
    try:
        worktree_dir = ea.create_worktree(sha_v1, worktree_root=worktree_root)
        try:
            assert (worktree_dir / "f.txt").read_text() == "v1"
        finally:
            ea.remove_worktree(worktree_dir, main_repo=repo)
    finally:
        ea.PROJECT_ROOT = orig_project_root


def test_create_worktree_refuses_if_target_exists(tmp_path):
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "f.txt").write_text("v1")
    _git("add", "f.txt", cwd=repo)
    _git("commit", "-q", "-m", "v1", cwd=repo)

    worktree_root = tmp_path / "worktrees"
    orig_project_root = ea.PROJECT_ROOT
    ea.PROJECT_ROOT = repo
    try:
        worktree_dir = ea.create_worktree("HEAD", worktree_root=worktree_root)
        try:
            with pytest.raises(RuntimeError, match="already exists"):
                ea.create_worktree("HEAD", worktree_root=worktree_root)
        finally:
            ea.remove_worktree(worktree_dir, main_repo=repo)
    finally:
        ea.PROJECT_ROOT = orig_project_root


# --- End-to-end sha-truthfulness (synthetic repo + fake recorder) ---------

_FAKE_RECORDER = '''
import json
import subprocess
import sys
from pathlib import Path

sha = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[1], text=True
).strip()

ledger_dir = None
args = sys.argv[1:]
if "--history-dir" in args:
    ledger_dir = Path(args[args.index("--history-dir") + 1])
ledger_dir.mkdir(parents=True, exist_ok=True)
(ledger_dir / "row.json").write_text(json.dumps({"git_sha": sha}))
'''


@pytest.mark.integration
def test_eval_at_git_sha_is_pinned_sha_even_if_main_repo_advances(tmp_path):
    """A commit landing in the main tree after worktree creation must not change the recorded
    pinned ``git_sha``."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "phase2_record_baseline.py").write_text(_FAKE_RECORDER)
    (repo / "parse_constraints.py").write_text("# v1\n")
    _git("add", "-A", cwd=repo)
    _git("commit", "-q", "-m", "v1", cwd=repo)
    pinned_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()

    ledger_dir = tmp_path / "ledger"
    worktree_root = tmp_path / "worktrees"

    orig_project_root = ea.PROJECT_ROOT
    ea.PROJECT_ROOT = repo
    try:
        worktree_dir = ea.create_worktree(pinned_sha, worktree_root=worktree_root)
        try:
            # Simulate a commit landing in the main tree *after* the worktree was created --
            # this is the scenario the freeze rule used to guard against.
            (repo / "parse_constraints.py").write_text("# v2 -- landed mid-run\n")
            _git("commit", "-q", "-a", "-m", "v2 mid-run", cwd=repo)

            rc = ea.run_recorder(
                worktree_dir, [], python_exe=Path(sys.executable), ledger_dir=ledger_dir,
            )
            assert rc == 0
        finally:
            ea.remove_worktree(worktree_dir, main_repo=repo)
    finally:
        ea.PROJECT_ROOT = orig_project_root

    row = json.loads((ledger_dir / "row.json").read_text())
    assert row["git_sha"] == pinned_sha
