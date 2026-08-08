#!/usr/bin/env python3
"""Phase 2 split runner: our own orchestrator (not opencode/codex).

Two modes, chosen by whether a whole-run wall-clock envelope is set:

**Per-query** (no ``--total-budget-sec``) — the development mode. Walks the split once, giving each
query the same budget, and for each query:
- loads it with oracle fields available for evaluation, but hides them from the agent,
- runs ``chinatravel.agent.phase2.orchestrator.solve_phase2`` (deterministic; LLM off by default),
- writes the official ``results/<method>/<uid>.json`` plan,
- writes ``<work_dir>/<uid>/evaluation.json`` (official evaluators) and ``telemetry.json``,
- is resume-safe (skips queries whose result file already exists).

**Whole-run** (``--total-budget-sec``, and what the organizer entry point uses) — hands the split to
the sweep scheduler (``chinatravel.agent.phase2.sweeps``): triage every query cheaply, repair the
constraint-failing ones at growing budgets, polish the rest, across worker processes, keeping the
best plan per query. See ``run_sweeps_split``. Scoring is *not* part of this mode -- it would run
after the deadline; use ``scripts/phase2_full_run.py``, which runs this and then ``eval_tpc.py``.

Usage:
    python agent_env/scripts/solve_phase2.py --split tpc_phase1 --limit 3
    python agent_env/scripts/solve_phase2.py --split tpc_phase2_val --resume --budget-sec 60
    python agent_env/scripts/solve_phase2.py --split tpc_phase2_familiar_100 --total-budget-sec 18000
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tomllib
from pathlib import Path
from statistics import mean, pstdev
import urllib.request

try:  # optional: only the opt-in RSS growth warning below needs it
    import psutil
except ImportError:  # pragma: no cover - exercised by the dependency-minimality test
    # Keeping psutil out of the submission install matters: it and ortools are the only two
    # packages this repository adds to upstream's dependency set, and the organizers asked for
    # minimal installs. RSS telemetry is a development nicety, so it degrades to absent here
    # rather than being a hard requirement of the shipped path.
    psutil = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# Reuse the baseline harness helpers (visible_query, evaluate_one, write_json, ...).
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import solve_script_with_harness as hb  # noqa: E402

from chinatravel.agent.phase2 import fallback as fallback_mod  # noqa: E402
from chinatravel.agent.phase2 import llm_client as p2_llm  # noqa: E402
from chinatravel.agent.phase2 import orchestrator as orch  # noqa: E402

DEFAULT_METHOD_PREFIX = "phase2_e2e_"
DEFAULT_BUDGET_SEC = orch.DEFAULT_BUDGET_SEC  # 300s (our working default); override via --budget-sec
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "agent_env" / "config.toml"


def _coverage_unknown_enabled() -> bool:
    """Opt-in flag for the P17(a) coverage signal (roadmap): keep a query the checker calls
    ``constraints_ok`` in the sweep scheduler's repair rotation, instead of promoting it to
    polish, when its visible text mentions something (a budget, a room type) the parse produced no
    family for. Library default off, so ``run_sweeps_split``'s pass selection is byte-identical
    unless this is set. Scheduler-level, like ``TPC_PIN_TIMED_WINDOWS``/``TPC_WINDOW_ANCHOR`` --
    not a ``Flags`` field, since it governs which pass a query enters rather than how one query is
    solved."""
    return os.environ.get("TPC_P2_COVERAGE_UNKNOWN", "0") not in ("", "0", "false", "False")

# --- Total wall-clock envelope -------------------------------------------------------------
# The organizers confirmed (2026-08-04) a single 5-hour wall-clock budget for the whole
# 100-query run, with no per-query timeout. A fixed per-query budget cannot honour that: at the
# 300s working default, 100 queries would need 8.3h and the run would be cut off mid-split, so
# every query after the cutoff scores zero. When ``total_budget_sec`` is set, each query instead
# gets ``remaining_time / remaining_queries`` (capped by the per-query budget, floored so a late
# query still gets a real solve). Queries that finish early hand their unused time to the ones
# after them. Off (``None``) for local development runs, on by default only in the organizer
# entry point -- see ``solve_script_with_harness.py``.
DEFAULT_TOTAL_BUDGET_SEC = 5 * 60 * 60.0
# Held back from the envelope for interpreter startup, WorldEnv/database load, worker spin-up and
# result writes -- work that runs inside the 5h but outside any solve budget. The sweep scheduler
# ends passes gracefully rather than being cut off mid-solve, so this only has to cover setup and
# straggler drain, not a whole query.
TOTAL_BUDGET_RESERVE_FRAC = 0.05
# A query solved with less than this is not worth budgeting for; below it the orchestrator's
# stage split degenerates and the fallback plan is the likely output either way.
MIN_QUERY_BUDGET_SEC = 20.0
# Warn-only guard: if set, print a warning (never raise/abort) when a single process's RSS grows
# by more than this many MB since its first solved query. Catches leaks (e.g. func_timeout thread
# accumulation on timeouts) during long single-process runs; unset by default (opt-in via env).
MAX_RSS_GROWTH_MB = float(os.environ.get("TPC_P2_MAX_RSS_MB", "0") or "0")
LLM_MODEL_PROBE_TIMEOUT_SEC = 5.0
_OPENAI_BASE_URL_ENV_VARS = (
    "TPC_P2_LLM_BASE_URL",
    "OPENAI_BASE_URL",
    "OPENAI_API_BASE",
    "SGLANG_BASE_URL",
)


def _default_method_for_split(split: str) -> str:
    """Keep the script default aligned with Makefile P2_METHOD."""
    return f"{DEFAULT_METHOD_PREFIX}{split}"


def _read_local_config(path: Path = DEFAULT_CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _first_env_value(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def _resolve_openai_api_key(cfg: dict) -> str:
    return str(
        cfg.get("api_key")
        or os.environ.get("TPC_P2_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or "EMPTY"
    )


def _probe_openai_model_id(base_url: str, *, api_key: str, timeout_sec: float = LLM_MODEL_PROBE_TIMEOUT_SEC) -> str | None:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/models",
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        status = getattr(response, "status", None)
        if status is None and hasattr(response, "getcode"):
            status = response.getcode()
        if status not in (None, 200):
            return None
        payload = json.load(response)

    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list) or not models:
        return None
    first = models[0]
    model_id = first.get("id") if isinstance(first, dict) else None
    return str(model_id) if model_id not in (None, "") else None


def _resolve_openai_model(cfg: dict, *, base_url: str | None, api_key: str) -> str | None:
    configured = cfg.get("model") or os.environ.get("TPC_P2_LLM_MODEL") or os.environ.get("OPENAI_MODEL")
    if configured not in (None, ""):
        return str(configured)
    if not base_url:
        return None
    return _probe_openai_model_id(base_url, api_key=api_key)


def _autodetect_openai_cfg() -> dict | None:
    base_url = _first_env_value(_OPENAI_BASE_URL_ENV_VARS)
    if not base_url:
        return None
    api_key = _resolve_openai_api_key({})
    try:
        model = _resolve_openai_model({}, base_url=base_url, api_key=api_key)
    except Exception:
        return None
    if not model:
        return None
    return {
        "backend": "openai",
        "backend_source": "autodetect",
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
    }


def _phase2_llm_config() -> dict:
    cfg: dict = {}
    backend_source = "none"

    local_cfg = _read_local_config()
    phase2_cfg = local_cfg.get("phase2") if isinstance(local_cfg, dict) else None
    if isinstance(phase2_cfg, dict):
        llm_cfg = phase2_cfg.get("llm")
        if isinstance(llm_cfg, dict):
            cfg.update({k: v for k, v in llm_cfg.items() if v not in (None, "")})
            if llm_cfg.get("backend") not in (None, ""):
                backend_source = "config"

    env_cfg = {
        "backend": os.environ.get("TPC_P2_LLM_BACKEND"),
        "fixtures_dir": os.environ.get("TPC_P2_LLM_FIXTURES"),
        "model": os.environ.get("TPC_P2_LLM_MODEL"),
        "base_url": os.environ.get("TPC_P2_LLM_BASE_URL"),
        "api_key_env": os.environ.get("TPC_P2_LLM_API_KEY_ENV"),
        "api_key": os.environ.get("TPC_P2_LLM_API_KEY"),
        "temperature": os.environ.get("TPC_P2_LLM_TEMPERATURE"),
        "max_tokens": os.environ.get("TPC_P2_LLM_MAX_TOKENS"),
    }
    cfg.update({k: v for k, v in env_cfg.items() if v not in (None, "")})
    if env_cfg["backend"] not in (None, ""):
        backend_source = "env-explicit"

    backend = str(cfg.get("backend") or "none").lower()
    cfg["backend"] = backend

    if backend == "deepinfra":
        cfg.setdefault("api_key_env", "DEEPINFRA_API_KEY")
        if "base_url" not in cfg and os.environ.get("DEEPINFRA_BASE_URL"):
            cfg["base_url"] = os.environ["DEEPINFRA_BASE_URL"]
        if "model" not in cfg and os.environ.get("DEEPINFRA_MODEL"):
            cfg["model"] = os.environ["DEEPINFRA_MODEL"]
    elif backend == "openai":
        base_url = str(cfg.get("base_url") or _first_env_value(_OPENAI_BASE_URL_ENV_VARS) or "") or None
        if base_url:
            cfg["base_url"] = base_url
        api_key = _resolve_openai_api_key(cfg)
        try:
            model = _resolve_openai_model(cfg, base_url=base_url, api_key=api_key)
        except Exception:
            model = None
        if model:
            cfg["model"] = model
            cfg["api_key"] = api_key
        else:
            cfg["backend"] = "none"
    elif backend_source != "env-explicit":
        autodetected = _autodetect_openai_cfg()
        if autodetected is not None:
            cfg.update(autodetected)
            backend_source = "autodetect"

    cfg["backend_source"] = backend_source
    return cfg


def _fmt_score(value) -> str:
    """Format a score for the per-uid log line; None (oracle-free query) prints as N/A rather
    than a misleading 0.0000."""
    return f"{float(value):.4f}" if value is not None else "N/A"


def _score_stats(values: list[float]) -> dict:
    vals = [float(v) for v in values]
    if not vals:
        return {"count": 0, "mean": 0.0, "min": 0.0, "max": 0.0, "std": 0.0}
    return {
        "count": len(vals),
        "mean": mean(vals),
        "min": min(vals),
        "max": max(vals),
        "std": pstdev(vals),
    }


def _aggregate_overall_scores(evaluations: list[dict]) -> dict:
    # overall_true is None (present key, no value) rather than absent for oracle-free queries
    # (see evaluate_one's has_oracle gate), so `.get(key, 0.0)` alone would not catch it.
    return {
        "overall_true": _score_stats([e.get("overall_true", 0.0) or 0.0 for e in evaluations]),
        "overall_parsed": _score_stats([e.get("overall_parsed", 0.0) or 0.0 for e in evaluations]),
    }


def current_rss_mb() -> float | None:
    """This process's resident set size in MB, or ``None`` when psutil is not installed."""
    if psutil is None:
        return None
    return psutil.Process().memory_info().rss / (1024 * 1024)


def resolve_total_budget_sec(explicit: float | None = None) -> float | None:
    """Resolve the whole-run wall-clock envelope, or ``None`` when it is disabled.

    Precedence: explicit argument, then ``TPC_P2_TOTAL_BUDGET_SEC``. A value ``<= 0`` from either
    source disables the envelope (back to a fixed per-query budget), which is what every local
    development run wants.
    """
    if explicit is None:
        raw = os.environ.get("TPC_P2_TOTAL_BUDGET_SEC")
        if raw in (None, ""):
            return None
        try:
            explicit = float(raw)
        except ValueError:
            return None
    return float(explicit) if float(explicit) > 0 else None


def query_budget_sec(
    *,
    cap_sec: float,
    remaining_sec: float,
    remaining_queries: int,
    min_sec: float = MIN_QUERY_BUDGET_SEC,
) -> float:
    """Per-query budget under a shared wall-clock envelope.

    Even split of what is left over what is left to do, capped by the per-query budget so a run
    that is ahead of schedule does not spend hours on one query, and floored at ``min_sec`` so a
    run that is behind schedule still attempts a real solve instead of degrading to fallbacks.
    """
    if remaining_queries <= 0:
        return float(cap_sec)
    fair_share = float(remaining_sec) / float(remaining_queries)
    return max(float(min_sec), min(float(cap_sec), fair_share))


# --- P2: per-attempt telemetry ledger -------------------------------------------------------
# `on_result` in `run_sweeps_split` used to write `work_root/<uid>/telemetry.json` on *every*
# attempt, so each later pass's write silently overwrote the previous pass's record -- reading it
# after a completed run measures only the winners (roadmap diagnosis §3's sampling note). This
# keeps that file as the latest (other tooling already reads it) and additionally appends one
# line per attempt to `work_root/<uid>/attempts.jsonl`, so the full attempt history survives.
ATTEMPT_LEDGER_FILENAME = "attempts.jsonl"


def attempt_ledger_record(
    *,
    pass_index: int | None,
    pass_kind: str | None,
    seed_salt: object = None,
    budget_sec: float | None,
    wall_sec: float | None,
    telemetry: dict,
    self_score: dict | None,
    kept: bool,
) -> dict:
    """One JSON-serializable record for a single solve attempt on one query.

    Pulled from ``telemetry``/``self_score`` where those already carry the value (solver search
    telemetry, pass kind) rather than re-deriving it, so the ledger can never disagree with the
    telemetry file written alongside it.
    """
    search_telemetry = telemetry.get("search_telemetry") or {}
    return {
        "pass_index": pass_index,
        "pass_kind": pass_kind or telemetry.get("pass_kind"),
        "seed_salt": seed_salt,
        "budget_sec": budget_sec,
        "wall_sec": wall_sec,
        "restarts_used": search_telemetry.get("restarts_used"),
        "stop_reason": search_telemetry.get("stop_reason"),
        "candidates_evaluated": search_telemetry.get("candidates_evaluated"),
        "best_found_at_restart": search_telemetry.get("best_found_at_restart"),
        "self_score": self_score,
        "kept": bool(kept),
    }


def append_attempt_ledger(run_dir: Path, record: dict) -> None:
    """Append one attempt record as a JSON line to ``run_dir/attempts.jsonl``.

    Append-only and additive: this never touches ``telemetry.json`` (still written separately as
    "the latest attempt", which existing tooling reads), never touches which plan gets written to
    ``results/<method>/<uid>.json``, and never influences keep-best or pass selection -- it is
    observation only, called after those decisions are already made.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, default=str)
    with (run_dir / ATTEMPT_LEDGER_FILENAME).open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_attempt_ledger(run_dir: Path) -> list[dict]:
    """Read every attempt record for one query, oldest first. Missing file -> ``[]``."""
    path = run_dir / ATTEMPT_LEDGER_FILENAME
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def _load_queries(split: str, lang: str = "en"):
    """Load queries with oracle fields present when the split has them (evaluation only).

    Formal Phase 2 data carries no ``hard_logic*`` field at all; ``oracle_translation=True`` only
    means "do not strip what is there", so this is the same call either way.
    """
    _, query_ids, query_data = _load_queries_resolving_lang(split, lang)
    return query_ids, query_data


def _load_queries_resolving_lang(split: str, lang: str = "en"):
    """``_load_queries`` plus the language the split actually resolved under.

    ``run_split`` needs the second value: a split that only exists in the *other* language tree
    must also build its ``WorldEnv`` and evaluators in that language, or the run grounds English
    plans against Chinese queries. See ``hb.load_queries_with_lang``.
    """
    return hb.load_queries_with_lang(split, lang)


def resolve_llm_client_and_flags():
    """Build the LLM client + acceptance-gate flags exactly as ``run_split`` does.

    Factored out so a caller running a single ad hoc query (e.g. ``scripts/run_query.py``) can
    reproduce the same parse-time flags used inside a real ``run_split`` invocation -- e.g. to
    diff the resulting parse against an oracle with ``parser_vs_oracle.compute_query_diff``.
    """
    llm_cfg = _phase2_llm_config()
    llm_client = p2_llm.build_llm_client(llm_cfg)
    llm_backend_source = str(llm_cfg.get("backend_source") or "none")
    setattr(llm_client, "backend_source", llm_backend_source)

    # Acceptance gate is OR-correct by default: enable disjunctive branch generation unless the
    # operator explicitly overrides TPC_P2_DISJUNCTION. The library default (Flags()) stays off, so
    # the deterministic byte-identical invariant tests are unaffected.
    flags = orch.Flags.from_env()
    flags.llm_backend = getattr(llm_client, "backend", "none")
    if "TPC_P2_DISJUNCTION" not in os.environ:
        flags.disjunction = True
    # Dynamic budget reallocation is a pure timing win (gives Stage 2 whatever Stage 1 -- and
    # Stage 3 when off -- didn't use) with a floor at the static split, so default it on too.
    if "TPC_P2_DYNAMIC_BUDGET" not in os.environ:
        flags.dynamic_budget = True
    # TPC_P2_LLM_PARSE stays off by default even when a real backend is configured -- an explicit
    # recorded decision (roadmap W8), not an auto-enable like disjunction/dynamic_budget/
    # entity_resolution above. `flags.llm_parse` already came from Flags.from_env() above (off
    # unless TPC_P2_LLM_PARSE is explicitly set), so there is deliberately no auto-enable branch
    # here. The last paired same-SHA screen on current head was RED for audit-on vs. parse-off
    # (n=10, 60s, DeepInfra timeout 6s): parse off FPR 30.0/overall_true 54.48/1 timeout vs. audit
    # on FPR 20.0/overall_true 45.54/2 timeouts -- see docs/tpc_phase2_roadmap.md's "Current status
    # snapshot". An explicit off is also safer than an auto-enable that fires only when an
    # endpoint happens to be reachable, since it makes the organizer run behave the same as every
    # local run. An operator who wants the audit on (e.g. to re-screen against a reachable
    # endpoint) still can with an explicit TPC_P2_LLM_PARSE=1 override.
    # Deterministic entity resolution is pure recall/precision cleanup against the committed POI
    # catalogs. It has no LLM or network dependency, so default it on with disjunction and dynamic
    # budget unless the operator overrides TPC_P2_ENTITY_RESOLUTION. Library Flags() remains off
    # for byte-identical invariant tests.
    if "TPC_P2_ENTITY_RESOLUTION" not in os.environ:
        flags.entity_resolution = True

    return llm_client, flags


def apply_deterministic_solver_defaults():
    """Promote gate-cleared deterministic solver features to harness-default-on.

    Same promotion pattern ``resolve_llm_client_and_flags`` uses for disjunction/dynamic_budget/
    entity_resolution: set the env default the ``TPCAgent`` reads, *unless the operator explicitly
    overrides it*, so the library default (the unset env var) -- and the byte-identical opt-in unit
    tests that assert it -- stay unchanged. These are deterministic (no LLM, no network) passes with
    a committed ``900 s`` gate, so this is the sanctioned "explicit measured configuration" path.

    - ``TPC_PIN_TIMED_WINDOWS=1``: the ``900 s`` ``familiar_100_val`` gate (roadmap step 1, rows
      ``20260723T200723Z`` floor / ``20260724T071840Z`` pin) cleared cleanly -- e2e continuous
      ``43.72 -> 48.04``, timeouts ``0 -> 0``. The earlier ``300 s`` timeout regression that blocked
      it was a budget-boundary artifact, not a real cost.
    - ``TPC_SOLVE_CONVERGE_PATIENCE=15``: paired with pin (row ``20260724T192503Z``) it held quality
      flat (e2e continuous ``47.98``) while cutting solve ``p50`` ``366 s -> 265 s`` (below even the
      floor's ``337 s``) -- reclaiming wall-clock and making the submission more robust to an
      organizer per-query timeout shorter than the assumed ``900 s``.
    - ``TPC_COMMONSENSE_FIRST=1``: the commonsense-first finalization policy (relaxed repair commit
      rule for unaccepted plans + the ``best_cs`` bucket in ``_solve``; see
      ``docs/archive/agents/final_night_commonsense_first.md``). ``eval_tpc`` scores C-LPR as the
      *conditional* logical micro, so an emitted plan that fails commonsense forfeits its whole
      logical partial credit (weight ``0.25``) and its EPR-macro point (``0.10``). Paired same-SHA
      end-to-end screen (``results/phase2_baselines/screens/20260726_e2e_n40_b120_commonsense_first``,
      ``familiar_100_val`` fold 0, ``n=40``, ``120 s``, ``parallel=7``, LLM backend ``none``):
      ``overall_true`` ``51.34 -> 60.98``, commonsense pass ``30/40 -> 40/40``, EPR-macro
      ``75 -> 100``, C-LPR ``67.35 -> 89.95``, FPR ``32.5 -> 35.0``, ``all_pass`` ``13 -> 14``, zero
      parse failures. ``logical_micro`` is unchanged at ``89.95``, which is the proof of mechanism:
      the gain is entirely the commonsense gate releasing logical credit the solver had already
      earned. **Caveat:** timeouts rose ``4 -> 7`` at that deliberately tight budget (baseline solve
      ``p50`` is already ``108 s`` of ``120 s``), all recovered with ``used_fallback=0`` -- the same
      budget-boundary shape ``TPC_PIN_TIMED_WINDOWS`` showed at ``300 s`` and cleared at ``900 s``
      (``p50 265 s`` there). The probe cost is bounded proportionally
      (``TPC_CS_CHECK_TIME_FRAC=0.08`` of the solve budget, ``TPC_CS_CHECK_BUDGET=60``
      confirmations), and ``docs/archive/agents/final_night_eval_commands.md`` carries the ``900 s`` pinned
      confirmation rows.
    - ``TPC_WINDOW_ANCHOR=1``: the window-anchored day relayout (roadmap P1). Promoted on **R8**, the
      first *whole-run* row to move FPR by more than a point: ``results/phase2_baselines/full_runs/
      20260805T123142Z.json`` scored ``overall 63.58`` / ``FPR 43.0`` / ``constraints_ok 46/100``
      against the R7 baseline's ``57.75`` / ``32.0`` / ``36/100`` (rows ``20260805T081535Z``,
      ``20260805T094549Z``, ``20260805T110654Z`` -- three repeats, **bit-for-bit identical**, so the
      ``+5.83`` overall and ``+11.0`` FPR are measured against a zero-variance floor and cannot be
      seed noise). Same box, same ``18000 s`` envelope, same ``workers 3``, ``evaluator_parity
      c89cfca`` on both sides. It also cost nothing in wall-clock (``4733 s`` vs ``4786 s``, both
      ~``26%`` of the envelope) and no robustness (``empty_plans 0/100``), and it matches the paired
      ``n=80``/``90 s`` screens that queued it (predicted ``FPR 32.5 -> 42.5``, measured ``32.0 ->
      43.0``). Deterministic and acceptance-gated like the passes above: every relayout is trialed on
      a deepcopy and committed only if the full checker still accepts and the preference key does not
      regress.
    - ``TPC_WINDOW_PUSH=1`` / ``TPC_WINDOW_INSERT=1`` (roadmap P8/P9): the bounded local window push
      (retime/shorten the residual after ``TPC_WINDOW_ANCHOR``) and the absent-timed-visit-POI
      insertion pass. Promoted on **R14**, the P8/P9 whole-run gate:
      ``results/phase2_baselines/full_runs/20260806T052925Z.json`` scored ``overall
      64.13167839953107`` (``+0.5471`` over the ``TPC_WINDOW_ANCHOR``-only baseline) / ``FPR 44.0``
      (``+1.0``) / ``empty_plans 0/100``, same box/envelope/workers/``evaluator_parity`` as the
      baseline it is measured against. Gated as a stack (both flags together), matching their paired
      screens (``results/phase2_baselines/screens/20260805_e2e_n80_b90_window_push_insert``):
      ``FPR 42.5 -> 45.0``, ``overall_true 63.130 -> 64.422``, ``all_pass 34 -> 36``, zero timeouts,
      fallbacks or parse regressions. **Two caveats, carried forward rather than dropped:**
      ``constraints_ok`` did **not** move on R14 (``46/100``, identical to the
      ``TPC_WINDOW_ANCHOR``-only baseline) -- the gain is one FPR point plus preference terms, not a
      newly passing query -- and the paired screen *over*-predicted the full run on all three axes,
      the opposite direction from R8's screen. ``TPC_WINDOW_PUSH_MAX_MIN`` (the push's bound) stays a
      candidate, unset here: R14 measured it at its code default (30 min), and it is a bound on the
      pass rather than a pass of its own.

    Must run *before* ``make_tpcagent_solve_fn`` builds the agent: ``TPCAgent.__init__`` reads
    ``TPC_SOLVE_CONVERGE_PATIENCE`` eagerly (``TPC_PIN_TIMED_WINDOWS``, ``TPC_WINDOW_ANCHOR``,
    ``TPC_WINDOW_PUSH`` and ``TPC_WINDOW_INSERT`` are read lazily at pack time, but all are set here
    for clarity)."""
    if "TPC_PIN_TIMED_WINDOWS" not in os.environ:
        os.environ["TPC_PIN_TIMED_WINDOWS"] = "1"
    if "TPC_SOLVE_CONVERGE_PATIENCE" not in os.environ:
        os.environ["TPC_SOLVE_CONVERGE_PATIENCE"] = "15"
    if "TPC_COMMONSENSE_FIRST" not in os.environ:
        os.environ["TPC_COMMONSENSE_FIRST"] = "1"
    # Only meaningful with TPC_PIN_TIMED_WINDOWS above, which is what puts the named POI in the plan
    # for the relayout to anchor. R8 measured the pair, so the pair is what ships.
    if "TPC_WINDOW_ANCHOR" not in os.environ:
        os.environ["TPC_WINDOW_ANCHOR"] = "1"
    # R14 gated TPC_WINDOW_PUSH and TPC_WINDOW_INSERT as a stack on top of TPC_WINDOW_ANCHOR above --
    # the pair is what R14 measured, so the pair is what ships.
    if "TPC_WINDOW_PUSH" not in os.environ:
        os.environ["TPC_WINDOW_PUSH"] = "1"
    if "TPC_WINDOW_INSERT" not in os.environ:
        os.environ["TPC_WINDOW_INSERT"] = "1"


def run_sweeps_split(
    *,
    split: str,
    method: str,
    selected: list[str],
    query_data: dict,
    deadline: float,
    run_start: float,
    budget_sec: float | None,
    total_budget_sec: float,
    lang: str,
    workers: int | None,
    resume: bool,
    result_method_dir: Path,
    work_root: Path,
) -> dict:
    """Run a split under a whole-run wall-clock envelope, constraint-first and in parallel.

    Three properties matter more than throughput here, and each costs something:

    - **A valid answer exists at every instant.** Every query gets a schema-valid fallback plan on
      disk *before* any solving starts, so a run cut off at any point -- including one killed
      before its first solve returns -- still submits a complete set of plans.
    - **Nothing ever regresses.** Each result is scored oracle-free and written only if it beats
      what is already there, so later passes can only improve the split.
    - **Nothing runs past the deadline.** The scheduler stops starting work it cannot finish, and
      this function does no post-deadline work (evaluation is a separate step, see
      ``scripts/phase2_full_run.py``) -- the organizers' clock covers the whole process.

    ``budget_sec`` here is ``None`` unless an operator explicitly passed ``--budget-sec`` alongside
    ``--total-budget-sec`` (roadmap P4). The shipped harness invocation never does -- the organizers'
    exact entry point takes no other flags -- so by default the sweep scheduler's own per-query cap,
    ``sweeps.DEFAULT_MAX_QUERY_SEC`` (900s), governs a repair/polish pass, not the unrelated 300s
    per-query *development*-gate default this function used to inherit by accident (it silently
    capped every whole-run pass at 300s and made ``MIN_BUDGET_GROWTH``'s re-entry threshold, 375s,
    unreachable -- see the roadmap item for the full mechanism). An explicit ``--budget-sec`` still
    overrides ``max_query_sec`` here too, since ``scripts/phase2_quick_eval.py --mode whole-run``
    relies on exactly that to keep its calibrated per-pass timing.
    """
    from chinatravel.agent.phase2 import normalize, selfscore, sweeps

    # Parse once per query, here in the parent, through the same canonical path the solver uses
    # (normalize.parse_to_ir -> normalize.ir_to_solver_variants) instead of the coarser, single-
    # variant selfscore.derive_parsed_constraints. That parse used to disagree with the solver's
    # own on any disjunctive or named-entity query -- see roadmap P10 -- because the two ran two
    # different parsers. Using the exact same ``flags`` object the workers build
    # (``resolve_llm_client_and_flags``, which ``sweeps.init_worker`` also calls) means the two
    # cannot diverge by configuration either. ``llm_client=None`` is deliberate: the parent must
    # stay zero-LLM even when a backend is configured, and ``flags.llm_parse`` is off by default.
    _llm_client, flags = resolve_llm_client_and_flags()
    workers = int(workers) if workers else sweeps.default_workers()
    if flags.llm_repair_loop:
        # Roadmap P6 item 5: "throttle to at most eight concurrent requests for organizer parity".
        # Each worker process makes at most one LLM call at a time (Stage 3 is synchronous within
        # a query's solve), so the worker pool size *is* the concurrent-request ceiling -- clamping
        # it here needs no separate cross-process semaphore. Only applies when this flag is on;
        # every other whole-run configuration keeps its full worker count.
        workers = min(workers, 8)
    visible: dict[str, dict] = {}
    variants: dict[str, list[dict]] = {}
    # Roadmap P13: which uids the parent parse degraded for. Surfaced in the run summary below --
    # previously this was discarded, so a run could not tell you which queries (if any) fell back
    # to the per-worker re-parse in orchestrator.solve_phase2.
    parent_parse_failed_uids: list[str] = []
    # Roadmap P17(a), opt-in: computed once per query here (never per attempt), from the same
    # visible text + parsed variants the rest of this loop already has -- oracle-free by
    # construction, since neither input is hard_logic*.
    coverage_unknown_flag = _coverage_unknown_enabled()
    coverage_unknown: dict[str, bool] = {}
    if coverage_unknown_flag:
        from chinatravel.agent.phase2 import coverage_signal
    for quid in selected:
        full_query = query_data[quid]
        full_query.setdefault("uid", quid)
        visible[quid] = hb.visible_query(full_query)
        try:
            ir = normalize.parse_to_ir(visible[quid], llm_client=None, flags=flags)
            variants[quid] = normalize.ir_to_solver_variants(
                ir, visible[quid], env=None, flags=flags
            )
        except Exception:
            # A parse failure must not take the run down -- degrade to no variants ([]), exactly
            # as the per-query orchestrator.solve_phase2 path degrades on its own parse failure.
            # orchestrator.solve_phase2 treats variants=[] the same as variants=None (roadmap
            # P13: it tests truthiness, not identity) and re-parses independently there, so this
            # query still solves and scores against a constraint set -- just not the same object
            # on both sides, the guarantee this parent-side parse exists to provide.
            variants[quid] = []
            parent_parse_failed_uids.append(quid)
        if coverage_unknown_flag:
            text = str(visible[quid].get("nature_language") or "")
            coverage_unknown[quid] = bool(
                coverage_signal.uncovered_mentions(text, variants[quid])
            )

    # Insurance first: a complete, schema-valid submission before a single query is solved.
    fallbacks_written = 0
    for quid in selected:
        result_path = result_method_dir / f"{quid}.json"
        if not result_path.exists():
            hb.write_json(result_path, fallback_mod.minimal_plan(visible[quid]))
            fallbacks_written += 1

    # Any real plan already on disk is an incumbent to beat, whether or not --resume was passed:
    # "never regress a query" has to hold across runs too, and the only way to honour it is to
    # know what the existing plan scores. Starting clean is `--fresh` (delete the directory), not
    # "overwrite whatever is there with whatever comes out first". Costs nothing on the organizer
    # run, where the directory is empty.
    best: dict[str, selfscore.PlanScore] = {}
    for quid in selected:
        result_path = result_method_dir / f"{quid}.json"
        try:
            plan = hb.read_json(result_path)
        except Exception:
            continue
        if not isinstance(plan, dict) or not plan.get("itinerary"):
            continue  # a bare fallback is not an incumbent worth defending
        best[quid] = selfscore.score_plan(
            plan, visible[quid], variants=variants.get(quid), lang=lang, uid=quid
        )

    def on_result(
        quid: str, plan: dict, score: selfscore.PlanScore, telemetry: dict, improved: bool
    ) -> None:
        # Telemetry for every attempt (a query retried and never improved is a finding); the plan
        # only when it beats the incumbent, so a pass can never regress the split.
        telemetry["kept"] = improved
        run_dir = work_root / quid
        hb.write_json(run_dir / "telemetry.json", telemetry)
        # P2: append this attempt to the per-uid ledger too, so the full attempt history survives
        # a run even though telemetry.json above still only ever holds the latest attempt. Purely
        # additive -- this cannot change which plan is kept (`improved` was already decided by
        # the caller) or which pass runs next.
        append_attempt_ledger(
            run_dir,
            attempt_ledger_record(
                pass_index=telemetry.get("pass_index"),
                pass_kind=telemetry.get("pass_kind"),
                seed_salt=telemetry.get("seed_salt"),
                budget_sec=telemetry.get("budget_sec"),
                wall_sec=telemetry.get("wall_sec"),
                telemetry=telemetry,
                self_score=telemetry.get("self_score"),
                kept=improved,
            ),
        )
        if not improved:
            return
        hb.write_json(result_method_dir / f"{quid}.json", plan)
        hb.write_json(run_dir / "output.json", plan)

    # roadmap P4: only an *explicit* --budget-sec overrides the sweep scheduler's own per-query
    # cap. Omitted (the shipped harness path), the scheduler's intended sweeps.DEFAULT_MAX_QUERY_SEC
    # (900s) applies via SweepConfig's own default -- not this function's unrelated 300s
    # development-gate default, which used to reach here whether or not an operator asked for it.
    config_kwargs = dict(workers=workers, lang=lang)
    if budget_sec is not None:
        config_kwargs["max_query_sec"] = float(budget_sec)
    config = sweeps.SweepConfig(**config_kwargs).apply_env_overrides()
    print(
        f"[sweep] {len(selected)} queries, {workers} worker(s), "
        f"{(deadline - time.monotonic()) / 60:.1f} min usable of a "
        f"{total_budget_sec / 3600:.2f} h envelope, per-query cap {config.max_query_sec:.0f}s"
        + ("" if budget_sec is not None else " (sweep default, no --budget-sec override)")
    )
    sweep_summary = sweeps.run_sweeps(
        uids=selected,
        queries=visible,
        deadline=deadline,
        config=config,
        on_result=on_result,
        best=best,
        variants=variants,
        coverage_unknown=coverage_unknown if coverage_unknown_flag else None,
    )

    summary = {
        "split": split,
        "method": method,
        "strategy": "sweeps",
        # The cap actually in force (roadmap P4): equals the operator's --budget-sec when given,
        # otherwise sweeps.DEFAULT_MAX_QUERY_SEC (900s) via SweepConfig's own default -- a row must
        # state its own configuration, not the possibly-irrelevant 300s development-gate default.
        "budget_sec": config.max_query_sec,
        "budget_sec_explicit": budget_sec,
        "total_budget_sec": total_budget_sec,
        "elapsed_sec": time.monotonic() - run_start,
        "selected": len(selected),
        "resume_requested": resume,
        "incumbents_scored": len(best),
        "fallbacks_prewritten": fallbacks_written,
        "parent_parse_failed_uids": parent_parse_failed_uids,
        # Roadmap P17(a): telemetry for the coverage signal, off (empty) unless
        # TPC_P2_COVERAGE_UNKNOWN=1 -- a row has to state whether/how much this fired.
        "coverage_unknown_flag": coverage_unknown_flag,
        "coverage_unknown_uids": sorted(uid for uid, flagged in coverage_unknown.items() if flagged),
        "uids": list(selected),
        **sweep_summary,
    }
    hb.write_json(work_root / f"{split}_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return summary


def run_split(
    split: str,
    *,
    method: str | None = None,
    limit: int | None = None,
    uid: str | None = None,
    uids: list[str] | None = None,
    resume: bool = False,
    budget_sec: float | None = None,
    total_budget_sec: float | None = None,
    start_monotonic: float | None = None,
    workers: int | None = None,
    lang: str = "en",
    work_dir: str | None = None,
    results_dir: str | None = None,
    env=None,
    solve_fn=None,
    queries: dict | None = None,
) -> dict:
    """Run the Phase 2 pipeline over a split. Returns a summary dict.

    ``queries``, when given, is used verbatim as ``{uid: query_dict}`` instead of loading
    ``split`` from the on-disk dataset -- lets a caller (e.g. a single-query CLI) feed an
    ad hoc or file-loaded query through the exact same solve/write/evaluate path used for
    real splits. ``split`` still becomes a label on the written results/evaluation.

    ``budget_sec`` is the per-query budget. ``total_budget_sec``, when set, additionally caps the
    *whole* run: each query then gets the smaller of ``budget_sec`` and its fair share of the time
    left (see ``query_budget_sec``). ``start_monotonic`` lets a caller start that clock at process
    start rather than here, so interpreter and database load count against the envelope.
    """
    method = method or _default_method_for_split(split)
    # Resolved only for the plain per-query loop below (roadmap P4): the sweep branch needs to
    # tell "operator explicitly passed --budget-sec" apart from "nothing was passed", so it is
    # handed the raw, possibly-None value instead.
    budget_sec_explicit = budget_sec
    run_start = float(start_monotonic if start_monotonic is not None else time.monotonic())
    deadline = (
        run_start + float(total_budget_sec) * (1.0 - TOTAL_BUDGET_RESERVE_FRAC)
        if total_budget_sec
        else None
    )
    results_root = Path(results_dir) if results_dir else PROJECT_ROOT / "results"
    work_root = Path(work_dir) if work_dir else PROJECT_ROOT / "agent_env" / "runs" / method
    result_method_dir = results_root / method
    result_method_dir.mkdir(parents=True, exist_ok=True)

    if queries is not None:
        query_ids, query_data = list(queries.keys()), queries
    else:
        # The resolved language, not the requested one: a split that only exists in the other
        # language tree must be solved and evaluated in that language (see the helper's docstring).
        lang, query_ids, query_data = _load_queries_resolving_lang(split, lang)
    if uids is not None:
        missing = [u for u in uids if u not in query_data]
        if missing:
            raise RuntimeError(f"{len(missing)} uid(s) not in split {split!r}, e.g. {missing[:3]}")
        selected = list(uids)
    elif uid:
        if uid not in query_data:
            raise RuntimeError(f"uid {uid!r} not in split {split!r}")
        selected = [uid]
    else:
        selected = query_ids[: int(limit)] if limit else query_ids

    if deadline is not None and solve_fn is None:
        # A whole-run envelope is exactly the situation the sweep scheduler exists for: it decides
        # what to work on next from what is already solved, instead of walking the split once.
        return run_sweeps_split(
            split=split,
            method=method,
            selected=selected,
            query_data=query_data,
            deadline=deadline,
            run_start=run_start,
            budget_sec=budget_sec_explicit,
            total_budget_sec=float(total_budget_sec),
            lang=lang,
            workers=workers,
            resume=resume,
            result_method_dir=result_method_dir,
            work_root=work_root,
        )

    # The plain per-query loop below: DEFAULT_BUDGET_SEC (300s) is this path's own default, same
    # as always -- only the sweep branch above needed the None distinction.
    budget_sec = float(budget_sec_explicit if budget_sec_explicit is not None else DEFAULT_BUDGET_SEC)

    # Build the deterministic TPCAgent-backed solve function once (unless injected).
    if solve_fn is None:
        # Promote the gate-cleared deterministic solver features (timed-window pinning + early
        # convergence) to harness-default-on -- but only when we build the agent ourselves. It runs
        # before make_tpcagent_solve_fn, since TPCAgent.__init__ reads TPC_SOLVE_CONVERGE_PATIENCE
        # eagerly. Gated on ``solve_fn is None`` so an injected solve_fn (unit tests / embedded
        # callers) never triggers a process-global env mutation the caller didn't ask for. An
        # explicit operator override of either env var is still respected.
        apply_deterministic_solver_defaults()
        if env is None:
            from chinatravel.environment.world_env import WorldEnv

            env = WorldEnv(lang=lang)
        solve_fn = orch.make_tpcagent_solve_fn(env, lang=lang)

    llm_client, flags = resolve_llm_client_and_flags()

    done_uids: list[str] = []
    skipped = 0
    parse_failures = 0
    llm_parse_attempts = 0
    llm_fixture_missing = 0
    llm_parse_failed = 0
    solved_evaluations: list[dict] = []
    rss_baseline_mb: float | None = None

    for idx, quid in enumerate(selected, start=1):
        result_path = result_method_dir / f"{quid}.json"
        if resume and result_path.exists():
            skipped += 1
            done_uids.append(quid)
            continue

        full_query = query_data[quid]
        full_query.setdefault("uid", quid)
        visible = hb.visible_query(full_query)  # oracle hidden from the agent

        if deadline is None:
            query_budget = budget_sec
        else:
            query_budget = query_budget_sec(
                cap_sec=budget_sec,
                remaining_sec=deadline - time.monotonic(),
                remaining_queries=len(selected) - idx + 1,
            )

        plan, telemetry = orch.solve_phase2(
            visible,
            env=env,
            llm_client=llm_client,
            budget_sec=query_budget,
            solve_fn=solve_fn,
            flags=flags,
        )
        telemetry["llm_backend_source"] = getattr(llm_client, "backend_source", "none")
        if deadline is not None:
            telemetry["total_budget_sec"] = float(total_budget_sec)
            telemetry["total_budget_remaining_sec"] = deadline - time.monotonic()

        hb.write_json(result_path, plan)

        rss_mb = current_rss_mb()
        telemetry["rss_mb"] = rss_mb
        if MAX_RSS_GROWTH_MB > 0 and rss_mb is not None:
            if rss_baseline_mb is None:
                rss_baseline_mb = rss_mb
            elif rss_mb - rss_baseline_mb > MAX_RSS_GROWTH_MB:
                print(
                    f"[rss-warn] {quid}: RSS grew {rss_mb - rss_baseline_mb:.0f} MB since first "
                    f"query ({rss_baseline_mb:.0f} -> {rss_mb:.0f} MB), exceeds "
                    f"TPC_P2_MAX_RSS_MB={MAX_RSS_GROWTH_MB:.0f} (warn-only, continuing)"
                )

        run_dir = work_root / quid
        hb.write_json(run_dir / "output.json", plan)
        hb.write_json(run_dir / "telemetry.json", telemetry)
        try:
            evaluation = hb.evaluate_one(split, quid, full_query, plan, lang)
        except Exception as exc:  # never let evaluation crash the batch
            evaluation = {"uid": quid, "error": f"evaluation: {exc}", "all_pass": False}
        hb.write_json(run_dir / "evaluation.json", evaluation)
        solved_evaluations.append(evaluation)

        if telemetry.get("used_fallback"):
            parse_failures += 0  # fallback != parse failure; kept for future attribution
        if telemetry.get("flags", {}).get("llm_parse"):
            llm_parse_attempts += 1
            err = str(telemetry.get("error") or "")
            if "No fixture for key" in err:
                llm_fixture_missing += 1
            if telemetry.get("llm_parse_error"):
                llm_parse_failed += 1
        done_uids.append(quid)
        print(
            f"[{idx}/{len(selected)}] {quid} "
            f"valid={telemetry.get('valid_output')} fallback={telemetry.get('used_fallback')} "
            f"budget_sec={query_budget:.0f} "
            f"solve_sec={telemetry.get('stage_sec', {}).get('solve', 0):.2f} "
            f"overall_true={_fmt_score(evaluation.get('overall_true'))} "
            f"overall_parsed={_fmt_score(evaluation.get('overall_parsed'))}"
        )

    solved_overall_stats = _aggregate_overall_scores(solved_evaluations)
    print(
        "[overall/solved_this_run] "
        f"true(mean/min/max/std)="
        f"{solved_overall_stats['overall_true']['mean']:.4f}/"
        f"{solved_overall_stats['overall_true']['min']:.4f}/"
        f"{solved_overall_stats['overall_true']['max']:.4f}/"
        f"{solved_overall_stats['overall_true']['std']:.4f} "
        f"parsed(mean/min/max/std)="
        f"{solved_overall_stats['overall_parsed']['mean']:.4f}/"
        f"{solved_overall_stats['overall_parsed']['min']:.4f}/"
        f"{solved_overall_stats['overall_parsed']['max']:.4f}/"
        f"{solved_overall_stats['overall_parsed']['std']:.4f}"
    )

    resume_all_selected_stats = None
    if resume:
        all_selected_evals: list[dict] = []
        for quid in selected:
            eval_path = work_root / quid / "evaluation.json"
            if eval_path.exists():
                try:
                    all_selected_evals.append(hb.read_json(eval_path))
                    continue
                except Exception:
                    pass

            result_path = result_method_dir / f"{quid}.json"
            if not result_path.exists():
                continue
            full_query = query_data.get(quid)
            if full_query is None:
                continue
            full_query.setdefault("uid", quid)
            try:
                plan = hb.read_json(result_path)
                evaluation = hb.evaluate_one(split, quid, full_query, plan, lang)
                hb.write_json(eval_path, evaluation)
                all_selected_evals.append(evaluation)
            except Exception:
                continue

        resume_all_selected_stats = _aggregate_overall_scores(all_selected_evals)
        print(
            "[overall/resume_all_selected] "
            f"true(mean/min/max/std)="
            f"{resume_all_selected_stats['overall_true']['mean']:.4f}/"
            f"{resume_all_selected_stats['overall_true']['min']:.4f}/"
            f"{resume_all_selected_stats['overall_true']['max']:.4f}/"
            f"{resume_all_selected_stats['overall_true']['std']:.4f} "
            f"parsed(mean/min/max/std)="
            f"{resume_all_selected_stats['overall_parsed']['mean']:.4f}/"
            f"{resume_all_selected_stats['overall_parsed']['min']:.4f}/"
            f"{resume_all_selected_stats['overall_parsed']['max']:.4f}/"
            f"{resume_all_selected_stats['overall_parsed']['std']:.4f}"
        )

    summary = {
        "split": split,
        "method": method,
        "budget_sec": budget_sec,
        "total_budget_sec": float(total_budget_sec) if total_budget_sec else None,
        "elapsed_sec": time.monotonic() - run_start,
        "llm_backend": getattr(llm_client, "backend", "none"),
        "llm_backend_source": getattr(llm_client, "backend_source", "none"),
        "llm_parse_attempts": llm_parse_attempts,
        "llm_fixture_missing": llm_fixture_missing,
        "llm_parse_failed": llm_parse_failed,
        "selected": len(selected),
        "skipped": skipped,
        "uids": done_uids,
        "overall_solved_this_run": solved_overall_stats,
    }
    if resume_all_selected_stats is not None:
        summary["overall_resume_all_selected"] = resume_all_selected_stats
    summary_path = work_root / f"{split}_summary.json"
    hb.write_json(summary_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", default="tpc_phase2_val")
    p.add_argument("--uid", default=None)
    p.add_argument(
        "--uids-file",
        default=None,
        help="Path to a file with one uid per line (blank lines ignored); feeds run_split's "
        "uids= param, overriding --limit/--uid. Used by rehearse_phase2.py's chunked subprocess "
        "workers to bound each process to a small uid set.",
    )
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--method", default=None)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--budget-sec", type=float, default=None, help="Per-query budget in seconds.")
    p.add_argument(
        "--total-budget-sec",
        type=float,
        default=None,
        help="Whole-run wall-clock envelope in seconds; each query gets the smaller of "
        "--budget-sec and its fair share of the time left. <=0 disables (the local default). "
        "Also settable via TPC_P2_TOTAL_BUDGET_SEC.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Worker processes for the sweep scheduler (whole-run-envelope runs only). "
        "Default: CPU count - 1. Also settable via TPC_P2_WORKERS.",
    )
    p.add_argument("--lang", default="en", choices=["en", "zh"])
    p.add_argument("--work-dir", default=None)
    p.add_argument("--results-dir", default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    method = args.method or _default_method_for_split(args.split)
    uids = None
    if args.uids_file:
        uids = [
            line.strip()
            for line in Path(args.uids_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    summary = run_split(
        args.split,
        method=method,
        limit=args.limit,
        uid=args.uid,
        uids=uids,
        resume=args.resume,
        budget_sec=args.budget_sec,
        total_budget_sec=resolve_total_budget_sec(args.total_budget_sec),
        workers=args.workers,
        lang=args.lang,
        work_dir=args.work_dir,
        results_dir=args.results_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
