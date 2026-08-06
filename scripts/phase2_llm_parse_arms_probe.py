#!/usr/bin/env python3
"""Does an LLM recover the constraint-extraction gaps the regex parser has on unfamiliar phrasing?

Why this exists
---------------
The 2026-08-06 generalization probe
(``results/phase2_baselines/screens/20260806_generalization_probe/README.md``) measured that our
deterministic extractor has **zero** clause-level gaps on ``tpc_phase2_familiar_100`` -- the
numbered-template split it was built against -- and 12-29 % gaps on every differently-phrased
released set. The existing ``TPC_P2_LLM_PARSE`` screen was RED (-3.20 overall), but it was only ever
run on familiar-100, where the deterministic parser is already perfect: that screen could not
possibly have shown a gain, whatever the LLM did. This script re-measures the same stage where the
deterministic parser actually fails.

It is the generalization probe's own instrument with one extra arm. Per query it computes three
solver-dict parses -- oracle, deterministic no-oracle, LLM-assisted no-oracle -- and reports, per
set and per arm:

- family-level precision / recall / F1 against the oracle (``scripts.parser_vs_oracle``, unchanged);
- clause-level coverage and **parse-gap** counts, with the C-LPR and FPR ceilings they imply
  (``scripts.phase2_generalization_probe``, unchanged);
- per-family recovery: which of the deterministic parse gaps the LLM closed, and which families it
  newly broke.

Methodology this script enforces rather than assumes
----------------------------------------------------
**An arm whose model never fired is UNMEASURED, not a null result.** A previous parse screen read
+1.97 only because 10 of 30 audits silently timed out and fell back to the deterministic path -- the
LLM stage swallows every exception by contract (``normalize.parse_to_ir``), so a broken endpoint is
indistinguishable from a well-behaved no-op unless calls are counted at the wire. So:

- every LLM call is counted at the OpenAI SDK boundary, with prompt/completion tokens, latency and
  the exception class of every failure;
- ``--no-cache`` is available, and cache hits are counted separately from live calls, because the
  shipped client caches responses on disk (``CachingLLMClient``) and a warm cache yields zero live
  calls;
- the report carries ``reportable``/``verdict`` fields, and a query whose LLM call failed is listed
  by uid so a "the LLM did not help" reading can be checked against "the LLM was not asked";
- the deterministic arm is computed on the **same queries in the same process**, so the pairing is
  exact rather than approximate.

Cost. One call per query. Measure first, size later::

    TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
        --set hf_medium --limit 2 --mode extract --out-dir /tmp/cost_probe

Then the real run::

    TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_llm_parse_arms_probe.py \
        --set hf_medium --set familiar_100 --mode extract \
        --out-dir results/phase2_baselines/screens/20260806_llm_arms/exp1_extract

Measurement only: it changes no default, is never imported by the shipped harness, and the library
default backend stays ``none``.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: DeepInfra list price for Qwen3-family models, USD per 1M tokens (in / out). Same figures the
#: report-ablation script uses, so the two arms' dollar numbers are on one scale.
DEFAULT_PRICE_IN_PER_MTOK = 0.32
DEFAULT_PRICE_OUT_PER_MTOK = 3.20
DEFAULT_MODEL = "Qwen/Qwen3.6-27B"

#: Named query sets: label -> (kind, name). Same six the generalization probe measures.
SETS: dict[str, tuple[str, str]] = {
    "familiar_100": ("local", "tpc_phase2_familiar_100"),
    "local_released_150": ("local", "tpc_phase2_test"),
    "hf_easy": ("hf", "easy"),
    "hf_medium": ("hf", "medium"),
    "hf_human": ("hf", "human"),
    "hf_preference_base50": ("hf", "preference_base50"),
}


# --- Call counting at the wire -------------------------------------------


class CallCounter:
    """Counts what actually left the process, so a null result cannot be confused with a no-op."""

    def __init__(self) -> None:
        self.live_calls = 0
        self.cache_hits = 0
        self.failures = 0
        self.timeouts = 0
        self.retries = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.latencies: list[float] = []
        self.errors: Counter = Counter()
        self.failed_uids: list[str] = []
        self.empty_responses = 0

    def as_dict(self, *, price_in: float, price_out: float) -> dict[str, Any]:
        lat = sorted(self.latencies)
        cost = self.prompt_tokens / 1e6 * price_in + self.completion_tokens / 1e6 * price_out
        return {
            "llm_live_calls": self.live_calls,
            "llm_cache_hits": self.cache_hits,
            "llm_failures": self.failures,
            "llm_timeouts": self.timeouts,
            "llm_retries": self.retries,
            "llm_empty_responses": self.empty_responses,
            "llm_error_classes": dict(self.errors.most_common()),
            "llm_failed_uids": self.failed_uids[:40],
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "est_cost_usd": round(cost, 4),
            "llm_sec_total": round(sum(lat), 1),
            "llm_sec_p50": round(lat[len(lat) // 2], 2) if lat else 0.0,
            "llm_sec_max": round(lat[-1], 2) if lat else 0.0,
            "price_in_per_mtok": price_in,
            "price_out_per_mtok": price_out,
        }


def _is_timeout(exc: BaseException) -> bool:
    names = {type(exc).__name__, *(t.__name__ for t in type(exc).__mro__)}
    return any("Timeout" in n for n in names) or isinstance(exc, TimeoutError)


def instrument_client(client, counter: CallCounter, *, retries: int = 0,
                      backoff_sec: float = 2.0):
    """Wrap the OpenAI SDK ``chat.completions.create`` under ``client`` to count real traffic.

    Instrumenting at the SDK boundary rather than at ``LLMClient.complete`` is deliberate: it is the
    only place that distinguishes a live request from a ``CachingLLMClient`` hit, and the only place
    token usage exists (``OpenAILLMClient.complete`` discards ``completion.usage``).

    ``retries`` retries a *transient* provider error (429 rate limit, 5xx, timeout) with linear
    backoff. Not cosmetic: a run that shares an API key with a concurrent multi-worker arm gets
    rate-limited, and because the LLM parse stage swallows every exception by contract, a
    rate-limited query is silently scored as the deterministic parse. Without retries the arm
    measures our own throughput limit rather than the model. Every attempt, successful or not, is
    still counted, so the telemetry shows the retry traffic instead of hiding it.
    """
    inner = getattr(client, "inner", client)  # unwrap CachingLLMClient
    sdk = getattr(inner, "_client", None)
    if sdk is None:
        return client  # fixture / none backend: nothing to instrument
    original = sdk.chat.completions.create

    def counted(**kwargs):
        last_exc: BaseException | None = None
        for attempt in range(max(1, retries + 1)):
            started = time.perf_counter()
            try:
                completion = original(**kwargs)
            except BaseException as exc:
                counter.latencies.append(time.perf_counter() - started)
                if _is_timeout(exc):
                    counter.timeouts += 1
                else:
                    counter.failures += 1
                counter.errors[type(exc).__name__] += 1
                last_exc = exc
                if attempt < retries and _is_retryable(exc):
                    counter.retries += 1
                    time.sleep(backoff_sec * (attempt + 1))
                    continue
                raise
            counter.latencies.append(time.perf_counter() - started)
            counter.live_calls += 1
            usage = getattr(completion, "usage", None)
            counter.prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            counter.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
            return completion
        raise last_exc  # unreachable: the loop either returns or raises

    sdk.chat.completions.create = counted
    return client


def _is_retryable(exc: BaseException) -> bool:
    """Transient provider errors worth another attempt: rate limits, 5xx, timeouts."""
    name = type(exc).__name__
    return _is_timeout(exc) or name in {
        "RateLimitError", "InternalServerError", "APIConnectionError", "APIError",
        "ServiceUnavailableError",
    }


class CacheHitCountingClient:
    """Delegates to the real client and records whether each ``complete`` hit the disk cache."""

    def __init__(self, inner, counter: CallCounter):
        self._inner = inner
        self._counter = counter

    def complete(self, prompt: str, *, system: str | None = None, cache_key: str | None = None) -> str:
        before = self._counter.live_calls
        text = self._inner.complete(prompt, system=system, cache_key=cache_key)
        if self._counter.live_calls == before:
            self._counter.cache_hits += 1
        if not (text or "").strip():
            self._counter.empty_responses += 1
        return text


# --- Data ----------------------------------------------------------------


def load_set(label: str, *, limit: int | None = None, uids: list[str] | None = None):
    kind, name = SETS[label]
    if kind == "local":
        from chinatravel.data.load_datasets import load_query

        ids, data = load_query(
            argparse.Namespace(splits=name, lang="en", oracle_translation=True)
        )
    else:
        from parser_vs_oracle import load_hf_queries

        ids, data = load_hf_queries("default", [name])
    if uids:
        wanted = [u for u in uids if u in data]
        return wanted, data
    if limit:
        ids = ids[:limit]
    return list(ids), data


# --- Per-arm measurement -------------------------------------------------


def _arm_row(query: dict, *, llm_parse: bool, llm_client, mode: str | None = None,
             disjunction: bool = True, branch_aware: bool = True) -> tuple[dict, set, list[dict]]:
    """One arm's (diff row, parsed family set, oracle variants) for one query.

    Deliberately calls ``query_variants`` **once** and computes the diff from its output rather than
    calling ``compute_query_diff`` as well: the latter re-parses, which on the LLM arm would issue a
    second call per query (or a cache hit that hides a real doubling of cost).
    """
    from parser_vs_oracle import _f1, _families, diff_variants, query_variants

    parsed_variants, oracle_variants = query_variants(
        query, disjunction=disjunction, llm_parse=llm_parse, llm_client=llm_client,
        llm_parse_mode=mode if llm_parse else None,
    )
    dv = diff_variants(parsed_variants=parsed_variants, oracle_variants=oracle_variants,
                       branch_aware=branch_aware, people_number=query.get("people_number"))
    precision = dv["diff"]["precision"]
    recall = dv["diff"]["recall"]
    row = {
        "uid": query.get("uid"),
        **{k: dv["diff"]["counts"][k]
           for k in ("matched", "missing", "spurious", "wrong_value", "defaulted")},
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(_f1(precision, recall), 4),
        "value_accuracy": round(dv["diff"]["value_accuracy"], 4),
        "buckets": dv["diff"]["buckets"],
    }
    fams: set[str] = set()
    for v in parsed_variants:
        fams |= _families(v)
    return row, fams, oracle_variants


def measure(label: str, uids: list[str], data: dict, *, llm_client, mode: str,
            counter: CallCounter) -> dict:
    """Deterministic and LLM arms over the same queries, in one pass, query by query."""
    from parser_vs_oracle import _families, _f1
    from phase2_generalization_probe import clause_gap_kind, clause_is_covered

    det_rows: list[dict] = []
    llm_rows: list[dict] = []
    det_gap = llm_gap = 0
    det_q_gap = llm_q_gap = 0
    n_clauses = 0
    det_gap_kinds: Counter = Counter()
    llm_gap_kinds: Counter = Counter()
    recovered_kinds: Counter = Counter()
    broken_kinds: Counter = Counter()
    per_query: list[dict] = []
    llm_error_uids: list[str] = []

    for uid in uids:
        q = dict(data[uid])
        q.setdefault("uid", uid)
        clauses = q.get("hard_logic_py") or []

        det_row, det_fams, oracle_variants = _arm_row(q, llm_parse=False, llm_client=None)
        det_rows.append(det_row)

        before_live, before_fail = counter.live_calls, counter.failures + counter.timeouts
        llm_row, llm_fams, _ = _arm_row(q, llm_parse=True, llm_client=llm_client, mode=mode)
        llm_rows.append(llm_row)
        if counter.failures + counter.timeouts > before_fail:
            llm_error_uids.append(uid)
            counter.failed_uids.append(uid)
        fired = (counter.live_calls > before_live) or (counter.failures + counter.timeouts == before_fail)

        oracle_fams: set[str] = set()
        for v in oracle_variants:
            oracle_fams |= _families(v)

        d_gap = l_gap = 0
        q_recovered: list[str] = []
        q_broken: list[str] = []
        for clause in clauses:
            n_clauses += 1
            d_cov, kinds = clause_is_covered(clause, det_fams)
            l_cov, _ = clause_is_covered(clause, llm_fams)
            d_is_gap = (not d_cov) and clause_gap_kind(clause, det_fams, oracle_fams) == "parse_gap"
            l_is_gap = (not l_cov) and clause_gap_kind(clause, llm_fams, oracle_fams) == "parse_gap"
            if d_is_gap:
                d_gap += 1
                for k in kinds:
                    det_gap_kinds[k] += 1
            if l_is_gap:
                l_gap += 1
                for k in kinds:
                    llm_gap_kinds[k] += 1
            if d_is_gap and not l_is_gap:
                for k in kinds:
                    recovered_kinds[k] += 1
                q_recovered.extend(kinds)
            if l_is_gap and not d_is_gap:
                for k in kinds:
                    broken_kinds[k] += 1
                q_broken.extend(kinds)
        det_gap += d_gap
        llm_gap += l_gap
        det_q_gap += bool(d_gap)
        llm_q_gap += bool(l_gap)
        per_query.append({
            "uid": uid,
            "n_clauses": len(clauses),
            "det_parse_gaps": d_gap,
            "llm_parse_gaps": l_gap,
            "det_recall": det_row["recall"],
            "llm_recall": llm_row["recall"],
            "det_precision": det_row["precision"],
            "llm_precision": llm_row["precision"],
            "recovered_kinds": sorted(set(q_recovered)),
            "broken_kinds": sorted(set(q_broken)),
            "llm_families_added": sorted(llm_fams - det_fams),
            "llm_families_dropped": sorted(det_fams - llm_fams),
            "llm_call_ok": fired,
        })

    def agg(rows: list[dict], gaps: int, q_gaps: int) -> dict:
        p = statistics.mean(r["precision"] for r in rows) if rows else 0.0
        r_ = statistics.mean(r["recall"] for r in rows) if rows else 0.0
        n = len(uids)
        return {
            "precision": round(p, 4),
            "recall": round(r_, 4),
            "f1": round(_f1(p, r_), 4),
            "value_accuracy": round(statistics.mean(x["value_accuracy"] for x in rows), 4) if rows else 0.0,
            "matched": sum(x["matched"] for x in rows),
            "missing": sum(x["missing"] for x in rows),
            "spurious": sum(x["spurious"] for x in rows),
            "wrong_value": sum(x["wrong_value"] for x in rows),
            "parse_gap_clauses": gaps,
            "parse_gap_rate": round(gaps / n_clauses, 4) if n_clauses else 0.0,
            "clpr_ceiling": round(100.0 * (n_clauses - gaps) / n_clauses, 2) if n_clauses else 100.0,
            "queries_with_parse_gap": q_gaps,
            "fpr_ceiling": round(100.0 * (n - q_gaps) / n, 2) if n else 100.0,
        }

    return {
        "set": label,
        "mode": mode,
        "n": len(uids),
        "n_oracle_clauses": n_clauses,
        "deterministic": agg(det_rows, det_gap, det_q_gap),
        "llm_assisted": agg(llm_rows, llm_gap, llm_q_gap),
        "gap_kinds_deterministic": dict(det_gap_kinds.most_common()),
        "gap_kinds_llm": dict(llm_gap_kinds.most_common()),
        "clauses_recovered_by_llm_by_kind": dict(recovered_kinds.most_common()),
        "clauses_broken_by_llm_by_kind": dict(broken_kinds.most_common()),
        "queries_llm_recall_up": sum(1 for r in per_query if r["llm_recall"] > r["det_recall"]),
        "queries_llm_recall_down": sum(1 for r in per_query if r["llm_recall"] < r["det_recall"]),
        "queries_llm_errored": llm_error_uids,
        "per_query": per_query,
    }


# --- Reporting ------------------------------------------------------------


def assess(report: dict) -> tuple[bool, str]:
    """Reportable? An arm whose model never fired has no result at all."""
    tel = report["telemetry"]
    live, hits = tel["llm_live_calls"], tel["llm_cache_hits"]
    bad = tel["llm_failures"] + tel["llm_timeouts"]
    if report.get("backend") in (None, "none", "stub", "fixture"):
        return False, f"UNMEASURED: backend {report.get('backend')!r} is not a live model."
    if live == 0 and hits == 0:
        return False, ("UNMEASURED: the LLM never fired (0 live calls, 0 cache hits). Fix the "
                       "endpoint/model/key and rerun; do not read this as 'the LLM did not help'.")
    if live == 0:
        return True, (f"MEASURED FROM CACHE: 0 live calls, {hits} cache hits. The responses are a "
                      "previous live run's at temperature 0; the numbers are real but this run "
                      "cost nothing and proves nothing about current endpoint health.")
    total = live + bad
    if bad >= total:
        return False, f"UNMEASURED: every call failed or timed out ({bad}/{total})."
    if bad > total * 0.2:
        return True, (f"MEASURED but DEGRADED: {bad}/{total} calls failed or timed out, and a "
                      "failed call silently falls back to the deterministic parse -- so the LLM "
                      "arm is diluted toward the control. Lower bound only.")
    return True, (f"MEASURED: {live} live calls ({hits} cached), {bad} failed, "
                  f"${tel['est_cost_usd']}.")


def render_markdown(report: dict) -> str:
    lines = [
        f"Mode `{report['mode']}` · model `{report['model']}` · backend `{report['backend']}` · "
        f"thinking `{report['enable_thinking']}`",
        "",
        "| set | n | arm | parse P | parse R | parse F1 | parse-gap clauses | C-LPR ceiling | "
        "queries w/ gap | FPR ceiling |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for s in report["sets"]:
        for arm_key, arm_name in (("deterministic", "deterministic"), ("llm_assisted", "LLM-assisted")):
            a = s[arm_key]
            lines.append(
                f"| {s['set']} | {s['n']} | {arm_name} | {a['precision']} | {a['recall']} | "
                f"{a['f1']} | {a['parse_gap_clauses']}/{s['n_oracle_clauses']} | "
                f"{a['clpr_ceiling']} | {a['queries_with_parse_gap']} | {a['fpr_ceiling']} |"
            )
    lines += ["", "| set | clauses recovered by LLM | clauses newly broken by LLM | queries R up | "
              "queries R down |", "| --- | --- | --- | --- | --- |"]
    for s in report["sets"]:
        rec = sum(s["clauses_recovered_by_llm_by_kind"].values())
        brk = sum(s["clauses_broken_by_llm_by_kind"].values())
        lines.append(f"| {s['set']} | {rec} | {brk} | {s['queries_llm_recall_up']} | "
                     f"{s['queries_llm_recall_down']} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set", dest="sets", action="append", choices=sorted(SETS),
                    help="Query set (repeatable). Default: hf_medium.")
    ap.add_argument("--limit", type=int, default=None, help="First N queries of each set.")
    ap.add_argument("--uid", dest="uids", action="append", help="Explicit uid (repeatable).")
    ap.add_argument("--mode", choices=["audit", "extract", "extract_fill"], default="extract",
                    help="audit: LLM patches the deterministic parse. extract: LLM extracts "
                         "families first, deterministic values survive where the LLM is silent. "
                         "extract_fill: extract, but the LLM may only fill families the "
                         "deterministic parse left empty -- it never overwrites a regex value.")
    ap.add_argument("--model", default=None, help=f"Default {DEFAULT_MODEL} or TPC_P2_LLM_MODEL.")
    ap.add_argument("--enable-thinking", action="store_true",
                    help="Leave Qwen3 thinking mode on (~10x latency and output tokens).")
    ap.add_argument("--timeout-sec", type=float, default=None,
                    help="Per-call timeout (default 30, the library default).")
    ap.add_argument("--max-tokens", type=int, default=None, help="Per-call completion cap.")
    ap.add_argument("--no-cache", action="store_true",
                    help="Bypass the on-disk response cache, so every query is a live call.")
    ap.add_argument("--retries", type=int, default=3,
                    help="Retries per call on a transient provider error (429/5xx/timeout), with "
                         "linear backoff. Without these a rate-limited run silently measures the "
                         "deterministic fallback instead of the model.")
    ap.add_argument("--backoff-sec", type=float, default=3.0)
    ap.add_argument("--price-in-per-mtok", type=float, default=DEFAULT_PRICE_IN_PER_MTOK)
    ap.add_argument("--price-out-per-mtok", type=float, default=DEFAULT_PRICE_OUT_PER_MTOK)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    labels = args.sets or ["hf_medium"]

    os.environ["TPC_P2_LLM_PARSE_MODE"] = args.mode
    from chinatravel.agent.phase2.llm_client import build_llm_client

    config: dict[str, Any] = {}
    if args.model:
        config["model"] = args.model
    if args.enable_thinking:
        config["enable_thinking"] = True
    if args.timeout_sec is not None:
        config["timeout"] = args.timeout_sec
    if args.max_tokens is not None:
        config["max_tokens"] = args.max_tokens
    if args.no_cache:
        config["cache"] = False

    raw_client = build_llm_client(config)
    backend = getattr(raw_client, "backend", "none")
    model = getattr(getattr(raw_client, "inner", raw_client), "model", "n/a")
    counter = CallCounter()
    instrument_client(raw_client, counter, retries=args.retries, backoff_sec=args.backoff_sec)
    client = CacheHitCountingClient(raw_client, counter)

    print(f"# llm parse probe: mode={args.mode} backend={backend} model={model} "
          f"thinking={bool(args.enable_thinking)} sets={labels} limit={args.limit}", flush=True)

    started = time.perf_counter()
    sets_out = []
    for label in labels:
        uids, data = load_set(label, limit=args.limit, uids=args.uids)
        print(f"[probe] {label}: {len(uids)} queries ...", flush=True)
        sets_out.append(measure(label, uids, data, llm_client=client, mode=args.mode,
                                counter=counter))
        print(f"[probe] {label} done: live_calls={counter.live_calls} "
              f"cache_hits={counter.cache_hits} fail={counter.failures + counter.timeouts} "
              f"cost=${counter.as_dict(price_in=args.price_in_per_mtok, price_out=args.price_out_per_mtok)['est_cost_usd']}",
              flush=True)

    report = {
        "mode": args.mode,
        "backend": backend,
        "model": model,
        "enable_thinking": bool(args.enable_thinking),
        "timeout_sec": args.timeout_sec,
        "cache_bypassed": bool(args.no_cache),
        "limit": args.limit,
        "wall_sec": round(time.perf_counter() - started, 1),
        "measurement_kind": "screen",
        "telemetry": counter.as_dict(price_in=args.price_in_per_mtok,
                                     price_out=args.price_out_per_mtok),
        "sets": sets_out,
    }
    reportable, verdict = assess(report)
    report["reportable"] = reportable
    report["verdict"] = verdict

    if args.out_dir:
        d = Path(args.out_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
        (d / "summary.md").write_text(render_markdown(report), encoding="utf-8")
        print(f"[probe] wrote {d}/report.json, summary.md", flush=True)

    print()
    print(render_markdown(report))
    print()
    print(json.dumps(report["telemetry"], indent=2))
    print(f"REPORTABLE: {reportable}\nVERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
