"""Unit tests for rehearse_phase2 pure helpers (Task 7).

The heavy end-to-end / solver-only runs are exercised via an opt-in integration test; here we test
the deterministic fold selection, the held-out-test guard, and attribution formatting.
"""

from __future__ import annotations

import pytest

import rehearse_phase2 as R


UIDS = [f"uid{i:04d}" for i in range(100)]


def test_select_fold_deterministic():
    a = R.select_fold(UIDS, fold=0, folds=5, seed=1)
    b = R.select_fold(UIDS, fold=0, folds=5, seed=1)
    assert a == b


def test_folds_are_disjoint_and_cover_all():
    seen = []
    for f in range(5):
        seen.extend(R.select_fold(UIDS, fold=f, folds=5, seed=1))
    assert sorted(seen) == sorted(UIDS)
    assert len(seen) == len(set(seen))  # disjoint


def test_select_fold_subset_of_input():
    fold = R.select_fold(UIDS, fold=2, folds=5, seed=1)
    assert set(fold).issubset(set(UIDS))
    assert 0 < len(fold) <= len(UIDS)


def test_resolve_split_set_defaults_to_val():
    name, is_test = R.resolve_split_set("val")
    assert name == "tpc_phase2_val"
    assert is_test is False


def test_resolve_split_set_test_is_flagged(capsys):
    name, is_test = R.resolve_split_set("test")
    assert name == "tpc_phase2_test"
    assert is_test is True
    warning = capsys.readouterr().out.lower()
    assert "held-out" in warning or "warning" in warning


def test_format_attribution_orders_ceiling_solver_e2e():
    line = R.format_attribution(ceiling=95.0, solver_only=90.0, end_to_end=70.0)
    assert "95.0" in line and "90.0" in line and "70.0" in line
    # parsing loss = solver_only - end_to_end; solver headroom = ceiling - solver_only
    assert "20.0" in line  # parsing loss
    assert "5.0" in line   # solver headroom


class _FakeAgent:
    def __init__(self, recovered):
        self._recovered = recovered

    def get_timeout_recovery_plan(self):
        return self._recovered


def test_recover_or_fallback_prefers_valid_recovery_plan():
    recovered = {"people_number": 2, "start_city": "A", "target_city": "B", "itinerary": [{"day": 1}]}
    plan = R._recover_or_fallback(_FakeAgent(recovered), {"people_number": 1})
    assert plan == recovered


def test_recover_or_fallback_uses_minimal_plan_for_invalid_recovery():
    q = {"people_number": 3, "start_city": "X", "target_city": "Y"}
    plan = R._recover_or_fallback(_FakeAgent({"not": "a plan"}), q)
    assert plan == {"people_number": 3, "start_city": "X", "target_city": "Y", "itinerary": []}


def test_split_into_chunks_covers_all_and_bounds_size():
    uids = [f"uid{i:03d}" for i in range(23)]
    chunks = R._split_into_chunks(uids, 5)
    assert [u for c in chunks for u in c] == uids
    assert all(0 < len(c) <= 5 for c in chunks)
    assert len(chunks) == 5  # 5+5+5+5+3


def test_split_into_chunks_nonpositive_size_is_one_chunk():
    uids = [f"uid{i:03d}" for i in range(7)]
    assert R._split_into_chunks(uids, 0) == [uids]
    assert R._split_into_chunks(uids, -1) == [uids]


def test_split_into_chunks_empty_input():
    assert R._split_into_chunks([], 5) == []


def test_write_uids_file_roundtrips(tmp_path):
    uids = ["a", "b", "c"]
    path = R._write_uids_file(uids)
    try:
        assert path.read_text(encoding="utf-8").splitlines() == uids
    finally:
        path.unlink(missing_ok=True)


def test_split_set_for_maps_split_name_back_to_cli_choice():
    assert R._split_set_for("tpc_phase2_val") == "val"
    assert R._split_set_for("tpc_phase2_test") == "test"


# --- Parallel chunk dispatch (P2_PARALLEL) -----------------------------------


def test_run_chunks_sequential_when_parallel_is_1(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, uids_file):
        calls.append(cmd)

    monkeypatch.setattr(R, "_run_chunk_subprocess", fake_run)
    chunks = [["a", "b"], ["c", "d"], ["e"]]
    R._run_chunks(chunks, lambda uf: [f"cmd-for-{uf.name}"], parallel=1)
    assert len(calls) == 3


def test_run_chunks_parallel_le_1_is_default_and_preserves_behavior(monkeypatch):
    """parallel defaults to 1 (DEFAULT_PARALLEL, unless P2_PARALLEL is set) -- must not change
    dispatch behavior for anyone not opting in."""
    assert R.DEFAULT_PARALLEL == 1


def test_run_chunks_parallel_actually_overlaps_in_time(monkeypatch):
    """The whole point of --parallel: N chunk subprocesses run concurrently, not back-to-back.
    Each fake job sleeps 0.2s; with parallel=3 all three should finish in ~0.2s, not ~0.6s."""
    import time

    def fake_run(cmd, uids_file):
        time.sleep(0.2)

    monkeypatch.setattr(R, "_run_chunk_subprocess", fake_run)
    chunks = [["a"], ["b"], ["c"]]
    t0 = time.time()
    R._run_chunks(chunks, lambda uf: ["cmd"], parallel=3)
    elapsed = time.time() - t0
    assert elapsed < 0.45, f"expected concurrent dispatch (~0.2s), took {elapsed:.2f}s"


def test_run_chunks_parallel_runs_every_chunk_exactly_once(monkeypatch):
    calls = []

    def fake_run(cmd, uids_file):
        calls.append(cmd[0])

    monkeypatch.setattr(R, "_run_chunk_subprocess", fake_run)
    chunks = [["a"], ["b"], ["c"], ["d"], ["e"]]
    R._run_chunks(chunks, lambda uf: [f"cmd-{id(uf)}"], parallel=3)
    assert len(calls) == 5
    assert len(set(calls)) == 5  # each chunk's distinct uids_file-derived cmd appears once


def test_run_chunks_parallel_propagates_subprocess_failure(monkeypatch):
    def failing_run(cmd, uids_file):
        raise RuntimeError("boom")

    monkeypatch.setattr(R, "_run_chunk_subprocess", failing_run)
    with pytest.raises(RuntimeError, match="boom"):
        R._run_chunks([["a"], ["b"]], lambda uf: ["cmd"], parallel=2)


def test_run_end_to_end_chunked_passes_parallel_through(monkeypatch):
    captured = {}

    def fake_run_chunks(chunks, build_cmd, *, parallel):
        captured["chunks"] = chunks
        captured["parallel"] = parallel

    monkeypatch.setattr(R, "_run_chunks", fake_run_chunks)
    R._run_end_to_end_chunked(
        "tpc_phase2_val", ["a", "b", "c"], budget_sec=10.0, lang="en", chunk_size=2, parallel=3,
    )
    assert captured["parallel"] == 3


def test_run_solver_only_chunked_passes_parallel_through(monkeypatch):
    captured = {}

    def fake_run_chunks(chunks, build_cmd, *, parallel):
        captured["parallel"] = parallel

    monkeypatch.setattr(R, "_run_chunks", fake_run_chunks)
    R._run_solver_only_chunked(
        "tpc_phase2_val", ["a", "b", "c"], budget_sec=10.0, lang="en", chunk_size=2, parallel=3,
    )
    assert captured["parallel"] == 3


def test_run_end_to_end_chunked_defaults_parallel_to_1(monkeypatch):
    captured = {}

    def fake_run_chunks(chunks, build_cmd, *, parallel):
        captured["parallel"] = parallel

    monkeypatch.setattr(R, "_run_chunks", fake_run_chunks)
    R._run_end_to_end_chunked("tpc_phase2_val", ["a"], budget_sec=10.0, lang="en", chunk_size=2)
    assert captured["parallel"] == 1
