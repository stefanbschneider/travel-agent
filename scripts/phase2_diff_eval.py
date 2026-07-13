#!/usr/bin/env python3
"""Differential e2e evaluation (plan-2 Step 2): re-solve only the uids whose solver input
changed since a baseline ledger row, and splice the rest from that row's recorded outcomes.

A parser change alters the solver's input (the constraint variants fed to it) only for the uids
whose parse actually changed -- typically a handful per fix. The solver is deterministic given
its variants (temp-0 LLM + warm disk cache + pure regex), so re-solving the ~95% of uids whose
input is unchanged reproduces the baseline row byte-for-byte; this script skips that redundant
work and reports a projected FPR instead.

Usage:
    scripts/phase2_diff_eval.py --baseline docs/phase2_baselines/runs/<run_id>.json

Validity: this is only sound if the solver/orchestrator code is unchanged vs the baseline sha --
otherwise a "changed" uid's fresh solve wouldn't be comparable to an "unchanged" uid's spliced-in
baseline outcome. Refuses (see ``guard_parser_only_changes``) unless every file that differs from
the baseline sha is on the parse-only allowlist, or ``--unsafe-allow-solver-drift`` is passed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
AGENT_ENV_SCRIPTS = PROJECT_ROOT / "agent_env" / "scripts"
if str(AGENT_ENV_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(AGENT_ENV_SCRIPTS))

import parser_vs_oracle as parser_mod  # noqa: E402
import phase2_record_baseline as recorder_mod  # noqa: E402
import rehearse_phase2 as rehearse_mod  # noqa: E402
import solve_phase2 as runner_mod  # noqa: E402

# Only these modules' changes leave the solver/orchestrator path untouched -- everything else
# (solver, harness, evaluators, budgeting) invalidates the "unchanged uids reproduce byte-for-
# byte" assumption the splice relies on.
PARSE_ONLY_ALLOWLIST = {
    "parse_constraints.py",
    "chinatravel/agent/phase2/normalize.py",
    "chinatravel/agent/phase2/schema.py",
}


class UnsafeDiffEvalError(RuntimeError):
    """Raised when files outside PARSE_ONLY_ALLOWLIST changed since the baseline sha."""


def changed_files_since(sha: str, *, cwd: Path = PROJECT_ROOT) -> list[str]:
    out = subprocess.check_output(
        ["git", "diff", "--name-only", sha], cwd=cwd, text=True
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def guard_parser_only_changes(
    sha: str, *, unsafe: bool = False, cwd: Path = PROJECT_ROOT
) -> list[str]:
    """Return the changed-file list; raise UnsafeDiffEvalError if any file outside the
    parse-only allowlist changed (unless ``unsafe`` overrides the guard).

    Files under ``tests/`` are exempt from the allowlist check (though still returned in the
    changed-file list): pytest is never imported by the solve path, so a test-only change cannot
    affect solver/orchestrator behavior -- the property this guard actually protects.
    """
    changed = changed_files_since(sha, cwd=cwd)
    disallowed = [
        f for f in changed if f not in PARSE_ONLY_ALLOWLIST and not f.startswith("tests/")
    ]
    if disallowed and not unsafe:
        raise UnsafeDiffEvalError(
            f"non-parser file(s) changed since {sha}: {disallowed} -- a full run is required "
            "(the splice assumes solver/orchestrator code is unchanged). Pass "
            "--unsafe-allow-solver-drift to override for exploratory use only."
        )
    return changed


def compute_projection(
    *, uids: list[str], changed: set[str], baseline_pass_ids: set[str], new_pass_ids: set[str]
) -> dict[str, Any]:
    """Pure splice math: unchanged uids keep their baseline pass/fail; changed uids use the
    freshly measured outcome. Split out so it's testable on synthetic inputs without a solver."""
    unchanged = [u for u in uids if u not in changed]
    unchanged_passes = sum(1 for u in unchanged if u in baseline_pass_ids)
    changed_passes = sum(1 for u in changed if u in new_pass_ids)
    n = len(uids)
    projected_fpr = 100.0 * (unchanged_passes + changed_passes) / n if n else 0.0

    flips = []
    for uid in sorted(changed):
        was = uid in baseline_pass_ids
        now = uid in new_pass_ids
        if was != now:
            flips.append({"uid": uid, "baseline_pass": was, "new_pass": now})

    return {
        "n": n,
        "changed_n": len(changed),
        "unchanged_n": len(unchanged),
        "unchanged_passes": unchanged_passes,
        "changed_passes": changed_passes,
        "projected_fpr": projected_fpr,
        "flips": flips,
    }


def _family_context(query: dict, *, flags, llm_client) -> dict[str, Any]:
    """Per-uid family-diff context (current parse vs oracle) for a changed uid -- helps attribute
    *why* it flipped without needing the baseline's (unstored) old parse content."""
    try:
        row = parser_mod.compute_query_diff(
            query, disjunction=flags.disjunction, branch_aware=True,
            llm_parse=flags.llm_parse, llm_client=llm_client,
            entity_resolution=flags.entity_resolution,
        )
    except Exception as exc:  # never let context-gathering fail the whole report
        return {"error": str(exc)}
    return {k: row["buckets"][k] for k in ("missing", "spurious", "wrong_value")}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--baseline", required=True, help="Path to a docs/phase2_baselines/runs/<id>.json row.")
    p.add_argument(
        "--budget-sec", type=float, default=None,
        help="Budget for re-solved uids (default: the baseline row's own budget_sec, so spliced "
        "numbers are homogeneous).",
    )
    p.add_argument("--parallel", type=int, default=rehearse_mod.DEFAULT_PARALLEL)
    p.add_argument("--lang", default=None, help="Default: the baseline row's own lang.")
    p.add_argument(
        "--unsafe-allow-solver-drift", action="store_true",
        help="Skip the parse-only-allowlist guard. Exploratory use only -- the projected FPR is "
        "not trustworthy if solver/orchestrator code changed.",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    baseline_sha = baseline["git_sha"]
    fingerprints_baseline: dict[str, str] = baseline.get("fingerprints") or {}
    if not fingerprints_baseline:
        print(
            "error: baseline row has no 'fingerprints' field -- record it with a recorder build "
            "that supports plan-2 Step 2 fingerprinting.", file=sys.stderr,
        )
        return 2

    try:
        guard_parser_only_changes(baseline_sha, unsafe=args.unsafe_allow_solver_drift)
    except UnsafeDiffEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    split_name = baseline["split_name"]
    lang = args.lang or baseline.get("lang", "en")
    budget_sec = args.budget_sec if args.budget_sec is not None else float(baseline["budget_sec"])
    uids = sorted(fingerprints_baseline.keys())

    _, query_data = rehearse_mod.runner_load(split_name, lang)
    llm_client, flags = runner_mod.resolve_llm_client_and_flags()

    current_fingerprints = recorder_mod.compute_fingerprints(
        query_data, uids, flags=flags, llm_client=llm_client
    )
    changed = {u for u in uids if current_fingerprints.get(u) != fingerprints_baseline.get(u)}
    print(f"{len(changed)}/{len(uids)} uid(s) have a changed solver input: {sorted(changed)}")

    e2e_method = f"phase2_e2e_{split_name}"
    new_pass_ids: set[str] = set()
    if changed:
        removed = rehearse_mod.clear_method_outputs(e2e_method, sorted(changed))
        print(f"cleared {removed} stale result(s) for the changed uid(s)")
        rehearse_mod._run_end_to_end_chunked(
            split_name, sorted(changed), budget_sec=budget_sec, lang=lang,
            chunk_size=rehearse_mod.DEFAULT_CHUNK, parallel=args.parallel,
        )
        import solve_script_with_harness as hb

        new_metrics = hb.evaluate_split(split_name, e2e_method, sorted(changed), query_data)
        new_pass_ids = set(new_metrics.get("all_pass_ids", []))

    baseline_pass_ids = set(
        baseline.get("rehearsal", {}).get("modes", {}).get("end-to-end", {})
        .get("raw", {}).get("all_pass_ids", [])
    )

    projection = compute_projection(
        uids=uids, changed=changed, baseline_pass_ids=baseline_pass_ids, new_pass_ids=new_pass_ids,
    )
    for flip in projection["flips"]:
        q = query_data[flip["uid"]]
        q.setdefault("uid", flip["uid"])
        flip["family_context"] = _family_context(q, flags=flags, llm_client=llm_client)

    report = {
        "baseline_run_id": baseline.get("run_id"),
        "baseline_sha": baseline_sha,
        "split_name": split_name,
        "budget_sec": budget_sec,
        "baseline_fpr": baseline.get("rehearsal", {}).get("modes", {}).get("end-to-end", {}).get("fpr"),
        **projection,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
