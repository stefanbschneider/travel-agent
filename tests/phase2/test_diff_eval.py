"""Unit tests for scripts/phase2_diff_eval.py and the fingerprinting it depends on
(plan-2 Step 2). The measured, real-repo acceptance check (projected FPR byte-equal to a full
fresh run on a real commit pair) is recorded in the step's commit message, not repeated here as
an automated test (it needs a real solver + real git history to be meaningful).
"""

from __future__ import annotations

import copy
import subprocess
from types import SimpleNamespace

import parser_vs_oracle as parser_mod
import phase2_diff_eval as de
import phase2_record_baseline as recorder_mod


def _flags(*, disjunction=True, llm_parse=False, entity_resolution=False):
    return SimpleNamespace(disjunction=disjunction, llm_parse=llm_parse, entity_resolution=entity_resolution)


# --- fingerprint stability (real val queries -- a hand-fabricated query dict skips the fields
# the regex actually keys on, see the debugging note in the plan-2 Step 2 commit) -------------


def _load_two_real_queries():
    ids, data = parser_mod._load_queries("tpc_phase2_val")
    u1, u2 = ids[0], ids[1]
    q1, q2 = data[u1], data[u2]
    q1.setdefault("uid", u1)
    q2.setdefault("uid", u2)
    return q1, q2


def test_fingerprint_stable_for_same_input():
    q1, _ = _load_two_real_queries()
    fp1 = recorder_mod.compute_fingerprint(q1, flags=_flags(), llm_client=None)
    fp2 = recorder_mod.compute_fingerprint(copy.deepcopy(q1), flags=_flags(), llm_client=None)
    assert fp1 == fp2
    assert len(fp1) == 64  # sha256 hex digest


def test_fingerprint_changes_when_constraint_bearing_text_changes():
    """Simulates a parser regression: dropping the sentence that carries a required-attraction
    constraint changes the no-oracle parsed side (the oracle side, driven by hard_logic_py, is
    untouched) -- exactly the scenario phase2_diff_eval.py must detect as "changed"."""
    q, _ = _load_two_real_queries()
    fp_base = recorder_mod.compute_fingerprint(q, flags=_flags(), llm_client=None)

    q_mod = copy.deepcopy(q)
    # Keep only the clause before "Requirements:" (see the fixture's actual phrasing).
    q_mod["nature_language"] = q["nature_language"].split("Requirements:")[0].strip()
    fp_changed = recorder_mod.compute_fingerprint(q_mod, flags=_flags(), llm_client=None)

    assert fp_base != fp_changed


def test_fingerprint_same_when_recomputed_from_an_untouched_copy():
    # The splice's "unchanged" bucket relies on this: re-fingerprinting an untouched query must
    # reproduce the exact same hash, not just an equivalent one.
    q, _ = _load_two_real_queries()
    fp_a = recorder_mod.compute_fingerprint(q, flags=_flags(), llm_client=None)
    fp_b = recorder_mod.compute_fingerprint(copy.deepcopy(q), flags=_flags(), llm_client=None)
    assert fp_a == fp_b


def test_compute_fingerprints_keys_every_uid():
    q1, q2 = _load_two_real_queries()
    query_data = {q1["uid"]: q1, q2["uid"]: q2}
    fps = recorder_mod.compute_fingerprints(
        query_data, [q1["uid"], q2["uid"]], flags=_flags(), llm_client=None
    )
    assert set(fps) == {q1["uid"], q2["uid"]}
    assert fps[q1["uid"]] != fps[q2["uid"]]


# --- splice math (compute_projection), pure ---------------------------------


def test_compute_projection_all_unchanged_matches_baseline_fpr():
    uids = ["a", "b", "c", "d"]
    proj = de.compute_projection(
        uids=uids, changed=set(), baseline_pass_ids={"a", "b", "c"}, new_pass_ids=set(),
    )
    assert proj["projected_fpr"] == 75.0
    assert proj["changed_n"] == 0
    assert proj["flips"] == []


def test_compute_projection_splices_changed_uids_from_new_results():
    uids = ["a", "b", "c", "d"]
    # baseline: a,b pass; c,d fail. "c" flips to pass after re-solving; "d" stays failed;
    # unchanged "a","b" keep their baseline outcome untouched.
    proj = de.compute_projection(
        uids=uids,
        changed={"c", "d"},
        baseline_pass_ids={"a", "b"},
        new_pass_ids={"c"},
    )
    assert proj["unchanged_passes"] == 2  # a, b
    assert proj["changed_passes"] == 1  # c
    assert proj["projected_fpr"] == 75.0  # 3/4
    assert proj["flips"] == [{"uid": "c", "baseline_pass": False, "new_pass": True}]


def test_compute_projection_detects_pass_to_fail_flip():
    uids = ["a", "b"]
    proj = de.compute_projection(
        uids=uids, changed={"a"}, baseline_pass_ids={"a", "b"}, new_pass_ids=set(),
    )
    assert proj["flips"] == [{"uid": "a", "baseline_pass": True, "new_pass": False}]
    assert proj["projected_fpr"] == 50.0


def test_compute_projection_empty_uids_is_zero_not_crash():
    proj = de.compute_projection(uids=[], changed=set(), baseline_pass_ids=set(), new_pass_ids=set())
    assert proj["projected_fpr"] == 0.0
    assert proj["n"] == 0


# --- allowlist guard ---------------------------------------------------------


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


def test_guard_allows_parse_only_changes(tmp_path):
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(repo, {"parse_constraints.py": "v1\n", "other.py": "v1\n"})
    (repo / "parse_constraints.py").write_text("v2\n")
    changed = de.guard_parser_only_changes(sha, cwd=repo)
    assert changed == ["parse_constraints.py"]


def test_guard_refuses_non_allowlisted_changes(tmp_path):
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(repo, {"parse_constraints.py": "v1\n", "solver.py": "v1\n"})
    (repo / "solver.py").write_text("v2\n")
    try:
        de.guard_parser_only_changes(sha, cwd=repo)
        assert False, "expected UnsafeDiffEvalError"
    except de.UnsafeDiffEvalError as exc:
        assert "solver.py" in str(exc)


def test_guard_unsafe_override_allows_anything(tmp_path):
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(repo, {"solver.py": "v1\n"})
    (repo / "solver.py").write_text("v2\n")
    changed = de.guard_parser_only_changes(sha, unsafe=True, cwd=repo)
    assert changed == ["solver.py"]


def test_guard_no_changes_passes(tmp_path):
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(repo, {"solver.py": "v1\n"})
    changed = de.guard_parser_only_changes(sha, cwd=repo)
    assert changed == []


def test_guard_ignores_test_only_changes(tmp_path):
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(
        repo, {"parse_constraints.py": "v1\n", "tests/phase2/test_x.py": "v1\n"}
    )
    (repo / "parse_constraints.py").write_text("v2\n")
    (repo / "tests" / "phase2" / "test_x.py").write_text("v2\n")
    changed = de.guard_parser_only_changes(sha, cwd=repo)
    assert set(changed) == {"parse_constraints.py", "tests/phase2/test_x.py"}


def test_guard_ignores_docs_only_changes(tmp_path):
    """Recording a baseline row is itself a commit under docs/phase2_baselines/ -- without this
    exemption, every ledger row would permanently poison itself as a diff-eval base the moment
    it's committed, even with zero solver-affecting code changed (2026-07-13 VM2 finding)."""
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(
        repo,
        {
            "parse_constraints.py": "v1\n",
            "docs/tpc_phase2_plan3.md": "v1\n",
            "docs/phase2_baselines/runs/20260101T000000Z.json": "{}\n",
        },
    )
    (repo / "docs" / "tpc_phase2_plan3.md").write_text("v2\n")
    (repo / "docs" / "phase2_baselines" / "runs" / "20260101T000000Z.json").write_text('{"x":1}\n')
    changed = de.guard_parser_only_changes(sha, cwd=repo)
    assert set(changed) == {
        "docs/tpc_phase2_plan3.md",
        "docs/phase2_baselines/runs/20260101T000000Z.json",
    }


def test_guard_still_refuses_non_allowlisted_changes_mixed_with_docs(tmp_path):
    repo = tmp_path / "repo"
    sha = _init_repo_with_commit(
        repo, {"solver.py": "v1\n", "docs/tpc_phase2_plan3.md": "v1\n"}
    )
    (repo / "solver.py").write_text("v2\n")
    (repo / "docs" / "tpc_phase2_plan3.md").write_text("v2\n")
    try:
        de.guard_parser_only_changes(sha, cwd=repo)
        assert False, "expected UnsafeDiffEvalError"
    except de.UnsafeDiffEvalError as exc:
        assert "solver.py" in str(exc)
        assert "docs/tpc_phase2_plan3.md" not in str(exc)
