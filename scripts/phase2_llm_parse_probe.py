#!/usr/bin/env python3
"""Cheap LLM-parse impact probe (no solver runs).

Measures whether the corrective LLM parse (``TPC_P2_LLM_PARSE``) fixes Stage-1 behavioral
disagreements without breaking correct parses, using the oracle verifier over ``results/best``
plans as ground truth:

1. Scan the first ``--limit`` validation queries with the deterministic parser and split them
   into behavioral disagreements (parse errors that matter) and agreements.
2. Probe up to ``--max-probes`` disagreement uids with the LLM parse enabled (one LLM call each)
   and count how many flip to agreement ("fixed").
3. Probe the same number of agreeing uids as a safety control and count regressions ("broke").

This isolates Axis-1 parse quality: one LLM call per probed uid, no TPCAgent/CP-SAT time, so it
is safe to run often and cheap on a paid API. Full end-to-end effect still needs a rehearsal run.

Usage:
    .venv/bin/python scripts/phase2_llm_parse_probe.py --limit 60 --max-probes 8
    .venv/bin/python scripts/phase2_llm_parse_probe.py --uids <uid1> <uid2> ...
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "agent_env" / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

DEFAULT_MODEL = "Qwen/Qwen3.6-27B"


def _variants_for(query, flags, llm_client=None):
    from chinatravel.agent.phase2 import normalize

    ir = normalize.parse_to_ir(query, llm_client=llm_client, flags=flags)
    return normalize.ir_to_solver_variants(ir, query, flags=flags), ir


def _parsed_pass(variants, plan, target_city) -> bool:
    from chinatravel.agent.tpc_agent.parsed_verifier import evaluate_parsed_constraints

    try:
        return any(all(evaluate_parsed_constraints(v, plan, target_city)) for v in variants)
    except Exception:
        return False


def probe_uid(uid: str, query_data: dict, llm_client, det_flags, llm_flags) -> dict:
    import solve_script_with_harness as hb
    from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py

    full = query_data[uid]
    full.setdefault("uid", uid)
    visible = hb.visible_query(full)
    plan = hb.read_json(PROJECT_ROOT / "results" / "best" / f"{uid}.json")
    target_city = full.get("target_city", "")

    oracle_res = evaluate_constraints_py(full.get("hard_logic_py", []) or [], plan, verbose=False)
    oracle_pass = all(bool(r) for r in oracle_res)

    det_variants, det_ir = _variants_for(visible, det_flags)
    det_pass = _parsed_pass(det_variants, plan, target_city)

    row = {
        "uid": uid,
        "oracle_pass": oracle_pass,
        "det_pass": det_pass,
        "det_agree": det_pass == oracle_pass,
        "det_n_variants": len(det_variants),
    }
    try:
        llm_variants, llm_ir = _variants_for(visible, llm_flags, llm_client=llm_client)
        llm_pass = _parsed_pass(llm_variants, plan, target_city)
        row.update(
            llm_pass=llm_pass,
            llm_agree=llm_pass == oracle_pass,
            llm_changed_raw=llm_ir.raw != det_ir.raw,
            llm_n_variants=len(llm_variants),
            llm_error=None,
        )
    except Exception as exc:
        row.update(llm_pass=None, llm_agree=None, llm_changed_raw=None, llm_n_variants=0,
                   llm_error=str(exc))
    return row


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", default="tpc_phase2_val")
    p.add_argument("--limit", type=int, default=60,
                   help="How many split queries to scan for disagreements (deterministic, free).")
    p.add_argument("--max-probes", type=int, default=8,
                   help="LLM-call cap per group (disagreements and control each).")
    p.add_argument("--uids", nargs="*", default=None,
                   help="Probe exactly these uids instead of scanning.")
    p.add_argument("--backend", default="deepinfra")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--lang", default="en", choices=["en", "zh"])
    p.add_argument(
        "--llm-parse-mode", default="audit", choices=["audit", "extract"],
        help="Which LLM parse strategy to probe (plan-2 Step 6): 'audit' (default, today's "
        "corrective-audit stub) or 'extract' (LLM-first structured extraction).",
    )
    p.add_argument("--out", default=str(PROJECT_ROOT / "cache" / "phase2_llm_parse_probe.json"))
    args = p.parse_args()

    import solve_phase2 as runner
    from chinatravel.agent.phase2.llm_client import build_llm_client
    from chinatravel.agent.phase2.orchestrator import Flags

    query_ids, query_data = runner._load_queries(args.split, lang=args.lang)
    llm_client = build_llm_client({"backend": args.backend, "model": args.model})
    det_flags = Flags(disjunction=True)
    llm_flags = Flags(
        disjunction=True, llm_parse=True, llm_backend=args.backend,
        llm_parse_mode=args.llm_parse_mode,
    )

    if args.uids:
        probe_uids = list(args.uids)
        control_uids: list[str] = []
    else:
        # Deterministic scan (no LLM): reuse probe_uid pieces without the LLM branch.
        disagreements: list[str] = []
        agreements: list[str] = []
        import solve_script_with_harness as hb
        from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py

        for uid in query_ids[: args.limit]:
            full = query_data[uid]
            full.setdefault("uid", uid)
            plan_path = PROJECT_ROOT / "results" / "best" / f"{uid}.json"
            if not plan_path.exists():
                continue
            plan = hb.read_json(plan_path)
            visible = hb.visible_query(full)
            oracle_res = evaluate_constraints_py(full.get("hard_logic_py", []) or [], plan, verbose=False)
            oracle_pass = all(bool(r) for r in oracle_res)
            det_variants, _ = _variants_for(visible, det_flags)
            det_pass = _parsed_pass(det_variants, plan, full.get("target_city", ""))
            (disagreements if det_pass != oracle_pass else agreements).append(uid)

        probe_uids = disagreements[: args.max_probes]
        control_uids = agreements[: args.max_probes]
        print(f"scan: n={args.limit} disagreements={len(disagreements)} "
              f"probing {len(probe_uids)} + {len(control_uids)} control")

    rows = []
    for uid in probe_uids + control_uids:
        row = probe_uid(uid, query_data, llm_client, det_flags, llm_flags)
        row["group"] = "disagreement" if uid in probe_uids else "control"
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    fixed = sum(1 for r in rows if r["group"] == "disagreement" and not r["det_agree"] and r["llm_agree"])
    broke = sum(1 for r in rows if r["det_agree"] and r["llm_agree"] is False)
    n_dis = sum(1 for r in rows if r["group"] == "disagreement")
    n_ctl = len(rows) - n_dis
    print(f"\nSummary: disagreements={n_dis} fixed={fixed} | control={n_ctl} broke={broke}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows, "fixed": fixed, "broke": broke}, ensure_ascii=False, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
