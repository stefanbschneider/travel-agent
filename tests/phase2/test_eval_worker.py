"""Unit tests for ``scripts/phase2_eval_worker.py``.

Pure-function tests plus a dependency-injected ``run_once`` dry-run/no-op check. They use no
real git remote or solver evaluation and reuse the fake-repository pattern from
``tests/phase2/test_diff_eval.py`` for allowlist-touch checks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import phase2_eval_worker as worker


# --- sha_already_evaluated / pick_labels_to_run -----------------------------


def test_sha_already_evaluated_true_on_exact_match():
    rows = [{"git_sha": "abc123", "label": "ci-300s"}]
    assert worker.sha_already_evaluated(rows, sha="abc123", label="ci-300s")


def test_sha_already_evaluated_false_on_label_mismatch():
    rows = [{"git_sha": "abc123", "label": "ci-300s-det"}]
    assert not worker.sha_already_evaluated(rows, sha="abc123", label="ci-300s")


def test_sha_already_evaluated_false_on_sha_mismatch():
    rows = [{"git_sha": "other", "label": "ci-300s"}]
    assert not worker.sha_already_evaluated(rows, sha="abc123", label="ci-300s")


def test_sha_already_evaluated_empty_history():
    assert not worker.sha_already_evaluated([], sha="abc123", label="ci-300s")


def test_pick_labels_to_run_fresh_sha_not_touching_parsing():
    labels = worker.pick_labels_to_run([], sha="abc123", touched_parsing=False)
    assert labels == [worker.CANONICAL_LABEL]


def test_pick_labels_to_run_fresh_sha_touching_parsing():
    labels = worker.pick_labels_to_run([], sha="abc123", touched_parsing=True)
    assert labels == [worker.CANONICAL_LABEL, worker.DET_LABEL]


def test_pick_labels_to_run_canonical_already_done():
    rows = [{"git_sha": "abc123", "label": worker.CANONICAL_LABEL}]
    labels = worker.pick_labels_to_run(rows, sha="abc123", touched_parsing=True)
    assert labels == [worker.DET_LABEL]


def test_pick_labels_to_run_both_already_done_is_noop():
    rows = [
        {"git_sha": "abc123", "label": worker.CANONICAL_LABEL},
        {"git_sha": "abc123", "label": worker.DET_LABEL},
    ]
    labels = worker.pick_labels_to_run(rows, sha="abc123", touched_parsing=True)
    assert labels == []


def test_pick_labels_to_run_ignores_other_shas():
    rows = [{"git_sha": "different-sha", "label": worker.CANONICAL_LABEL}]
    labels = worker.pick_labels_to_run(rows, sha="abc123", touched_parsing=False)
    assert labels == [worker.CANONICAL_LABEL]


# --- read_history_jsonl ------------------------------------------------------


def test_read_history_jsonl_missing_file_is_empty(tmp_path):
    assert worker.read_history_jsonl(tmp_path / "nope.jsonl") == []


def test_read_history_jsonl_parses_lines(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text(
        json.dumps({"git_sha": "a", "label": "x"}) + "\n"
        + json.dumps({"git_sha": "b", "label": "y"}) + "\n"
    )
    rows = worker.read_history_jsonl(path)
    assert [r["git_sha"] for r in rows] == ["a", "b"]


def test_read_history_jsonl_skips_blank_lines(tmp_path):
    path = tmp_path / "history.jsonl"
    path.write_text(json.dumps({"git_sha": "a", "label": "x"}) + "\n\n")
    rows = worker.read_history_jsonl(path)
    assert len(rows) == 1


# --- pidfile guard ------------------------------------------------------------


def test_pidfile_holder_alive_missing_file(tmp_path):
    assert worker.pidfile_holder_alive(tmp_path / "nope.pid") is None


def test_pidfile_holder_alive_stale_pid(tmp_path):
    pidfile = tmp_path / "worker.pid"
    pidfile.write_text("999999999")  # not a real pid
    assert worker.pidfile_holder_alive(pidfile) is None


def test_pidfile_holder_alive_live_pid(tmp_path):
    pidfile = tmp_path / "worker.pid"
    pidfile.write_text(str(os.getpid()))
    assert worker.pidfile_holder_alive(pidfile) == os.getpid()


def test_pidfile_holder_alive_garbage_contents(tmp_path):
    pidfile = tmp_path / "worker.pid"
    pidfile.write_text("not-a-pid")
    assert worker.pidfile_holder_alive(pidfile) is None


# --- sha_touched_parsing (real tmp git repo, same pattern as test_diff_eval) --


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo_with_commit(root, files: dict[str, str]):
    root.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", "init", cwd=root)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def _commit_change(root, rel, content, msg="change"):
    (root / rel).write_text(content)
    _git("add", "-A", cwd=root)
    _git("commit", "-q", "-m", msg, cwd=root)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def test_sha_touched_parsing_true_for_allowlisted_file(tmp_path):
    repo = tmp_path / "repo"
    _init_repo_with_commit(repo, {"parse_constraints.py": "v1\n", "other.py": "v1\n"})
    sha = _commit_change(repo, "parse_constraints.py", "v2\n")
    assert worker.sha_touched_parsing(sha, cwd=repo)


def test_sha_touched_parsing_false_for_non_allowlisted_file(tmp_path):
    repo = tmp_path / "repo"
    _init_repo_with_commit(repo, {"parse_constraints.py": "v1\n", "solver.py": "v1\n"})
    sha = _commit_change(repo, "solver.py", "v2\n")
    assert not worker.sha_touched_parsing(sha, cwd=repo)


def test_sha_touched_parsing_root_commit_is_false(tmp_path):
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(repo, {"parse_constraints.py": "v1\n"})
    assert not worker.sha_touched_parsing(sha, cwd=repo)


# --- build_eval_at_cmd (pure) -------------------------------------------------


def test_build_eval_at_cmd_shape(tmp_path):
    cmd = worker.build_eval_at_cmd(
        sha="abc123", label="ci-300s", ledger_dir=tmp_path / "ledger",
        python_exe=Path("/usr/bin/python3"),
    )
    assert cmd[0] == "/usr/bin/python3"
    assert cmd[2:4] == ["--sha", "abc123"]
    assert "--ledger-dir" in cmd
    assert cmd[cmd.index("--label") + 1] == "ci-300s"
    assert "--" in cmd


# --- run_once orchestration (dependency-injected, no real git/subprocess) ----


def test_run_once_dry_run_reports_plan_without_running():
    calls = {"eval_at": 0, "commit_push": 0}

    def fake_run_eval_at(cmd, env):
        calls["eval_at"] += 1
        return 0

    def fake_commit_push(wt, msg):
        calls["commit_push"] += 1
        return True

    result = worker.run_once(
        dry_run=True,
        resolve_sha_fn=lambda: "deadbeef",
        ensure_ledger_fn=lambda: Path("/tmp/does-not-matter"),
        run_eval_at_fn=fake_run_eval_at,
        commit_push_fn=fake_commit_push,
    )
    assert result["sha"] == "deadbeef"
    assert result["dry_run"] is True
    assert calls["eval_at"] == 0
    assert calls["commit_push"] == 0


def test_run_once_second_call_is_noop_when_already_evaluated(tmp_path):
    ledger_root = tmp_path / "ledger_wt"
    (ledger_root / "results" / "phase2_baselines").mkdir(parents=True)
    history_path = ledger_root / "results" / "phase2_baselines" / "history.jsonl"
    history_path.write_text(json.dumps({"git_sha": "deadbeef", "label": worker.CANONICAL_LABEL}) + "\n")

    calls = {"eval_at": 0, "commit_push": 0}

    def fake_run_eval_at(cmd, env):
        calls["eval_at"] += 1
        return 0

    def fake_commit_push(wt, msg):
        calls["commit_push"] += 1
        return True

    result = worker.run_once(
        dry_run=False,
        resolve_sha_fn=lambda: "deadbeef",
        ensure_ledger_fn=lambda: ledger_root,
        run_eval_at_fn=fake_run_eval_at,
        commit_push_fn=fake_commit_push,
    )
    assert result["labels"] == []
    assert result["ran"] == []
    assert calls["eval_at"] == 0
    assert calls["commit_push"] == 0


def test_run_once_runs_and_publishes_missing_labels(tmp_path):
    ledger_root = tmp_path / "ledger_wt"
    (ledger_root / "results" / "phase2_baselines").mkdir(parents=True)

    calls = {"eval_at": [], "commit_push": []}

    def fake_run_eval_at(cmd, env):
        calls["eval_at"].append((cmd, env))
        return 0

    def fake_commit_push(wt, msg):
        calls["commit_push"].append(msg)
        return True

    result = worker.run_once(
        dry_run=False,
        resolve_sha_fn=lambda: "deadbeef",
        ensure_ledger_fn=lambda: ledger_root,
        run_eval_at_fn=fake_run_eval_at,
        commit_push_fn=fake_commit_push,
    )
    assert result["labels"] == [worker.CANONICAL_LABEL]
    assert len(calls["eval_at"]) == 1
    assert len(calls["commit_push"]) == 1
    assert "deadbeef"[:8] in calls["commit_push"][0]


def test_run_once_skips_push_on_eval_at_failure(tmp_path):
    ledger_root = tmp_path / "ledger_wt"
    (ledger_root / "results" / "phase2_baselines").mkdir(parents=True)

    def failing_run_eval_at(cmd, env):
        return 1

    calls = {"commit_push": 0}

    def fake_commit_push(wt, msg):
        calls["commit_push"] += 1
        return True

    result = worker.run_once(
        dry_run=False,
        resolve_sha_fn=lambda: "deadbeef",
        ensure_ledger_fn=lambda: ledger_root,
        run_eval_at_fn=failing_run_eval_at,
        commit_push_fn=fake_commit_push,
    )
    assert result["ran"] == [{"label": worker.CANONICAL_LABEL, "returncode": 1}]
    assert calls["commit_push"] == 0


# --- CLI --once --dry-run integration (real argv, fake git via the real repo) -


def test_cli_once_dry_run_smoke(tmp_path):
    """The real CLI, run once against this actual repo's origin/stefan/phase2 -- --dry-run means
    it only fetches/resolves/reads history, never runs an eval or pushes anything (though it does
    create the ledger worktree as a read-only side effect of locating history.jsonl, hence
    --ledger-worktree pointed at tmp_path instead of the real default path). Confirms the
    plumbing (argv parsing, pidfile skip, JSON plan on stdout) end to end without any solver
    cost. Skipped if there's no network access to the origin remote in this environment."""
    import pytest

    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "phase2_eval_worker.py"
    ledger_worktree = tmp_path / "phase2_eval_ledger"
    test_ledger_branch = "phase2-eval-ledger-test-smoke"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--once", "--dry-run",
             "--ledger-worktree", str(ledger_worktree), "--ledger-branch", test_ledger_branch,
             "--pidfile", str(tmp_path / "worker.pid")],
            cwd=str(repo_root), capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0 and "fatal" in (proc.stderr or "").lower():
            pytest.skip(f"no git remote access in this environment: {proc.stderr.strip()[:200]}")
        assert proc.returncode == 0, proc.stderr
        plan = json.loads(proc.stdout)
        assert "sha" in plan
        assert plan["dry_run"] is True
        assert plan["ran"] == []
    finally:
        # ensure_ledger_worktree (a read-only lookup here, since dry-run never pushes) still
        # creates a real worktree + local branch in THIS repo -- clean both up unconditionally.
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(ledger_worktree)],
            cwd=str(repo_root), capture_output=True, text=True,
        )
        subprocess.run(
            ["git", "branch", "-D", test_ledger_branch],
            cwd=str(repo_root), capture_output=True, text=True,
        )
