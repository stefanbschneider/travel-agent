#!/usr/bin/env python3
"""Phase 2 quick A/B screen for an off-by-default flag.

Methodology, cadence, and worked example: docs/tpc_phase2_eval.md ("Quick A/B screen (pre-gate
triage)").

Purpose: decide *within an hour or two, on a short-lived box* whether a landed-but-ungated
Phase 2 improvement helps enough to flip its default on -- without waiting for the 8h+ pinned
end-to-end baseline that runs on the eval machine. This is a **screen**, not the promotion gate:
it runs a paired baseline (flag off) vs candidate (flag on) on the *same* deterministic subset,
budget, and seed, and reports the delta. Only the sign/magnitude of the delta is trusted, because
the reduced budget/subset make the absolute numbers non-comparable to a full pinned row. A positive
screen is a green light to spend the eval machine's pinned gate on the change; it never promotes a
change by itself (see the measurement rules in docs/tpc_phase2_eval.md).

Why a paired same-budget A/B is meaningful at a reduced budget: the deterministic solver flags act
at the *acceptance* boundary inside ``_pack_plan`` (before the acceptance gate), so their effect on
FPR shows up even when the restart loop is cut short -- as long as baseline and candidate share the
exact budget/subset/seed, the *difference* isolates the flag. Holding everything but the flag fixed
is the whole point; the run is a controlled experiment, not a baseline row.

Default mode is ``solver-only`` (oracle constraints, no LLM, fully deterministic and reproducible on
this box), which is what the highest-leverage recent flags target. ``end-to-end`` is also supported;
with the Phase 2 LLM backend left at ``none`` it too makes zero LLM calls, so the deterministic
solver flags can be screened end-to-end here with no API key.

Examples:
    # Screen the timed-window pinning flag, solver-only, 40 queries at a 60s budget, 3 in parallel:
    .venv/bin/python scripts/phase2_quick_eval.py --flag TPC_PIN_TIMED_WINDOWS \
        --n 40 --budget-sec 60 --parallel 3

    # Screen the early-convergence stop at patience 40 (watch timeout rate, not FPR):
    .venv/bin/python scripts/phase2_quick_eval.py --flag TPC_SOLVE_CONVERGE_PATIENCE \
        --on 40 --n 40 --budget-sec 120 --parallel 3

    # Screen two flags stacked on top of each other:
    .venv/bin/python scripts/phase2_quick_eval.py --flag TPC_REPAIR_TRANSPORT_GAPS \
        --extra-env TPC_PIN_TIMED_WINDOWS=1 --n 40 --budget-sec 60 --parallel 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# Put scripts/ (this file's own dir) on the path so sibling modules import under a single, stable
# name (``phase2_gate``, not ``scripts.phase2_gate``) -- matching the tests and every other caller,
# so the same file is never loaded twice under two module names.
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "agent_env" / "scripts"))
CHINATRAVEL_ROOT = str(PROJECT_ROOT / "chinatravel")
if CHINATRAVEL_ROOT not in sys.path:
    sys.path.insert(0, CHINATRAVEL_ROOT)

import make_phase2_splits as splits  # noqa: E402
import rehearse_phase2 as reh  # noqa: E402
from phase2_gate import check_gate  # noqa: E402


def _method_for(mode: str, split_name: str) -> str:
    return f"phase2_{'solver_only' if mode == 'solver-only' else 'e2e'}_{split_name}"


def _aggregate_telemetry(mode: str, split_name: str, uids: list[str]) -> dict:
    """Read per-uid telemetry written by the run and summarize the reliability signals.

    Both the solver-only worker (rehearse_phase2._run_solver_only) and the end-to-end runner
    (solve_phase2) write ``agent_env/runs/<method>/<uid>/telemetry.json`` with the same core keys.
    """
    method = _method_for(mode, split_name)
    run_dir = PROJECT_ROOT / "agent_env" / "runs" / method
    n = 0
    timed_out = 0
    recovered = 0
    used_fallback = 0
    errored = 0
    valid = 0
    # LLM-activity counters (end-to-end mode only; stay 0 for solver-only / deterministic runs).
    llm_parse_fired = 0
    llm_parse_skipped = 0
    llm_parse_errored = 0
    refine_called = 0
    refine_committed = 0
    solve_secs: list[float] = []
    for uid in uids:
        tpath = run_dir / uid / "telemetry.json"
        if not tpath.exists():
            continue
        try:
            t = json.loads(tpath.read_text(encoding="utf-8"))
        except Exception:
            continue
        n += 1
        timed_out += int(bool(t.get("timed_out")))
        # solver-only worker uses recovered_from_*; the e2e orchestrator uses solve_recovered_from_*.
        recovered += int(any(bool(t.get(k)) for k in (
            "recovered_from_timeout", "recovered_from_error",
            "solve_recovered_from_timeout", "solve_recovered_from_error")))
        used_fallback += int(bool(t.get("used_fallback")))
        errored += int(bool(t.get("error")))
        valid += int(bool(t.get("valid_output")))
        # An LLM flag that never fired makes its screen meaningless, so surface it: parse audit ran
        # iff the flag was on and it was neither deadline-skipped nor errored; refine ran iff
        # improve_llm_called. improve_committed counts repairs that actually landed.
        if t.get("flags", {}).get("llm_parse"):
            if t.get("llm_parse_skipped_deadline"):
                llm_parse_skipped += 1
            elif t.get("llm_parse_error"):
                llm_parse_errored += 1
            else:
                llm_parse_fired += 1
        refine_called += int(bool(t.get("improve_llm_called")))
        refine_committed += int(bool(t.get("improve_committed")))
        stage = t.get("stage_sec") or {}
        if "solve" in stage:
            solve_secs.append(float(stage["solve"]))
    solve_secs.sort()

    def _pct(p: float) -> float:
        if not solve_secs:
            return 0.0
        idx = min(len(solve_secs) - 1, int(round(p * (len(solve_secs) - 1))))
        return solve_secs[idx]

    return {
        "n_telemetry": n,
        "timeouts": timed_out,
        "recovered": recovered,
        "used_fallback": used_fallback,
        "errored": errored,
        "valid_output": valid,
        "llm_parse_fired": llm_parse_fired,
        "llm_parse_skipped": llm_parse_skipped,
        "llm_parse_errored": llm_parse_errored,
        "refine_called": refine_called,
        "refine_committed": refine_committed,
        "solve_sec_mean": (sum(solve_secs) / len(solve_secs)) if solve_secs else 0.0,
        "solve_sec_p50": _pct(0.5),
        "solve_sec_p90": _pct(0.9),
    }


def _run_condition(*, label, env_overrides, mode, split_name, fold_uids,
                   budget_sec, parallel, chunk_size, fold, folds, seed) -> dict:
    """Run one arm of the A/B with ``env_overrides`` applied, return a metrics dict."""
    prev = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update({k: str(v) for k, v in env_overrides.items()})
    t0 = time.perf_counter()
    try:
        report = reh.rehearse(
            modes=(mode,),
            split_set=reh._split_set_for(split_name),
            fold=fold,
            folds=folds,
            seed=seed,
            budget_sec=budget_sec,
            limit=len(fold_uids),
            fresh=True,
            chunk_size=chunk_size,
            parallel=parallel,
        )
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    wall = time.perf_counter() - t0

    m = report["modes"][mode]
    quality = m.get("quality", {})
    overall_true = (quality.get("overall_true") or {}).get("mean", 0.0)
    telem = _aggregate_telemetry(mode, split_name, fold_uids)
    # A uid that produced no result file (`missing`), unreadable JSON, a failed eval, or a solve
    # error is a failure that must count -- otherwise a run where some uids produced no artifact
    # looks greener than it is (the gate blocks on any increase). `missing`/`invalid_json`/
    # `eval_failed` are disjoint per-uid quality buckets; telemetry `errored` may overlap a missing
    # uid, but over-counting failures only makes the gate stricter (the safe direction).
    parse_failures = int(quality.get("missing", 0)) + int(quality.get("invalid_json", 0)) \
        + int(quality.get("eval_failed", 0)) + int(telem.get("errored", 0))
    # Missing telemetry files undercount timeouts/solve stats, so surface coverage explicitly.
    requested = len(fold_uids)
    telemetry_coverage = f"{int(telem.get('n_telemetry', 0))}/{requested}"
    return {
        "label": label,
        "env_overrides": env_overrides,
        "wall_sec": round(wall, 1),
        # gate-shaped keys:
        "fpr": round(float(m.get("fpr", 0.0)), 2),
        "continuous_score": round(float(overall_true), 3),
        "parse_failures": parse_failures,
        "timeouts": int(telem.get("timeouts", 0)),
        "telemetry_coverage": telemetry_coverage,
        # richer screen signals:
        "telemetry": telem,
        "quality_n": {k: quality.get(k) for k in ("requested", "evaluated", "missing")},
    }


def decide_verdict(baseline: dict, candidate: dict, gate: dict, flag: str, *, tol: float = 0.5) -> str:
    """Reconcile the target-signal delta with the strict monotonic gate into one screen verdict.

    Pure function of the two metric dicts, the gate result, and the flag name, so it is unit-tested
    without running a solve. The categories are documented in docs/tpc_phase2_eval.md
    (GREEN LIGHT / GREEN LIGHT with caveat / MIXED / RED / NO BENEFIT / NEUTRAL).

    ``tol`` is a preference-score noise band: an ``overall_true`` move within +-tol counts as flat,
    not a regression or an improvement. Screens run at a reduced budget with a wall-clock-bounded
    restart loop, so a sub-point ``continuous_score`` wobble is run-to-run noise, not signal -- e.g.
    a repair pass that commits nothing still shifts overall_true by a few hundredths through solve
    timing alone, and that must not read as RED.
    """
    d_fpr = candidate["fpr"] - baseline["fpr"]
    d_cs = candidate["continuous_score"] - baseline["continuous_score"]
    d_to = candidate["timeouts"] - baseline["timeouts"]
    d_pf = candidate["parse_failures"] - baseline["parse_failures"]
    # A quality regression (fewer accepted plans / lower preference beyond noise / new parse
    # failures) is a hard RED regardless of the timeout picture -- those are correctness signals.
    quality_regression = d_fpr < -1e-9 or d_cs < -tol or d_pf > 0
    # For the two acceptance-flipping flags the target is FPR/overall_true; for the convergence
    # stop the target is the timeout/wall-clock rate at held FPR. overall_true only counts as
    # "improved" when it clears the noise band.
    target_improved = (
        d_fpr > 1e-9 or (abs(d_fpr) < 1e-9 and d_cs > tol)
        or (flag == "TPC_SOLVE_CONVERGE_PATIENCE" and d_to < 0 and d_fpr >= -1e-9 and d_cs >= -tol)
    )
    only_timeout_blocks = (not gate["passed"]) and bool(gate["reasons"]) and all(
        "timeout" in r for r in gate["reasons"]
    )

    if quality_regression:
        return ("RED: candidate regresses a correctness signal on this screen (FPR / "
                "overall_true / parse_failures) -> do NOT default on; investigate first.")
    if target_improved and gate["passed"]:
        return ("GREEN LIGHT: candidate improves its target signal and passes the like-for-like "
                "gate on this screen -> worth a pinned end-to-end gate on the eval machine.")
    if target_improved and only_timeout_blocks:
        return ("GREEN LIGHT (with caveat): candidate improves its target signal, but does more "
                f"work per solve (+{d_to} timeouts at this tight budget, all recovered). The "
                "pinned end-to-end gate at full budget must confirm the wall-clock cost is "
                "acceptable; the acceptance/preference gain is real.")
    if target_improved:
        return ("MIXED: target signal improves but the gate blocks on a non-timeout metric -> "
                "read the blocks above before spending a pinned gate.")
    # Not improved and not a regression: quality is flat within noise. Separate "flat but costs
    # wall-clock" (a real thumbs-down: the flag buys nothing and adds work) from a true no-op.
    if d_to > 0 or not gate["passed"]:
        return ("NO BENEFIT: quality is flat within noise but the candidate adds wall-clock cost "
                f"(+{d_to} timeouts) and flips nothing -> not worth defaulting as-is; use the "
                "per-query telemetry (e.g. refine committed/called, or parse fired) to see why.")
    return ("NEUTRAL: no measurable delta on this screen -> enlarge n/budget or pick a "
            "subset that exercises the flag before deciding.")


def _fmt_delta(base: float, cand: float, *, higher_better: bool = True) -> str:
    d = cand - base
    arrow = "→"
    tag = ""
    if abs(d) > 1e-9:
        good = (d > 0) == higher_better
        tag = "  (better)" if good else "  (WORSE)"
    return f"{base:>8.2f} {arrow} {cand:>8.2f}   Δ={d:+.2f}{tag}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--flag", required=True,
                   help="Env-var flag to A/B (e.g. TPC_PIN_TIMED_WINDOWS).")
    p.add_argument("--on", default="1", help="Candidate value for --flag (default '1').")
    p.add_argument("--off", default="0", help="Baseline value for --flag (default '0').")
    p.add_argument("--extra-env", default="",
                   help="Comma-separated K=V applied to BOTH arms (stack other flags/settings).")
    p.add_argument("--mode", choices=["solver-only", "end-to-end"], default="solver-only")
    p.add_argument(
        "--split-set",
        choices=["val", "test", "familiar_100", "familiar_100_val", "familiar_100_test"],
        default="familiar_100_val",
        help="Development screens default to the familiar-100 VAL split (80 records); the "
        "familiar_100_test split (20) is a held-out overfitting tripwire, not a per-change signal.",
    )
    p.add_argument("--n", type=int, default=40, help="Queries to screen (subset size).")
    p.add_argument("--budget-sec", type=float, default=60.0)
    p.add_argument("--parallel", type=int, default=3)
    p.add_argument("--chunk-size", type=int, default=1)
    p.add_argument("--folds", type=int, default=1, help="Fold partition count (1 = whole split).")
    p.add_argument("--fold", type=int, default=0)
    p.add_argument("--seed", type=int, default=reh.DEFAULT_SEED)
    p.add_argument("--tol", type=float, default=0.5,
                   help="overall_true (continuous_score) noise band: a move within +-tol is treated "
                   "as flat by both the gate and the verdict (default 0.5). Screens run at a reduced "
                   "budget where a sub-point preference wobble is run-to-run noise, not signal.")
    p.add_argument("--out", default=None, help="Directory to write baseline/candidate/summary JSON.")
    p.add_argument("--baseline-json", default=None,
                   help="Reuse a previously written baseline.json instead of rerunning the OFF arm. "
                   "Valid only when that baseline used the SAME mode/split/subset/budget/seed and "
                   "an all-flags-off configuration -- lets you screen several flags against one "
                   "shared baseline. YOU are responsible for that match; the tool trusts it.")
    args = p.parse_args()

    split_name, _is_test = reh.resolve_split_set(args.split_set)
    uids = splits.read_split(split_name)
    fold_uids = reh.select_fold(uids, fold=args.fold, folds=args.folds, seed=args.seed)[: args.n]

    extra = {}
    for pair in filter(None, (s.strip() for s in args.extra_env.split(","))):
        k, _, v = pair.partition("=")
        extra[k.strip()] = v.strip()

    print(f"# phase2 quick A/B screen: {args.flag} ({args.off} -> {args.on})")
    print(f"  mode={args.mode} split={split_name} n={len(fold_uids)} budget={args.budget_sec}s "
          f"parallel={args.parallel} seed={args.seed}")
    if extra:
        print(f"  shared extra-env (both arms): {extra}")
    print(f"  NOTE: reduced-budget SCREEN, not a promotion gate. Trust the delta's sign, not the "
          f"absolute numbers.\n")

    base_env = {args.flag: args.off, **extra}
    cand_env = {args.flag: args.on, **extra}

    common = dict(mode=args.mode, split_name=split_name, fold_uids=fold_uids,
                  budget_sec=args.budget_sec, parallel=args.parallel, chunk_size=args.chunk_size,
                  fold=args.fold, folds=args.folds, seed=args.seed)

    if args.baseline_json:
        baseline = json.loads(Path(args.baseline_json).read_text(encoding="utf-8"))
        print(f"[1/2] baseline  (reused {args.baseline_json})  FPR={baseline['fpr']} "
              f"overall_true={baseline['continuous_score']}\n", flush=True)
    else:
        print(f"[1/2] baseline  ({args.flag}={args.off}) ...", flush=True)
        baseline = _run_condition(label=f"{args.flag}={args.off}", env_overrides=base_env, **common)
        print(f"      done in {baseline['wall_sec']}s  FPR={baseline['fpr']} "
              f"overall_true={baseline['continuous_score']}\n", flush=True)

    print(f"[2/2] candidate ({args.flag}={args.on}) ...", flush=True)
    candidate = _run_condition(label=f"{args.flag}={args.on}", env_overrides=cand_env, **common)
    print(f"      done in {candidate['wall_sec']}s  FPR={candidate['fpr']} "
          f"overall_true={candidate['continuous_score']}\n", flush=True)

    gate = check_gate(baseline, candidate, tol=args.tol)

    print("=" * 72)
    print(f"RESULT  {args.flag}: {args.off} -> {args.on}   (n={len(fold_uids)}, "
          f"budget={args.budget_sec}s, {args.mode})")
    print("-" * 72)
    print(f"  FPR (pass %)          {_fmt_delta(baseline['fpr'], candidate['fpr'])}")
    print(f"  overall_true (pref)   {_fmt_delta(baseline['continuous_score'], candidate['continuous_score'])}")
    print(f"  timeouts (count)      {_fmt_delta(baseline['timeouts'], candidate['timeouts'], higher_better=False)}")
    bt, ct = baseline["telemetry"], candidate["telemetry"]
    print(f"  solve p50 (sec)       {_fmt_delta(bt['solve_sec_p50'], ct['solve_sec_p50'], higher_better=False)}")
    print(f"  used_fallback         {_fmt_delta(bt['used_fallback'], ct['used_fallback'], higher_better=False)}")
    print(f"  parse_failures        {_fmt_delta(baseline['parse_failures'], candidate['parse_failures'], higher_better=False)}")
    # Warn when either arm produced fewer telemetry files than uids -- timeouts/solve stats then
    # undercount, so the deltas above are not fully trustworthy for this run.
    for arm in (baseline, candidate):
        cov = arm.get("telemetry_coverage", "")
        got, _, want = cov.partition("/")
        if got and want and got != want:
            print(f"  WARNING: {arm['label']} telemetry coverage {cov} -- "
                  f"timeouts/solve stats undercount; enlarge budget or investigate the gap.")
    # LLM-activity line: only meaningful in end-to-end mode with an LLM flag. Proves the candidate
    # arm actually reached the model (a green screen where the LLM never fired is meaningless) and,
    # for refine, how many proposed repairs actually committed.
    if any(ct.get(k) for k in ("llm_parse_fired", "llm_parse_skipped", "llm_parse_errored",
                               "refine_called", "refine_committed")):
        bits = []
        if ct.get("llm_parse_fired") or ct.get("llm_parse_skipped") or ct.get("llm_parse_errored"):
            bits.append(f"llm_parse fired {ct['llm_parse_fired']}/"
                        f"skipped {ct['llm_parse_skipped']}/errored {ct['llm_parse_errored']}")
        if ct.get("refine_called") or ct.get("refine_committed"):
            bits.append(f"refine called {ct['refine_called']}/committed {ct['refine_committed']}")
        print(f"  LLM activity (cand)   {'; '.join(bits)}")
    print("-" * 72)
    print(f"  monotonic gate (like-for-like at this budget): "
          f"{'PASS' if gate['passed'] else 'FAIL'}")
    for r in gate["reasons"]:
        print(f"    - blocks: {r}")
    for a in gate["advisories"]:
        print(f"    - note:   {a}")
    print("-" * 72)

    verdict = decide_verdict(baseline, candidate, gate, args.flag, tol=args.tol)
    print(f"  VERDICT: {verdict}")
    print("=" * 72)

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
        (out / "candidate.json").write_text(json.dumps(candidate, indent=2), encoding="utf-8")
        summary = {
            "flag": args.flag, "off": args.off, "on": args.on, "extra_env": extra,
            "mode": args.mode, "split": split_name, "n": len(fold_uids),
            "budget_sec": args.budget_sec, "seed": args.seed,
            "baseline": baseline, "candidate": candidate, "gate": gate, "verdict": verdict,
        }
        (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nwrote {out}/summary.json (+ baseline.json, candidate.json)")


if __name__ == "__main__":
    main()
