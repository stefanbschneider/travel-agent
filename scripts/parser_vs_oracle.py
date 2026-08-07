#!/usr/bin/env python3
"""Parser-vs-oracle attribution (Axis 1 of docs/tpc_phase2_eval.md).

Compares the no-oracle parser output against the oracle constraints **in the shared solver-dict
schema** and reports, per constraint family: precision / recall / value-accuracy, with failure
buckets: missing, spurious, wrong_value, disjunction_flattened.

This module provides the pure diff core. The CLI over a split and behavioral-equivalence check
are available through the same module.
"""

from __future__ import annotations

import math


def _present(value) -> bool:
    """A constraint family counts as present only if it carries a non-empty value."""
    return value not in (None, [], {}, "", ())


def _canon(value):
    """Canonicalize for order-insensitive equality of list-valued constraints."""
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        canon_items = [_canon(v) for v in value]
        try:
            return sorted(canon_items, key=lambda x: repr(x))
        except Exception:
            return canon_items
    return value


def _families(d: dict) -> set:
    if not isinstance(d, dict):
        return set()
    return {k for k, v in d.items() if _present(v)}


def _taxi_cars_default(people_number) -> int | None:
    """The party-size-derived default parse_query_no_oracle always fills in for
    taxi_cars_equals (ceil(people/4), matching the oracle's own formula). It's a deliberate,
    vacuously-true-on-taxi-free-plans default -- not a real over-extraction -- so it
    shouldn't count against precision when the oracle never mentions taxi count at all."""
    if people_number is None:
        return None
    try:
        people = int(people_number)
    except (TypeError, ValueError):
        return None
    return max(1, math.ceil(people / 4))


def _canonicalize_hotel_distance(d: dict) -> dict:
    """hotel_nearby (dict) and poi_distance_hotel (list-of-dict) encode the same hotel-distance
    constraint in two schema shapes -- the no-oracle parser always mirrors one into the other, and
    the oracle sometimes does too, which double-counts the same defect under two family
    names. Canonicalize to poi_distance_hotel only for diff purposes."""
    if not isinstance(d, dict):
        return d
    nearby = d.get("hotel_nearby")
    if not _present(nearby):
        return d
    out = dict(d)
    out.pop("hotel_nearby", None)
    if not _present(out.get("poi_distance_hotel")):
        out["poi_distance_hotel"] = [nearby]
    return out


def diff_constraints(parsed: dict, oracle: dict, *, people_number=None) -> dict:
    """Structural diff of one parsed vs one oracle solver-constraint dict.

    Returns counts, per-bucket family lists, and precision/recall/value-accuracy. ``defaulted``
    families (currently just a party-size-matching ``taxi_cars_equals``) are excluded from
    ``spurious``/precision -- they're a deliberate always-on default, not an extraction defect.
    """
    parsed = _canonicalize_hotel_distance(parsed)
    oracle = _canonicalize_hotel_distance(oracle)
    p_fams = _families(parsed)
    o_fams = _families(oracle)
    taxi_default = _taxi_cars_default(people_number)

    missing, spurious, wrong_value, matched, defaulted = [], [], [], [], []
    for fam in o_fams - p_fams:
        missing.append(fam)
    for fam in p_fams - o_fams:
        if fam == "taxi_cars_equals" and taxi_default is not None and parsed.get(fam) == taxi_default:
            defaulted.append(fam)
        else:
            spurious.append(fam)
    for fam in p_fams & o_fams:
        if _canon(parsed.get(fam)) == _canon(oracle.get(fam)):
            matched.append(fam)
        else:
            wrong_value.append(fam)

    n_matched = len(matched)
    n_missing = len(missing)
    n_spurious = len(spurious)
    n_wrong = len(wrong_value)
    n_defaulted = len(defaulted)

    predicted = n_matched + n_spurious + n_wrong
    relevant = n_matched + n_missing + n_wrong
    precision = n_matched / predicted if predicted else 1.0
    recall = n_matched / relevant if relevant else 1.0
    shared = n_matched + n_wrong
    value_accuracy = n_matched / shared if shared else 1.0

    return {
        "counts": {
            "matched": n_matched,
            "missing": n_missing,
            "spurious": n_spurious,
            "wrong_value": n_wrong,
            "defaulted": n_defaulted,
        },
        "buckets": {
            "matched": sorted(matched),
            "missing": sorted(missing),
            "spurious": sorted(spurious),
            "wrong_value": sorted(wrong_value),
            "defaulted": sorted(defaulted),
        },
        "precision": precision,
        "recall": recall,
        "value_accuracy": value_accuracy,
    }


def _best_oracle_index(parsed_variant: dict, oracle_variants: list[dict]) -> int:
    """Pick the oracle branch the parsed variant matches best (most matched families)."""
    best_i, best_matched = 0, -1
    for i, ov in enumerate(oracle_variants or [{}]):
        d = diff_constraints(parsed_variant, ov)
        if d["counts"]["matched"] > best_matched:
            best_matched, best_i = d["counts"]["matched"], i
    return best_i


def _match_pairs(parsed_variants: list[dict], oracle_variants: list[dict]):
    """Greedy one-to-one matching of oracle branches to parsed branches.

    Returns (pairs, unmatched_oracle_idx, unmatched_parsed_idx) where pairs is a list of
    (oracle_idx, parsed_idx) chosen by descending matched-family count without reusing a branch.
    """
    candidates = []
    for oi, ov in enumerate(oracle_variants):
        for pj, pv in enumerate(parsed_variants):
            m = diff_constraints(pv, ov)["counts"]["matched"]
            candidates.append((m, oi, pj))
    # Highest matched first; ties broken deterministically by (oracle_idx, parsed_idx).
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_o, used_p, pairs = set(), set(), []
    for _m, oi, pj in candidates:
        if oi in used_o or pj in used_p:
            continue
        used_o.add(oi); used_p.add(pj); pairs.append((oi, pj))
    unmatched_o = [oi for oi in range(len(oracle_variants)) if oi not in used_o]
    unmatched_p = [pj for pj in range(len(parsed_variants)) if pj not in used_p]
    return pairs, unmatched_o, unmatched_p


def _branch_aware_diff(parsed_variants: list[dict], oracle_variants: list[dict], *,
                       people_number=None) -> dict:
    """Matched-pair diff aggregated across all OR branches (micro-averaged counts).

    Each oracle branch is matched to a distinct parsed branch; per-pair family counts are summed.
    Unmatched oracle branches contribute their families as recall misses (``missing``); extra
    parsed branches contribute theirs as precision misses (``spurious``). This credits correct
    multi-branch parsing that the single-branch diff (parsed_variants[0] only) cannot.
    """
    pairs, unmatched_o, unmatched_p = _match_pairs(parsed_variants, oracle_variants)
    tot = {"matched": 0, "missing": 0, "spurious": 0, "wrong_value": 0, "defaulted": 0}
    buckets = {"matched": [], "missing": [], "spurious": [], "wrong_value": [], "defaulted": []}
    for oi, pj in pairs:
        d = diff_constraints(parsed_variants[pj], oracle_variants[oi], people_number=people_number)
        for k in tot:
            tot[k] += d["counts"][k]
            buckets[k].extend(d["buckets"][k])
    for oi in unmatched_o:  # whole oracle branch missing from the parse
        fams = sorted(_families(_canonicalize_hotel_distance(oracle_variants[oi])))
        tot["missing"] += len(fams)
        buckets["missing"].extend(fams)
    for pj in unmatched_p:  # extra parsed branch the oracle does not have
        canon_pv = _canonicalize_hotel_distance(parsed_variants[pj])
        taxi_default = _taxi_cars_default(people_number)
        for fam in sorted(_families(canon_pv)):
            if fam == "taxi_cars_equals" and taxi_default is not None and canon_pv.get(fam) == taxi_default:
                tot["defaulted"] += 1
                buckets["defaulted"].append(fam)
            else:
                tot["spurious"] += 1
                buckets["spurious"].append(fam)

    predicted = tot["matched"] + tot["spurious"] + tot["wrong_value"]
    relevant = tot["matched"] + tot["missing"] + tot["wrong_value"]
    shared = tot["matched"] + tot["wrong_value"]
    return {
        "counts": tot,
        "buckets": buckets,
        "precision": tot["matched"] / predicted if predicted else 1.0,
        "recall": tot["matched"] / relevant if relevant else 1.0,
        "value_accuracy": tot["matched"] / shared if shared else 1.0,
    }


def diff_variants(*, parsed_variants: list[dict], oracle_variants: list[dict],
                  branch_aware: bool = False, people_number=None) -> dict:
    """Diff parsed vs oracle at the variant-list level, flagging disjunction flattening.

    ``disjunction_flattened`` is True when the oracle encodes multiple OR branches but the parser
    collapsed them into fewer variants.

    Two scoring modes:
    - default (``branch_aware=False``): **single-branch** diff — scores only ``parsed_variants[0]``
      against its best-matching oracle branch. This UNDER-REPORTS correct multi-branch parsing: a
      perfectly split N-branch query is credited for at most one branch, so its recall/precision
      look low even when every branch is parsed correctly. Prefer ``disjunction_flattened`` and the
      disjunction-aware behavioral check as the trustworthy signals for disjunctive queries.
    - ``branch_aware=True``: matched-pair diff over all branches (see ``_branch_aware_diff``), which
      credits multi-branch parsing and subsumes ``disjunction_flattened`` (a flattened query shows
      unmatched oracle branches as recall misses).
    """
    parsed_variants = parsed_variants or [{}]
    oracle_variants = oracle_variants or [{}]
    flattened = len(oracle_variants) > 1 and len(parsed_variants) < len(oracle_variants)

    if branch_aware:
        diff = _branch_aware_diff(parsed_variants, oracle_variants, people_number=people_number)
    else:
        pv = parsed_variants[0]
        oi = _best_oracle_index(pv, oracle_variants)
        diff = diff_constraints(pv, oracle_variants[oi], people_number=people_number)

    return {
        "disjunction_flattened": flattened,
        "parsed_branches": len(parsed_variants),
        "oracle_branches": len(oracle_variants),
        "diff": diff,
    }


# --- Split-level report (CLI) ---------------------------------------------

import argparse  # noqa: E402
import csv  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_queries(split: str, lang: str = "en"):
    from chinatravel.data.load_datasets import load_query

    args = argparse.Namespace(splits=split, lang=lang, oracle_translation=True)
    return load_query(args)


def _hf_city_lookup() -> dict[str, str]:
    """Chinese city name -> English city name (matches ``target_city``/``start_city`` in the
    local en data), by CITY_SLUGS index -- see ``chinatravel/environment/language.py``."""
    from chinatravel.environment.language import CITY_NAMES

    return dict(zip(CITY_NAMES["zh"], CITY_NAMES["en"]))


def load_hf_queries(config: str = "default", splits: list[str] | None = None):
    """Load the HF ``LAMDA-NeSy/ChinaTravel`` dataset (see ``docs/tpc_phase2_eval.md``) in
    the same ``(query_ids, query_data)`` shape ``_load_queries`` returns, normalized to what the
    local pipeline expects: ``nature_language_en`` -> ``nature_language``, Chinese city names ->
    English, ``hard_logic_py`` literal-eval'd if it arrived as a string. A **measurement set**,
    never tuned against (uid-disjoint from ``tpc_phase1`` per the compare-script findings) --
    read-only by design, see docs/tpc_phase2_eval.md.
    """
    import ast

    from datasets import load_dataset

    ds = load_dataset("LAMDA-NeSy/ChinaTravel", name=config)
    splits = splits or list(ds.keys())
    city_lookup = _hf_city_lookup()

    query_ids = []
    query_data = {}
    for sp in splits:
        for row in ds[sp].to_list():
            uid = row.get("uid")
            if not uid or uid in query_data:
                continue
            q = dict(row)
            nl_en = q.pop("nature_language_en", None)
            if nl_en:
                q["nature_language"] = nl_en
            q["start_city"] = city_lookup.get(q.get("start_city"), q.get("start_city"))
            q["target_city"] = city_lookup.get(q.get("target_city"), q.get("target_city"))
            hlp = q.get("hard_logic_py")
            if isinstance(hlp, str):
                try:
                    q["hard_logic_py"] = ast.literal_eval(hlp)
                except (ValueError, SyntaxError):
                    q["hard_logic_py"] = []
            q.setdefault("uid", uid)
            query_ids.append(uid)
            query_data[uid] = q
    return query_ids, query_data


def query_variants(query: dict, *, disjunction: bool = False, llm_parse: bool = False, llm_client=None,
                   entity_resolution: bool = False, drop_unsatisfiable_names: bool = False,
                   llm_parse_mode: str | None = None):
    """Return (parsed_no_oracle_variants, oracle_variants) in the shared solver-dict schema.

    When ``disjunction`` is True, the parsed side is produced through the Phase 2 normalize layer
    with ``TPC_P2_DISJUNCTION`` on, so disjunctive queries expand into one branch-local variant per
    OR arm (the same path the harness feeds the solver). Default (False) keeps the flat single-
    variant no-oracle parse, so existing reports are unchanged.

    When ``llm_parse`` is True, also routes through the LLM corrective-audit stage
    (``normalize.llm_parse_stub`` via ``parse_to_ir``) using ``llm_client`` -- so this report
    measures the same parse path ``solve_phase2.py`` uses when a backend is configured, not just
    the deterministic fallback. A failing/misconfigured client degrades to the deterministic parse
    (see the parse_to_ir fix), never raises.

    When ``entity_resolution`` is True, routes through the deterministic entity-resolution layer
    (``normalize.resolve_entities`` via ``TPC_P2_ENTITY_RESOLUTION``).

    When ``drop_unsatisfiable_names`` is True, routes through the same layer's P22 drop rule
    (``TPC_P2_DROP_UNSATISFIABLE_NAMES``) -- reachable standalone, without ``entity_resolution``.
    """
    import parse_constraints
    from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants

    if disjunction or llm_parse or entity_resolution or drop_unsatisfiable_names:
        from chinatravel.agent.phase2 import normalize
        from chinatravel.agent.phase2.orchestrator import Flags

        flags = Flags(disjunction=disjunction, llm_parse=llm_parse, entity_resolution=entity_resolution,
                       drop_unsatisfiable_names=drop_unsatisfiable_names)
        if llm_parse_mode:
            # "audit" (patch the regex parse) vs "extract" (LLM-first families). Explicit rather
            # than env-derived so a caller measuring both modes in one process cannot mix them up.
            flags.llm_parse_mode = llm_parse_mode
        ir = normalize.parse_to_ir(query, llm_client=llm_client, flags=flags)
        parsed = normalize.ir_to_solver_variants(ir, query, flags=flags)
    else:
        parsed = solver_constraint_variants(
            query, parse_constraints.parse_query_no_oracle(query), use_oracle=False
        )
    oracle = solver_constraint_variants(
        query, parse_constraints.parse_query(query), use_oracle=True
    )
    return parsed, oracle


def compute_query_diff(query: dict, *, disjunction: bool = False, branch_aware: bool = False,
                       llm_parse: bool = False, llm_client=None, entity_resolution: bool = False,
                       llm_parse_mode: str | None = None) -> dict:
    parsed_variants, oracle_variants = query_variants(
        query, disjunction=disjunction, llm_parse=llm_parse, llm_client=llm_client,
        entity_resolution=entity_resolution, llm_parse_mode=llm_parse_mode,
    )
    dv = diff_variants(parsed_variants=parsed_variants, oracle_variants=oracle_variants,
                       branch_aware=branch_aware, people_number=query.get("people_number"))
    precision = dv["diff"]["precision"]
    recall = dv["diff"]["recall"]
    row = {
        "uid": query.get("uid"),
        "oracle_branches": dv["oracle_branches"],
        "parsed_branches": dv["parsed_branches"],
        "disjunction_flattened": dv["disjunction_flattened"],
        **{k: dv["diff"]["counts"][k] for k in ("matched", "missing", "spurious", "wrong_value", "defaulted")},
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(_f1(precision, recall), 4),
        "value_accuracy": round(dv["diff"]["value_accuracy"], 4),
        # Per-family bucket membership (which constraint families were matched/missing/spurious/
        # wrong_value for this uid). Not written to the per-uid CSV (see run_report) -- consumed by
        # _aggregate_family_stats to attribute precision/recall loss to specific families.
        "buckets": dv["diff"]["buckets"],
    }
    return row


def _parsed_pass(parsed_variants: list[dict], plan: dict, target_city: str, *,
                 disjunction: bool) -> bool:
    """Do the parsed constraints accept ``plan``? OR semantics over disjunction-expanded variants
    when ``disjunction=True`` (accept if ANY branch's constraints all pass), matching how the
    agent actually accepts plans (``TPCAgent._solve`` keeps a plan that satisfies any one
    variant). Never raises -- a verifier exception is treated as a reject (conservative)."""
    from chinatravel.agent.tpc_agent.parsed_verifier import evaluate_parsed_constraints

    try:
        if disjunction:
            return any(
                all(evaluate_parsed_constraints(v, plan, target_city)) for v in parsed_variants
            )
        return all(evaluate_parsed_constraints(parsed_variants[0], plan, target_city))
    except Exception:
        return False


def _oracle_pass(query: dict, plan: dict) -> bool:
    """Do this query's oracle (``hard_logic_py``) constraints accept ``plan``? Never raises."""
    from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py

    try:
        oracle_res = evaluate_constraints_py(query.get("hard_logic_py", []) or [], plan, verbose=False)
        return all(bool(r) for r in oracle_res)
    except Exception:
        return False


def behavioral_check(query: dict, plan: dict, *, disjunction: bool = False,
                     llm_parse: bool = False, llm_client=None, entity_resolution: bool = False) -> dict:
    """Do parsed vs oracle constraints accept/reject the plan identically? (the "accept-side"
    check: one plan per uid, the oracle-optimal ``results/best/<uid>.json`` -- see
    ``reject_probe_check`` for the complementary reject-side probe).
    """
    parsed_variants, _ = query_variants(
        query, disjunction=disjunction, llm_parse=llm_parse, llm_client=llm_client,
        entity_resolution=entity_resolution,
    )
    target_city = query.get("target_city", "")
    parsed_pass = _parsed_pass(parsed_variants, plan, target_city, disjunction=disjunction)
    oracle_pass = _oracle_pass(query, plan)
    return {"uid": query.get("uid"), "oracle_pass": oracle_pass, "parsed_pass": parsed_pass,
            "agree": oracle_pass == parsed_pass}


# --- Two-sided behavioral proxy: reject-side probes ------------------------
#
# The accept-side check above is structurally blind to *missing* constraints: both the parsed and
# oracle sides accept the same oracle-optimal plan regardless of what the parser missed, so a
# parser that silently drops constraints looks perfect on this check alone (this is exactly what
# let the LLM audit look +9 behavioral pts better while e2e FPR got worse -- see docs/
# tpc_phase2_eval.md, "the parser win did not transfer"). The reject side closes that blind spot:
# feed each uid *other* uids' oracle-optimal plans (its "reject probes") -- plans that legitimately
# violate this uid's required-attraction/hotel/cuisine families -- and check whether the parsed
# constraints reject them too. A parser missing a family will wrongly *accept* a probe the oracle
# rejects, which this check -- and only this check -- can catch.


def _group_key(query: dict) -> tuple:
    return (query.get("target_city"), query.get("days"))


def select_reject_probes(
    uid: str, query: dict, query_data: dict[str, dict], *, results_best: Path, k: int = 4,
) -> list[str]:
    """Deterministic candidate probe uids: other uids in ``query_data`` sharing (target_city,
    days) with ``query``, restricted to ones with an existing ``results/best`` plan, sorted, first
    ``k``. Determinism (sort, don't sample) keeps the metric comparable across runs."""
    key = _group_key(query)
    candidates = sorted(
        u for u, q in query_data.items()
        if u != uid and _group_key(q) == key and (results_best / f"{u}.json").exists()
    )
    return candidates[:k]


def reject_probe_check(
    query: dict, parsed_variants: list[dict], probe_uids: list[str], *,
    results_best: Path, disjunction: bool = False,
) -> dict:
    """Run the reject-side probe check for one uid: for each candidate probe plan, keep it only
    if this uid's *oracle* constraints reject it (a probe the oracle happens to accept -- e.g. a
    uid with no hard constraints at all -- carries no reject-side signal and is dropped); among
    kept probes, count how many the *parsed* constraints also reject."""
    target_city = query.get("target_city", "")
    kept: list[str] = []
    reject_agree = 0
    for probe_uid in probe_uids:
        plan_path = results_best / f"{probe_uid}.json"
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if _oracle_pass(query, plan):
            continue  # oracle doesn't reject this probe -- no reject-side signal
        kept.append(probe_uid)
        if not _parsed_pass(parsed_variants, plan, target_city, disjunction=disjunction):
            reject_agree += 1
    n_kept = len(kept)
    return {
        "uid": query.get("uid"),
        "probe_uids": probe_uids,
        "kept_probe_uids": kept,
        "n_probes": len(probe_uids),
        "n_kept": n_kept,
        "reject_agree": reject_agree,
        "reject_agreement": (reject_agree / n_kept) if n_kept else None,
    }


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def _f1(precision: float, recall: float) -> float:
    denom = precision + recall
    return (2.0 * precision * recall / denom) if denom else 0.0


def _aggregate_family_stats(rows: list[dict], *, max_examples: int = 5,
                            per_variant: bool = False) -> list[dict]:
    """Roll the per-uid bucket membership up to per-family counts, sorted by spurious count
    (the dominant loss per docs/tpc_phase2_eval.md) so the top of the list is where to look first
    for regex over-extraction fixes. Each family also carries a few example uids per failure
    bucket to jump straight to a repro.

    By default (``per_variant=False``) counts are de-duplicated per (uid, family, bucket): a
    family that appears in the same bucket across multiple OR branches of one uid (branch-aware
    diff) counts once, not once per branch; OR-heavy UIDs otherwise inflate family
    totals). Pass ``per_variant=True`` for the raw per-branch-occurrence view.
    """
    stats: dict[str, dict] = {}
    for row in rows:
        uid = row.get("uid")
        buckets = row.get("buckets", {})
        for bucket in ("matched", "missing", "spurious", "wrong_value", "defaulted"):
            fams = buckets.get(bucket, [])
            if not per_variant:
                fams = sorted(set(fams))
            for fam in fams:
                fam_stats = stats.setdefault(
                    fam,
                    {
                        "family": fam,
                        "matched": 0,
                        "missing": 0,
                        "spurious": 0,
                        "wrong_value": 0,
                        "defaulted": 0,
                        "reject_miss": 0,
                        "example_missing_uids": [],
                        "example_spurious_uids": [],
                        "example_wrong_value_uids": [],
                    },
                )
                fam_stats[bucket] += 1
                example_key = f"example_{bucket}_uids"
                if example_key in fam_stats and len(fam_stats[example_key]) < max_examples:
                    fam_stats[example_key].append(uid)
    return sorted(stats.values(), key=lambda s: (-s["spurious"], -s["missing"], s["family"]))


def _attribute_reject_misses(
    family_stats: list[dict], *, rows_by_uid: dict[str, dict], reject_miss_uids: list[str],
) -> None:
    """For each UID where a reject probe was wrongly accepted by the parsed constraints, credit
    its cause to an oracle family missing from that UID's parsed constraints. Mutates
    ``family_stats`` in place. A family that appears only as a reject-miss cause still belongs to
    that UID's ``missing`` bucket, which ``_aggregate_family_stats`` has already seeded."""
    by_family = {s["family"]: s for s in family_stats}
    for uid in reject_miss_uids:
        row = rows_by_uid.get(uid)
        if not row:
            continue
        for fam in row.get("buckets", {}).get("missing", []):
            if fam in by_family:
                by_family[fam]["reject_miss"] += 1


def run_report(split: str, *, uids=None, limit=None, behavioral=False, lang="en",
               results_best=None, out_dir=None, disjunction=False, branch_aware=False,
               llm_parse=False, llm_client=None, per_variant_family_stats=False,
               entity_resolution=False, hf_config=None, hf_splits=None) -> dict:
    if hf_config:
        query_ids, query_data = load_hf_queries(hf_config, hf_splits)
        split = f"hf:{hf_config}:{'+'.join(hf_splits) if hf_splits else 'all'}"
    else:
        query_ids, query_data = _load_queries(split, lang=lang)
    selected = list(uids) if uids else (query_ids[: int(limit)] if limit else query_ids)

    if llm_parse and llm_client is None:
        # Build once per report (not per uid) -- CachingLLMClient makes repeat uids/reruns free,
        # but constructing the underlying OpenAI-compatible client per query would still be
        # wasteful and, for the fixture backend, unnecessary duplicate directory reads. Reuse
        # solve_phase2's config loader (env vars + agent_env/config.toml) so this measures the
        # same backend/model the real harness would use, not just bare env vars.
        agent_env_scripts = PROJECT_ROOT / "agent_env" / "scripts"
        if str(agent_env_scripts) not in sys.path:
            sys.path.insert(0, str(agent_env_scripts))
        import solve_phase2 as _runner
        from chinatravel.agent.phase2 import llm_client as p2_llm

        llm_client = p2_llm.build_llm_client(_runner._phase2_llm_config())

    rows = []
    behav_rows = []
    reject_rows = []
    results_best = Path(results_best) if results_best else PROJECT_ROOT / "results" / "best"
    for uid in selected:
        q = query_data[uid]
        q.setdefault("uid", uid)
        row = compute_query_diff(
            q, disjunction=disjunction, branch_aware=branch_aware,
            llm_parse=llm_parse, llm_client=llm_client, entity_resolution=entity_resolution,
        )
        rows.append(row)
        if behavioral:
            plan_path = results_best / f"{uid}.json"
            if plan_path.exists():
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                behav_rows.append(behavioral_check(
                    q, plan, disjunction=disjunction, llm_parse=llm_parse, llm_client=llm_client,
                    entity_resolution=entity_resolution,
                ))
            # Reject-side probes close the accept-side check's blind spot to *missing*
            # constraints: both sides can accept the same oracle-optimal plan even when the
            # parser dropped one. Probes come from the whole split (``query_data``), not just
            # ``selected``, so the metric is stable across differently-scoped reports.
            probe_uids = select_reject_probes(uid, q, query_data, results_best=results_best)
            parsed_variants, _ = query_variants(
                q, disjunction=disjunction, llm_parse=llm_parse, llm_client=llm_client,
                entity_resolution=entity_resolution,
            )
            reject_rows.append(reject_probe_check(
                q, parsed_variants, probe_uids, results_best=results_best, disjunction=disjunction,
            ))

    mean_precision = _mean(r["precision"] for r in rows)
    mean_recall = _mean(r["recall"] for r in rows)
    agg = {
        "split": split,
        "n": len(rows),
        "precision": round(mean_precision, 4),
        "recall": round(mean_recall, 4),
        "f1": round(_f1(mean_precision, mean_recall), 4),
        "value_accuracy": round(_mean(r["value_accuracy"] for r in rows), 4),
        "disjunction_flattened": sum(1 for r in rows if r["disjunction_flattened"]),
        "totals": {k: sum(r[k] for r in rows) for k in ("matched", "missing", "spurious", "wrong_value", "defaulted")},
        "family_stats": _aggregate_family_stats(rows, per_variant=per_variant_family_stats),
    }
    if behavioral:
        # No best plans for this data source (e.g. the familiar-100 archive ships none) means the
        # accept-side check has nothing to evaluate. Report None (unavailable) rather than a 0.0
        # that reads as total disagreement -- mirroring reject_agreement's None and the ceiling.
        accept_agreement = (
            round(_mean(1.0 if b["agree"] else 0.0 for b in behav_rows), 4)
            if behav_rows else None
        )
        kept_rows = [r for r in reject_rows if r["n_kept"] > 0]
        total_kept = sum(r["n_kept"] for r in kept_rows)
        total_reject_agree = sum(r["reject_agree"] for r in kept_rows)
        reject_agreement = round(total_reject_agree / total_kept, 4) if total_kept else None
        _sides = [s for s in (accept_agreement, reject_agreement) if s is not None]
        behavioral_balanced = round(_mean(_sides), 4) if _sides else None
        reject_miss_uids = sorted(
            r["uid"] for r in kept_rows if r["reject_agree"] < r["n_kept"]
        )
        rows_by_uid = {r["uid"]: r for r in rows}
        _attribute_reject_misses(
            agg["family_stats"], rows_by_uid=rows_by_uid, reject_miss_uids=reject_miss_uids,
        )
        agg["behavioral"] = {
            "n": len(behav_rows),
            "agreement_rate": accept_agreement,  # retained for row continuity
            "accept_agreement": accept_agreement,
            "disagreements": [b["uid"] for b in behav_rows if not b["agree"]],
            "reject_agreement": reject_agreement,
            "reject_probes_n": len(reject_rows),
            "reject_probes_kept_n": len(kept_rows),
            "reject_miss_uids": reject_miss_uids,
            "behavioral_balanced": behavioral_balanced,
        }

    if out_dir:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"parser_vs_oracle_{split}.csv"
        csv_rows = [{k: v for k, v in r.items() if k != "buckets"} for r in rows]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()) if csv_rows else ["uid"])
            w.writeheader()
            w.writerows(csv_rows)
        (out_dir / f"parser_vs_oracle_{split}.json").write_text(
            json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return agg


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", default=None, help="Explicit split name (overrides --split-set).")
    p.add_argument("--split-set", choices=["val", "test"], default="val")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--behavioral", action="store_true", help="Also run the behavioral-equivalence check.")
    p.add_argument("--lang", default="en", choices=["en", "zh"])
    p.add_argument("--disjunction", action="store_true",
                   help="Expand disjunctive queries via the Phase 2 normalize layer "
                        "(TPC_P2_DISJUNCTION) instead of the flat single-variant parse.")
    p.add_argument("--branch-aware", action="store_true",
                   help="Score precision/recall with a matched-pair diff across all OR branches "
                        "(credits multi-branch parsing) instead of the single-branch "
                        "parsed_variants[0] diff. Best combined with --disjunction.")
    p.add_argument("--out-dir", default=str(PROJECT_ROOT / "cache" / "phase2_parser_vs_oracle"))
    p.add_argument("--llm-parse", action="store_true",
                   help="Route the parsed side through the LLM corrective-audit stage "
                        "(same backend solve_phase2.py would use, per TPC_P2_LLM_BACKEND / "
                        "agent_env/config.toml). Responses are cached by default (TPC_P2_LLM_CACHE), "
                        "so a warm rerun is free and byte-deterministic.")
    p.add_argument("--per-variant-family-stats", action="store_true",
                   help="Count family_stats occurrences once per OR-branch variant instead of "
                        "once per (uid, family, bucket) -- the raw pre-dedup view. "
                        "Default is de-duplicated, which is the trustworthy signal.")
    p.add_argument("--entity-resolution", action="store_true",
                   help="Route the parsed side through the deterministic entity-resolution layer "
                        "(TPC_P2_ENTITY_RESOLUTION) that canonicalizes name-bearing "
                        "families against the target city's POI catalog.")
    p.add_argument("--hf-config", default=None, choices=["default", "preference"],
                   help="Measure against the HF LAMDA-NeSy/ChinaTravel dataset instead of a local "
                        "split (see docs/tpc_phase2_eval.md) -- a held-out phrasing "
                        "generalization probe, uid-disjoint from tpc_phase1. Overrides --split/"
                        "--split-set. A measurement set only -- never tune the parser against it.")
    p.add_argument("--hf-splits", nargs="*", default=None,
                   help="HF config splits to include (default: all splits in --hf-config, e.g. "
                        "easy/medium/human for the 'default' config).")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    split = args.split or ("tpc_phase2_test" if args.split_set == "test" else "tpc_phase2_val")
    agg = run_report(split, limit=args.limit, behavioral=args.behavioral, lang=args.lang,
                     out_dir=args.out_dir, disjunction=args.disjunction,
                     branch_aware=args.branch_aware, llm_parse=args.llm_parse,
                     per_variant_family_stats=args.per_variant_family_stats,
                     entity_resolution=args.entity_resolution,
                     hf_config=args.hf_config, hf_splits=args.hf_splits)
    print(json.dumps(agg, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
