"""Unit tests for scripts/run_query.py (single-query Phase 2 harness front-end).

Uses the injected ``fast_solve_fn`` fixture throughout, so these never build a real WorldEnv /
TPCAgent or touch the network -- only the resolve/report logic and the (deterministic,
solver-free) parsed-vs-oracle diagnostics are exercised.
"""

from __future__ import annotations

import json

import pytest

import run_query as rq


def test_uid_mode_reports_official_and_estimated_score(one_query, fast_solve_fn, tmp_path):
    uid = one_query["uid"]
    args = rq.parse_args(
        [
            "--uid", uid,
            "--budget-sec", "5",
            "--method", "phase2_query_test_uid",
            "--results-dir", str(tmp_path / "results"),
            "--work-dir", str(tmp_path / "runs"),
        ]
    )
    report = rq.run_query(args, solve_fn=fast_solve_fn)

    assert report["uid"] == uid
    assert report["has_oracle"] is True
    assert isinstance(report["estimated_score"], float)
    assert isinstance(report["official_score"], float)
    assert "parsing_vs_oracle" in report
    assert "parsing_vs_solving" in report
    assert json.loads(open(report["result_path"], encoding="utf-8").read())["itinerary"]

    # print_report must not raise on a fully-populated (oracle) report.
    rq.print_report(report)


def test_uid_not_found_exits_with_clear_message(tmp_path):
    args = rq.parse_args(["--uid", "does_not_exist_12345", "--budget-sec", "5"])
    with pytest.raises(SystemExit) as excinfo:
        rq.resolve_query(args)
    assert "does_not_exist_12345" in str(excinfo.value)


def test_query_file_without_oracle_is_estimated_only(fast_solve_fn, tmp_path):
    query_path = tmp_path / "custom_query.json"
    query_path.write_text(
        json.dumps(
            {
                "nature_language": "2 days in Hangzhou from Shanghai for 2 people.",
                "people_number": 2,
                "start_city": "Shanghai",
                "target_city": "Hangzhou",
                "days": 2,
            }
        ),
        encoding="utf-8",
    )
    args = rq.parse_args(
        [
            "--query-file", str(query_path),
            "--budget-sec", "5",
            "--method", "phase2_query_test_file",
            "--results-dir", str(tmp_path / "results"),
            "--work-dir", str(tmp_path / "runs"),
        ]
    )
    report = rq.run_query(args, solve_fn=fast_solve_fn)

    assert report["uid"] == "custom_query"  # derived from the file stem (no uid field)
    assert report["has_oracle"] is False
    assert isinstance(report["estimated_score"], float)
    assert report["official_score"] is None
    assert "parsing_vs_oracle" not in report

    rq.print_report(report)


def test_query_file_missing_required_field_errors(tmp_path):
    query_path = tmp_path / "bad_query.json"
    query_path.write_text(json.dumps({"nature_language": "no structured fields"}), encoding="utf-8")
    args = rq.parse_args(["--query-file", str(query_path), "--budget-sec", "5"])
    with pytest.raises(SystemExit):
        rq.resolve_query(args)


def test_query_text_requires_structured_fields():
    args = rq.parse_args(["--query-text", "some trip", "--budget-sec", "5"])
    with pytest.raises(SystemExit) as excinfo:
        rq.resolve_query(args)
    msg = str(excinfo.value)
    assert "--start-city" in msg and "--target-city" in msg and "--days" in msg


def test_evaluate_one_empty_hard_logic_py_is_still_a_vacuous_oracle(one_query):
    """Regression: hard_logic_py=[] must be treated as a present (vacuously-true) oracle, not as
    'no oracle'. Truthiness-based gating would silently coerce overall_true to None/0.0 for these
    queries in a real split run, understating the aggregate ceiling/solver-only/e2e means the
    baseline ledger tracks. See has_oracle in solve_script_with_harness.evaluate_one."""
    import solve_script_with_harness as hb

    query = dict(one_query)
    query["hard_logic_py"] = []
    plan = {
        "people_number": query.get("people_number", 1),
        "start_city": query.get("start_city", ""),
        "target_city": query.get("target_city", ""),
        "itinerary": [{"day": 1, "activities": []}],
    }
    evaluation = hb.evaluate_one("unit_test", query["uid"], query, plan)

    assert evaluation["has_oracle"] is True
    assert evaluation["overall_true"] is not None
    assert evaluation["logical_macro"] is not None  # vacuous pass, not skipped


def test_query_text_mode_builds_adhoc_query(fast_solve_fn, tmp_path):
    args = rq.parse_args(
        [
            "--query-text", "2 days in Chengdu from Beijing for 2 people.",
            "--start-city", "Beijing",
            "--target-city", "Chengdu",
            "--days", "2",
            "--query-uid", "test_adhoc_text",
            "--budget-sec", "5",
            "--method", "phase2_query_test_text",
            "--results-dir", str(tmp_path / "results"),
            "--work-dir", str(tmp_path / "runs"),
        ]
    )
    report = rq.run_query(args, solve_fn=fast_solve_fn)

    assert report["uid"] == "test_adhoc_text"
    assert report["has_oracle"] is False
    assert report["official_score"] is None
    assert isinstance(report["estimated_score"], float)
