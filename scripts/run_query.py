#!/usr/bin/env python3
"""Run a single query through the Phase 2 harness end to end.

Three query sources (mutually exclusive):

- ``--uid <uid>``: an existing query id, looked up in ``--split`` (default ``tpc_phase1``, the
  full local 1000-query set). Always has the oracle ``hard_logic_py``, so this always reports an
  official score plus a parsing-vs-solving breakdown.
- ``--query-file <path>``: a query JSON file with the same schema as
  ``chinatravel/data/en/**/*.json`` (``nature_language``, ``start_city``, ``target_city``,
  ``days``, optionally ``people_number`` and ``hard_logic_py``). If it includes ``hard_logic_py``,
  the official score and parsing-vs-solving breakdown are computed too; otherwise only the
  estimated (oracle-free) score is reported.
- ``--query-text "<...>"``: an ad hoc natural-language query with no backing file and no oracle.
  Requires ``--start-city``/``--target-city``/``--days`` explicitly. This matches the real Phase 2
  contract, not a workaround: only ``hard_logic``/``hard_logic_py``/``hard_logic_nl`` (the oracle
  verifier fields) are ever hidden from the agent (see ``docs/tpc_phase2_design.md``); trip
  metadata is always given as structured fields alongside the free text, never something the agent
  has to infer from prose. Estimated score only (no oracle).

In every mode this runs the real Phase 2 orchestrator (deterministic TPCAgent, LLM parse/refine
per the usual env/config flags) and writes the same artifacts a split run would:
``results/<method>/<uid>.json`` (the plan) and
``agent_env/runs/<method>/<uid>/{output,telemetry,evaluation}.json``.

Examples:
    python scripts/run_query.py --uid 20250322063246301376 --budget-sec 60
    python scripts/run_query.py --query-file my_query.json --budget-sec 120
    python scripts/run_query.py --query-text "3 days in Chengdu from Beijing for 2 people, \\
        visit a panda base" --start-city Beijing --target-city Chengdu --days 3
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
_AGENT_ENV_SCRIPTS = PROJECT_ROOT / "agent_env" / "scripts"
if str(_AGENT_ENV_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_AGENT_ENV_SCRIPTS))

import solve_phase2 as runner  # noqa: E402
import solve_script_with_harness as hb  # noqa: E402
import parser_vs_oracle as pvo  # noqa: E402

DEFAULT_METHOD = "phase2_query"
DEFAULT_BUDGET_SEC = 120.0
REQUIRED_QUERY_FIELDS = ("nature_language", "start_city", "target_city", "days")


def resolve_query(args: argparse.Namespace) -> tuple[str, dict[str, Any], str]:
    """Return ``(uid, query_dict, split_label)`` for whichever source was given."""
    if args.uid:
        query_ids, query_data = runner._load_queries(args.split, lang=args.lang)
        if args.uid not in query_data:
            raise SystemExit(
                f"uid {args.uid!r} not found in split {args.split!r} ({len(query_ids)} uids). "
                "Use --query-file for a query outside the local dataset."
            )
        query = dict(query_data[args.uid])
        query.setdefault("uid", args.uid)
        return args.uid, query, args.split

    if args.query_file:
        path = Path(args.query_file)
        query = dict(json.loads(path.read_text(encoding="utf-8")))
        uid = args.query_uid or query.get("uid") or path.stem
        query["uid"] = uid
        missing = [k for k in REQUIRED_QUERY_FIELDS if k not in query]
        if missing:
            raise SystemExit(f"--query-file {path} is missing required field(s): {missing}")
        query.setdefault("people_number", 1)
        return uid, query, "adhoc_file"

    # --query-text
    missing_flags = [
        flag
        for flag, val in (
            ("--start-city", args.start_city),
            ("--target-city", args.target_city),
            ("--days", args.days),
        )
        if not val
    ]
    if missing_flags:
        raise SystemExit(
            f"--query-text also requires {', '.join(missing_flags)}: real Phase 2 queries always "
            "carry these as structured fields alongside the free text (only the oracle "
            "hard_logic/hard_logic_py/hard_logic_nl fields are ever hidden -- see "
            "docs/tpc_phase2_design.md), so the solver expects them explicitly rather than "
            "inferring them from prose."
        )
    uid = args.query_uid or f"adhoc_{int(time.time())}"
    query = {
        "uid": uid,
        "nature_language": args.query_text,
        "start_city": args.start_city,
        "target_city": args.target_city,
        "days": args.days,
        "people_number": args.people_number,
    }
    return uid, query, "adhoc_text"


def run_query(args: argparse.Namespace, *, env=None, solve_fn=None) -> dict[str, Any]:
    uid, query, split_label = resolve_query(args)
    # Presence, not truthiness: hard_logic_py=[] is still a real (vacuously-true) oracle.
    has_oracle = "hard_logic_py" in query

    method = args.method or DEFAULT_METHOD
    summary = runner.run_split(
        split_label,
        method=method,
        uid=uid,
        queries={uid: query},
        resume=args.resume,
        budget_sec=args.budget_sec,
        lang=args.lang,
        work_dir=args.work_dir,
        results_dir=args.results_dir,
        env=env,
        solve_fn=solve_fn,
    )

    results_root = Path(args.results_dir) if args.results_dir else PROJECT_ROOT / "results"
    work_root = (
        Path(args.work_dir) if args.work_dir else PROJECT_ROOT / "agent_env" / "runs" / method
    )
    result_path = results_root / method / f"{uid}.json"
    eval_path = work_root / uid / "evaluation.json"
    telemetry_path = work_root / uid / "telemetry.json"
    evaluation = hb.read_json(eval_path)

    report: dict[str, Any] = {
        "uid": uid,
        "result_path": str(result_path),
        "evaluation_path": str(eval_path),
        "telemetry_path": str(telemetry_path),
        "has_oracle": has_oracle,
        "estimated_score": evaluation.get("overall_parsed"),
        "estimated_all_pass": evaluation.get("all_pass_parsed"),
        "official_score": evaluation.get("overall_true") if has_oracle else None,
        "official_all_pass": evaluation.get("all_pass") if has_oracle else None,
        "summary": summary,
    }

    if has_oracle:
        plan = hb.read_json(result_path)
        llm_client, flags = runner.resolve_llm_client_and_flags()
        diff = pvo.compute_query_diff(
            query, disjunction=flags.disjunction, llm_parse=flags.llm_parse, llm_client=llm_client,
            entity_resolution=flags.entity_resolution,
        )
        behavior = pvo.behavioral_check(
            query, plan, disjunction=flags.disjunction, llm_parse=flags.llm_parse,
            llm_client=llm_client, entity_resolution=flags.entity_resolution,
        )
        report["parsing_vs_oracle"] = {
            "precision": diff["precision"],
            "recall": diff["recall"],
            "f1": diff["f1"],
            "value_accuracy": diff["value_accuracy"],
            "matched": diff["matched"],
            "missing": diff["missing"],
            "spurious": diff["spurious"],
            "wrong_value": diff["wrong_value"],
        }
        report["parsing_vs_solving"] = {
            # Did the plan satisfy the constraints the solver was actually given (the parse)?
            "solving_pass": evaluation.get("all_pass_parsed"),
            # Does that same plan also satisfy the ground-truth oracle constraints?
            "parsing_pass": evaluation.get("all_pass"),
            "behavioral_agree": behavior["agree"],
        }

    return report


def print_report(report: dict[str, Any]) -> None:
    print("=" * 72)
    print(f"uid:            {report['uid']}")
    print(f"result:         {report['result_path']}")
    print(f"evaluation:     {report['evaluation_path']}")
    print(f"telemetry:      {report['telemetry_path']}")
    print("-" * 72)
    est = report["estimated_score"]
    print(
        f"estimated score (overall_parsed, oracle-free): {est:.4f} "
        f"(all_pass_parsed={report['estimated_all_pass']})"
    )
    if report["has_oracle"]:
        off = report["official_score"]
        print(
            f"official score  (overall_true):                {off:.4f} "
            f"(all_pass={report['official_all_pass']})"
        )
        pvs = report["parsing_vs_solving"]
        d = report["parsing_vs_oracle"]
        print("-" * 72)
        print("parsing vs solving (this query has an oracle, so the gap is attributable):")
        print(f"  solving : plan satisfies its OWN parsed constraints?      {pvs['solving_pass']}")
        print(f"  parsing : that plan also satisfies the ORACLE constraints? {pvs['parsing_pass']}")
        print(f"  behavioral agreement (parsed vs oracle verifier, same plan): {pvs['behavioral_agree']}")
        print(
            f"  structural diff vs oracle: precision={d['precision']} recall={d['recall']} "
            f"f1={d['f1']} value_accuracy={d['value_accuracy']} "
            f"(matched={d['matched']} missing={d['missing']} spurious={d['spurious']} "
            f"wrong_value={d['wrong_value']})"
        )
    else:
        print("no hard_logic_py oracle on this query -> official score / parsing-vs-solving diff "
              "not computed (estimated score only).")
    print("=" * 72)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--uid", default=None,
        help="Existing query uid, looked up in --split (default: tpc_phase1, the full local set).",
    )
    src.add_argument(
        "--query-file", default=None,
        help="Path to a query JSON file. Include hard_logic_py for an official score.",
    )
    src.add_argument(
        "--query-text", default=None,
        help="Ad hoc natural-language query text. Requires --start-city/--target-city/--days. "
        "No oracle -> estimated score only.",
    )

    p.add_argument(
        "--split", default="tpc_phase1",
        help="Split --uid is resolved against (default: tpc_phase1, the full local 1000-query set).",
    )
    p.add_argument("--lang", default="en", choices=["en", "zh"])
    p.add_argument("--budget-sec", type=float, default=DEFAULT_BUDGET_SEC)
    p.add_argument("--method", default=None, help=f"Result/work dir label (default: {DEFAULT_METHOD}).")
    p.add_argument("--results-dir", default=None)
    p.add_argument("--work-dir", default=None)
    p.add_argument(
        "--resume", action="store_true",
        help="Reuse an existing results/<method>/<uid>.json instead of re-solving.",
    )

    p.add_argument("--query-uid", default=None, help="Override the uid for --query-file/--query-text.")
    p.add_argument("--start-city", default=None)
    p.add_argument("--target-city", default=None)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--people-number", type=int, default=1)
    return p.parse_args(argv)


def main() -> None:
    args = parse_args()
    report = run_query(args)
    print_report(report)


if __name__ == "__main__":
    main()
