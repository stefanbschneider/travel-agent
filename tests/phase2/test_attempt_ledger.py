"""Roadmap P2: the per-attempt telemetry ledger.

``agent_env/scripts/solve_phase2.py``'s ``run_sweeps_split`` used to write
``work_root/<uid>/telemetry.json`` on *every* attempt, so a later pass's write silently destroyed
the previous pass's record -- reading it after a completed run measures only the winners
(roadmap diagnosis §3's sampling note). These tests defend the fix: ``telemetry.json`` still holds
only the latest attempt (existing tooling reads it), and every attempt is additionally appended,
one JSON line each, to ``work_root/<uid>/attempts.jsonl``.

Two things this item must *not* do, defended here by construction rather than by a negative test
in every case: it must not change which plan is written to ``results/<method>/<uid>.json`` (that
decision, ``improved``, is made by the caller before ``on_result`` runs) and it must not change
pass selection (``sweeps.run_sweeps``'s own scheduling is untouched; only the telemetry dict handed
to ``on_result`` gains two purely observational keys).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_ENV_SCRIPTS = PROJECT_ROOT / "agent_env" / "scripts"
for _p in (str(PROJECT_ROOT), str(AGENT_ENV_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from chinatravel.agent.phase2 import selfscore, sweeps  # noqa: E402


def _score(*, ok: bool, overall: float) -> selfscore.PlanScore:
    return selfscore.PlanScore(
        schema_ok=True,
        commonsense_ok=ok,
        logical_ok=ok,
        epr_micro=100.0,
        epr_macro=100.0 if ok else 0.0,
        clpr=100.0 if ok else 0.0,
        fpr=100.0 if ok else 0.0,
        dav=50.0 if ok else 0.0,
        att=50.0 if ok else 0.0,
        ddr=50.0 if ok else 0.0,
        overall=overall,
        logical_total=1,
        logical_satisfied=1 if ok else 0,
    )


# --- append_attempt_ledger / attempt_ledger_record ---------------------------------------------


def test_two_attempts_on_one_uid_append_two_lines_without_clobbering(tmp_path):
    import solve_phase2 as runner

    run_dir = tmp_path / "runs" / "u1"

    first = runner.attempt_ledger_record(
        pass_index=1,
        pass_kind="triage",
        seed_salt="0",
        budget_sec=30.0,
        wall_sec=2.5,
        telemetry={"search_telemetry": {
            "restarts_used": 0, "stop_reason": "accepted_stop",
            "candidates_evaluated": 1, "best_found_at_restart": 0,
        }},
        self_score={"overall": 40.0},
        kept=True,
    )
    second = runner.attempt_ledger_record(
        pass_index=2,
        pass_kind="repair",
        seed_salt="0",
        budget_sec=90.0,
        wall_sec=61.2,
        telemetry={"search_telemetry": {
            "restarts_used": 47, "stop_reason": "budget",
            "candidates_evaluated": 48, "best_found_at_restart": 12,
        }},
        self_score={"overall": 85.0},
        kept=True,
    )

    runner.append_attempt_ledger(run_dir, first)
    runner.append_attempt_ledger(run_dir, second)

    ledger_path = run_dir / runner.ATTEMPT_LEDGER_FILENAME
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, "the second append must not clobber the first line"

    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["pass_index"] == 1
    assert parsed[0]["pass_kind"] == "triage"
    assert parsed[0]["wall_sec"] == 2.5
    assert parsed[0]["restarts_used"] == 0
    assert parsed[0]["stop_reason"] == "accepted_stop"
    assert parsed[0]["self_score"] == {"overall": 40.0}
    assert parsed[0]["kept"] is True

    assert parsed[1]["pass_index"] == 2
    assert parsed[1]["pass_kind"] == "repair"
    assert parsed[1]["wall_sec"] == 61.2
    assert parsed[1]["restarts_used"] == 47
    assert parsed[1]["stop_reason"] == "budget"

    # read_attempt_ledger reproduces exactly what was written, oldest first.
    assert runner.read_attempt_ledger(run_dir) == parsed


def test_missing_ledger_reads_as_empty_list(tmp_path):
    import solve_phase2 as runner

    assert runner.read_attempt_ledger(tmp_path / "nope") == []


def test_a_query_never_solved_leaves_no_ledger_file(tmp_path):
    import solve_phase2 as runner

    run_dir = tmp_path / "runs" / "never-touched"
    assert not (run_dir / runner.ATTEMPT_LEDGER_FILENAME).exists()
    assert runner.read_attempt_ledger(run_dir) == []


# --- on_result wiring inside run_sweeps_split ---------------------------------------------------


def _one_uid_and_query():
    from chinatravel.data.load_datasets import load_query
    import argparse

    args = argparse.Namespace(splits="tpc_phase1", lang="en", oracle_translation=True)
    query_ids, query_data = load_query(args)
    uid = query_ids[0]
    query = query_data[uid]
    query.setdefault("uid", uid)
    return uid, query


def test_run_sweeps_split_appends_a_ledger_line_and_keeps_telemetry_as_latest(tmp_path, monkeypatch):
    """End-to-end through ``run_sweeps_split`` with a stubbed ``sweeps.run_sweeps`` that fires
    ``on_result`` twice for the same uid, mirroring two real attempts (triage then repair)."""
    import solve_phase2 as runner

    uid, query = _one_uid_and_query()

    def fake_run_sweeps(*, uids, queries, deadline, config, on_result, best=None,
                         variants=None, coverage_unknown=None, log=print):
        plan1 = {"itinerary": [{"day": 1, "activities": []}], "uid": uid, "marker": "attempt-1"}
        plan2 = {"itinerary": [{"day": 1, "activities": []}], "uid": uid, "marker": "attempt-2"}
        telemetry1 = {
            "pass_kind": "triage", "pass_index": 1, "seed_salt": "0", "budget_sec": 30.0,
            "wall_sec": 3.1, "search_telemetry": {"restarts_used": 0, "stop_reason": "accepted_stop"},
            "self_score": {"overall": 40.0},
        }
        telemetry2 = {
            "pass_kind": "repair", "pass_index": 2, "seed_salt": "0", "budget_sec": 90.0,
            "wall_sec": 55.0, "search_telemetry": {"restarts_used": 30, "stop_reason": "budget"},
            "self_score": {"overall": 88.0},
        }
        on_result(uid, plan1, _score(ok=False, overall=40.0), telemetry1, True)
        on_result(uid, plan2, _score(ok=True, overall=88.0), telemetry2, True)
        return {"passes": [], "final_pass_scores": {}}

    from chinatravel.agent.phase2 import sweeps as sweeps_mod

    monkeypatch.setattr(sweeps_mod, "run_sweeps", fake_run_sweeps)

    result_method_dir = tmp_path / "results" / "phase2_p2_test"
    work_root = tmp_path / "runs" / "phase2_p2_test"
    result_method_dir.mkdir(parents=True)
    work_root.mkdir(parents=True)

    runner.run_sweeps_split(
        split="tpc_phase1",
        method="phase2_p2_test",
        selected=[uid],
        query_data={uid: query},
        deadline=time.monotonic() + 60.0,
        run_start=time.monotonic(),
        budget_sec=30.0,
        total_budget_sec=60.0,
        lang="en",
        workers=1,
        resume=False,
        result_method_dir=result_method_dir,
        work_root=work_root,
    )

    run_dir = work_root / uid

    # telemetry.json holds only the latest attempt.
    telemetry_json = json.loads((run_dir / "telemetry.json").read_text(encoding="utf-8"))
    assert telemetry_json["pass_kind"] == "repair"
    assert telemetry_json["kept"] is True

    # attempts.jsonl holds both, in order, and neither clobbered the other.
    ledger = runner.read_attempt_ledger(run_dir)
    assert len(ledger) == 2
    assert ledger[0]["pass_kind"] == "triage"
    assert ledger[0]["wall_sec"] == 3.1
    assert ledger[1]["pass_kind"] == "repair"
    assert ledger[1]["wall_sec"] == 55.0

    # The result plan on disk is the last (and only) improving attempt's plan -- unaffected by
    # ledger bookkeeping.
    written_plan = json.loads((result_method_dir / f"{uid}.json").read_text(encoding="utf-8"))
    assert written_plan["marker"] == "attempt-2"


def test_a_non_improving_attempt_still_appends_to_the_ledger_but_writes_no_plan(tmp_path, monkeypatch):
    import solve_phase2 as runner

    uid, query = _one_uid_and_query()

    def fake_run_sweeps(*, uids, queries, deadline, config, on_result, best=None,
                         variants=None, coverage_unknown=None, log=print):
        good_plan = {"itinerary": [{"day": 1, "activities": []}], "uid": uid, "marker": "good"}
        worse_plan = {"itinerary": [{"day": 1, "activities": []}], "uid": uid, "marker": "worse"}
        on_result(uid, good_plan, _score(ok=True, overall=90.0),
                   {"pass_kind": "triage", "pass_index": 1}, True)
        on_result(uid, worse_plan, _score(ok=False, overall=5.0),
                   {"pass_kind": "repair", "pass_index": 2}, False)
        return {"passes": [], "final_pass_scores": {}}

    from chinatravel.agent.phase2 import sweeps as sweeps_mod

    monkeypatch.setattr(sweeps_mod, "run_sweeps", fake_run_sweeps)

    result_method_dir = tmp_path / "results" / "phase2_p2_noregress"
    work_root = tmp_path / "runs" / "phase2_p2_noregress"
    result_method_dir.mkdir(parents=True)
    work_root.mkdir(parents=True)

    runner.run_sweeps_split(
        split="tpc_phase1",
        method="phase2_p2_noregress",
        selected=[uid],
        query_data={uid: query},
        deadline=time.monotonic() + 60.0,
        run_start=time.monotonic(),
        budget_sec=30.0,
        total_budget_sec=60.0,
        lang="en",
        workers=1,
        resume=False,
        result_method_dir=result_method_dir,
        work_root=work_root,
    )

    run_dir = work_root / uid
    ledger = runner.read_attempt_ledger(run_dir)
    assert len(ledger) == 2
    assert ledger[0]["kept"] is True
    assert ledger[1]["kept"] is False

    # The written plan is still the improving one -- keep-best is untouched by the ledger.
    written_plan = json.loads((result_method_dir / f"{uid}.json").read_text(encoding="utf-8"))
    assert written_plan["marker"] == "good"


# --- sweeps.run_sweeps: wall_sec/pass_index/seed_salt reach on_result's telemetry --------------


def test_run_sweeps_adds_wall_sec_and_pass_index_to_telemetry(monkeypatch):
    """These two keys are pure additions to the dict already flowing through ``handle`` --
    added here rather than inside ``solve_one`` so a directly-tested ``solve_one`` result stays
    unchanged. Neither key is read by ``is_better``/keep-best or by pass selection."""
    queries = {"q1": {"uid": "q1", "start_city": "A", "target_city": "B", "people_number": 1}}

    def fake_solve_one(task):
        return {
            "uid": task["uid"],
            "plan": {"itinerary": [{"day": 1}], "uid": task["uid"]},
            "telemetry": {"uid": task["uid"], "pass_kind": task["kind"]},
            "score": _score(ok=True, overall=90.0).to_dict(),
            "wall_sec": 4.25,
        }

    monkeypatch.setattr(sweeps, "solve_one", fake_solve_one)
    seen_telemetry: list[dict] = []

    sweeps.run_sweeps(
        uids=list(queries),
        queries=queries,
        deadline=time.monotonic() + 600,
        config=sweeps.SweepConfig(workers=1),
        on_result=lambda uid, plan, score, tel, improved: seen_telemetry.append(dict(tel)),
        log=lambda _msg: None,
    )

    assert len(seen_telemetry) >= 1
    first = seen_telemetry[0]
    assert first["wall_sec"] == 4.25
    assert first["pass_index"] == 1
    assert first["seed_salt"] is not None


def test_run_sweeps_pass_selection_and_keep_best_unaffected_by_ledger_fields(monkeypatch):
    """Regression floor: the scheduler's own decisions (which pass runs, which plan is kept) must
    be byte-identical to the pre-P2 behaviour tested in ``test_sweeps.py``."""
    queries = {
        uid: {"uid": uid, "start_city": "A", "target_city": "B", "people_number": 1}
        for uid in ("q1", "q2", "q3")
    }
    calls = []

    def fake_solve_one(task):
        calls.append(dict(task))
        return {
            "uid": task["uid"],
            "plan": {"itinerary": [{"day": 1}], "uid": task["uid"]},
            "telemetry": {"uid": task["uid"]},
            "score": _score(ok=True, overall=90.0).to_dict(),
            "wall_sec": 0.0,
        }

    monkeypatch.setattr(sweeps, "solve_one", fake_solve_one)
    written = []
    summary = sweeps.run_sweeps(
        uids=list(queries),
        queries=queries,
        deadline=time.monotonic() + 600,
        config=sweeps.SweepConfig(workers=1),
        on_result=lambda uid, plan, score, tel, improved: (
            written.append((uid, score.overall)) if improved else None
        ),
        log=lambda _msg: None,
    )

    triage = [call for call in calls if call["kind"] == "triage"]
    assert sorted(call["uid"] for call in triage) == ["q1", "q2", "q3"]
    assert sorted(uid for uid, _ in written) == ["q1", "q2", "q3"]
    assert summary["constraints_ok"] == 3
