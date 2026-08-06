#!/usr/bin/env python3
"""Run the two Phase 2 *report* ablation arms: LLM-only planning, and the upstream baseline agents.

Evidence this script produces
-----------------------------
For one arm it produces, on a deterministic subset of a split:

1. ``results/<method>/<uid>.json`` -- one plan per query, in exactly the layout
   ``eval_tpc.py --splits <subset-split> --method <method>`` already scores, so the arm's number
   lands in the same shape as every other recorded row.
2. ``<telemetry-dir>/<uid>.json`` + ``<telemetry-dir>/summary.json`` -- per-query and aggregate
   telemetry that **proves the LLM actually fired**: call count, failures, timeouts, prompt/
   completion tokens, and an estimated dollar cost.

The telemetry is the point. The report already documents a trap where an LLM stage looked
beneficial only because it silently never ran (a wrong model id 404'd on every call and the
exception path fell back to the deterministic result). So this script refuses to call an arm a
result when its LLM never fired: ``summary.json`` carries ``reportable: false`` and a
``verdict`` starting with ``UNMEASURED`` whenever ``llm_calls_total == 0`` (see ``assess_arm``).
An unmeasured arm is not a null result and must not be reported as one.

The two arms
------------
``--arm llm-only`` (default agent ``Act``)
    A language model plans autonomously against the sandbox ``WorldEnv`` tools -- no deterministic
    solver, no acceptance gate, no repair loop. This is upstream's ``ActAgent``/``ReActAgent``
    (``chinatravel/agent/pure_neuro_agent/``): the model emits one tool call per step, notes what it
    finds, and finally calls ``plan()``, which asks the model for the itinerary JSON directly.

``--arm upstream`` (default agent ``RuleNeSy``)
    Upstream's shipped neuro-symbolic baselines (``chinatravel/agent/nesy_agent/``): the LLM
    translates the natural-language query into ``hard_logic_py`` and a DFS search then builds a plan
    validated against the commonsense and logical checks. ``LLMNeSy`` additionally asks the LLM for
    every POI recommendation.

``LLM-modulo`` is deliberately not offered: it refuses to run without ``--oracle_translation``, so it
is oracle-privileged and cannot be compared with an oracle-free arm.

What this script is *not*
-------------------------
An offline measurement tool. It touches no shipped code path, changes no default, and is never
imported by the submitted harness. Library defaults still make zero LLM calls; this script makes
them only because it is asked to, on the command line.

It is also a **screen**, never a promotion row: reduced subset, reduced budget, one repeat. Read
``docs/tpc_phase2_eval.md`` for what a screen may and may not prove.

Glue this script owns (and why upstream's own CLI is not enough)
---------------------------------------------------------------
Three upstream defects make ``run_exp.py`` unusable for an English, DeepInfra-backed, oracle-free
arm. All three are handled here without editing upstream:

* ``load_model.init_agent``'s ``RuleNeSy`` branch drops ``lang``, so ``--lang en`` still builds a
  ``zh`` agent and sends Chinese nl2sl prompts for English queries. ``build_agent`` constructs
  ``RuleDrivenAgent(**kwargs)`` directly with ``lang`` set.
* There is no English zero-shot ``Act`` instruction: the shipped one hard-codes the Chinese city
  list, which the English ``WorldEnv`` rejects on every call. ``act_instruction_en`` rebuilds it from
  upstream's own English ``func_doc`` and the English city list, and ``plan_prompt`` is pinned to the
  English ``DIRECT_PROMPT``.
* ``init_llm`` only knows hosted Deepseek/GPT4o/GLM4Plus and local vLLM models, so there is no
  DeepInfra route. ``BudgetedChatLLM`` implements upstream's tiny ``AbstractLLM`` contract against any
  OpenAI-compatible endpoint and adds the bounds and telemetry the report needs.

Released queries *do* carry ``hard_logic_py``, so every query is passed through the harness's own
``visible_query`` before an agent sees it: these arms are oracle-free by construction.

Examples
--------
Offline plumbing self-test (no network, no API key, not a reportable arm)::

    .venv/bin/python scripts/phase2_report_ablations.py --arm llm-only --llm-backend stub --n 2

The two real arms (24 deterministic queries of the familiar-100 val split)::

    TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_report_ablations.py \
        --arm llm-only --agent Act --n 24 --max-steps 30 --workers 4

    TPC_P2_LLM_BACKEND=deepinfra .venv/bin/python scripts/phase2_report_ablations.py \
        --arm upstream --agent RuleNeSy --n 24 --workers 4

Then score each arm over the identical uid set the run materialized::

    .venv/bin/python eval_tpc.py --splits tpc_phase2_familiar_100_val_n24 \
        --method <method printed by the run> --lang en

Full recipe, cost, and how to read the result:
``results/phase2_baselines/screens/README_report_ablations.md``.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import copy
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for _extra in (
    PROJECT_ROOT,
    PROJECT_ROOT / "scripts",
    PROJECT_ROOT / "agent_env" / "scripts",
    PROJECT_ROOT / "chinatravel",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import make_phase2_splits as splits  # noqa: E402
import rehearse_phase2 as reh  # noqa: E402

# --- Arm / agent catalogue -------------------------------------------------

LLM_ONLY_ARM = "llm-only"
UPSTREAM_ARM = "upstream"
ARMS = (LLM_ONLY_ARM, UPSTREAM_ARM)

#: Agents each arm may run, first entry is that arm's default.
ARM_AGENTS: dict[str, tuple[str, ...]] = {
    LLM_ONLY_ARM: ("Act", "ReAct", "ReAct0"),
    UPSTREAM_ARM: ("RuleNeSy", "LLMNeSy"),
}
PURE_NEURO_AGENTS = frozenset(ARM_AGENTS[LLM_ONLY_ARM])
NESY_AGENTS = frozenset(ARM_AGENTS[UPSTREAM_ARM])

DEFAULT_SPLIT_SET = "familiar_100_val"
DEFAULT_N = 24
DEFAULT_SEED = reh.DEFAULT_SEED
DEFAULT_MODEL = "Qwen/Qwen3.6-27B"
DEFAULT_CALL_TIMEOUT_SEC = 60.0
DEFAULT_MAX_CALLS = 64
DEFAULT_BUDGET_SEC = 900.0
DEFAULT_MAX_STEPS = 30
#: DeepInfra list price for Qwen3-family models, USD per 1M tokens (in / out). Only used to turn
#: measured token counts into an estimated cost; override when the provider differs.
DEFAULT_PRICE_IN_PER_MTOK = 0.32
DEFAULT_PRICE_OUT_PER_MTOK = 3.20

TELEMETRY_ROOT = PROJECT_ROOT / "results" / "phase2_baselines" / "screens" / "report_ablations"

#: Upstream's own "the request failed" sentinel (see ``llms.GPT4o._get_response``). Returning it
#: instead of raising is what lets an agent loop absorb one bad call and keep going.
LLM_ERROR_SENTINEL = '{"error": "Request failed, please try again."}'


class CallBudgetExhausted(RuntimeError):
    """Raised when a single query exceeds ``--max-calls``; caught per query, never fatal."""


class QueryTimeout(RuntimeError):
    """Raised when a single query exceeds ``--budget-sec``; caught per query, never fatal."""


# --- Deterministic subset selection ---------------------------------------


def select_subset(
    split_name: str,
    *,
    n: int,
    seed: int = DEFAULT_SEED,
    fold: int = 0,
    folds: int = 1,
    splits_dir: Path | None = None,
) -> list[str]:
    """The first ``n`` uids of one deterministic fold of ``split_name``.

    Exactly ``phase2_quick_eval.py``'s convention -- ``select_fold(uids, fold, folds, seed)[:n]`` --
    so an arm covers the same queries as our own screens and the two are comparable query-for-query.
    Pure and side-effect free: same arguments always give the same list.

    Note the inherited property, so nobody mistakes it for a bug: ``select_fold`` sorts the fold it
    returns, so at the default ``folds=1`` the result is the first ``n`` uids of the sorted split and
    ``seed`` has no effect. The seed decides *which* uids land in which fold, so it only changes the
    subset once ``folds > 1``.
    """
    if splits_dir is None:
        uids = splits.read_split(split_name)
    else:
        uids = splits.read_split(split_name, Path(splits_dir))
    return reh.select_fold(uids, fold=fold, folds=folds, seed=seed)[:n]


def subset_split_name(split_name: str, uids: Sequence[str], *, n: int) -> str:
    """Name of the materialized subset split (``<split>_n<count>``)."""
    del uids
    return f"{split_name}_n{n}"


def materialize_subset_split(
    split_name: str,
    uids: Sequence[str],
    *,
    splits_dir: Path | None = None,
    name: str | None = None,
) -> str:
    """Write ``default_splits/<name>.txt`` listing ``uids`` and return the split name.

    Needed so ``eval_tpc.py`` scores *exactly* the subset every arm ran, rather than the whole
    split with the un-run queries silently scoring zero. Upstream's loader resolves a split with no
    matching data directory by scanning the language tree for the listed uids, so a uid list is the
    only file required. Rewritten on every run: the content is a pure function of
    (split, n, seed, fold, folds), so a rewrite is either a no-op or a corrected list.
    """
    target_dir = Path(splits_dir) if splits_dir is not None else splits.DEFAULT_SPLITS_DIR
    split = name or subset_split_name(split_name, uids, n=len(uids))
    splits._write_lines(target_dir / f"{split}.txt", list(uids))
    return split


# --- The LLM adapter ------------------------------------------------------


@dataclass
class LLMTelemetry:
    """Everything needed to decide whether an arm was measured at all."""

    calls: int = 0
    failures: int = 0
    timeouts: int = 0
    retries: int = 0
    budget_exhausted: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    max_prompt_tokens: int = 0
    latencies_sec: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        lat = sorted(self.latencies_sec)
        return {
            "llm_calls": self.calls,
            "llm_failures": self.failures,
            "llm_timeouts": self.timeouts,
            "llm_retries": self.retries,
            "llm_call_budget_exhausted": self.budget_exhausted,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "max_prompt_tokens": self.max_prompt_tokens,
            "llm_sec_total": round(sum(lat), 2),
            "llm_sec_p50": round(lat[len(lat) // 2], 2) if lat else 0.0,
            "llm_sec_max": round(lat[-1], 2) if lat else 0.0,
        }

    def reset(self) -> None:
        self.calls = 0
        self.failures = 0
        self.timeouts = 0
        self.retries = 0
        self.budget_exhausted = False
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.max_prompt_tokens = 0
        self.latencies_sec = []


def _abstract_llm_base() -> type:
    from chinatravel.agent.llms import AbstractLLM

    return AbstractLLM


def _merge_repeated_role(messages: list[dict]) -> list[dict]:
    """Upstream's consecutive-same-role merge, on a copy.

    ``llms.merge_repeated_role`` mutates the list it is given; the ``Act``/``ReAct`` scratchpad is
    that list, so calling it in place would rewrite the agent's own history mid-run.
    """
    from chinatravel.agent.llms import merge_repeated_role

    return merge_repeated_role(copy.deepcopy(list(messages)))


def _is_timeout(exc: BaseException) -> bool:
    """Whether ``exc`` is a request timeout, by class name (no hard openai dependency)."""
    names = {type(exc).__name__, *(type(base).__name__ for base in type(exc).__mro__)}
    return any("Timeout" in name for name in names) or isinstance(exc, TimeoutError)


def make_budgeted_llm(
    *,
    model: str,
    base_url: str | None,
    api_key: str | None,
    timeout_sec: float,
    max_calls: int,
    retries: int,
    max_tokens: int | None,
    extra_body: dict | None,
    client_factory: Callable[..., Any] | None = None,
) -> Any:
    """Build an ``AbstractLLM`` that drives any OpenAI-compatible endpoint under hard bounds.

    Implemented as a factory rather than a module-level class so importing this module never
    imports ``chinatravel.agent.llms`` (which pulls ``openai``) -- the tests import this module
    with no network and no API key.

    Bounds, all of them per query:

    * ``timeout_sec`` -- SDK-level per-call timeout; a hung request cannot eat the whole budget.
    * ``retries`` -- extra attempts after a failed call; the last failure returns upstream's error
      sentinel instead of raising, so the agent loop degrades rather than dying.
    * ``max_calls`` -- hard ceiling on calls for one query; exceeding it raises
      ``CallBudgetExhausted``, which the per-query runner records as a failure.

    ``max_calls * timeout_sec`` is therefore a genuine upper bound on the LLM time one query can
    consume, independent of the wall-clock budget.
    """
    base = _abstract_llm_base()

    class BudgetedChatLLM(base):  # type: ignore[misc, valid-type]
        """Upstream ``AbstractLLM`` over an OpenAI-compatible chat endpoint, with telemetry."""

        def __init__(self) -> None:
            super().__init__()
            self.name = model.replace("/", "-")
            self.model = model
            self.timeout_sec = float(timeout_sec)
            self.max_calls = int(max_calls)
            self.retries = int(retries)
            self.max_tokens = max_tokens
            self.extra_body = extra_body
            self.telemetry = LLMTelemetry()
            factory = client_factory or _default_openai_factory
            self._client = factory(base_url=base_url, api_key=api_key, timeout=float(timeout_sec))

        # -- upstream contract -------------------------------------------------
        def _get_response(self, messages, one_line, json_mode):  # noqa: ANN001
            if self.telemetry.calls >= self.max_calls:
                self.telemetry.budget_exhausted = True
                raise CallBudgetExhausted(
                    f"query exceeded --max-calls={self.max_calls} for model {self.model!r}"
                )
            payload = _merge_repeated_role(messages)
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": payload,
                "temperature": 0.0,
            }
            if self.max_tokens is not None:
                kwargs["max_tokens"] = int(self.max_tokens)
            if self.extra_body:
                kwargs["extra_body"] = self.extra_body
            if one_line:
                kwargs["stop"] = ["\n"]
            elif json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            attempts = max(1, self.retries + 1)
            for attempt in range(attempts):
                started = time.perf_counter()
                try:
                    text = self._send(kwargs)
                except Exception as exc:  # noqa: BLE001 - every provider error is absorbed here
                    self.telemetry.latencies_sec.append(time.perf_counter() - started)
                    if _is_timeout(exc):
                        self.telemetry.timeouts += 1
                    else:
                        self.telemetry.failures += 1
                    if attempt + 1 < attempts:
                        self.telemetry.retries += 1
                        continue
                    return LLM_ERROR_SENTINEL
                self.telemetry.latencies_sec.append(time.perf_counter() - started)
                return _repair_if_json(text, json_mode)
            return LLM_ERROR_SENTINEL

        def _send(self, kwargs: dict[str, Any]) -> str:
            completion = self._client.chat.completions.create(**kwargs)
            self.telemetry.calls += 1
            usage = getattr(completion, "usage", None)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            self.telemetry.prompt_tokens += prompt_tokens
            self.telemetry.completion_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
            self.telemetry.max_prompt_tokens = max(self.telemetry.max_prompt_tokens, prompt_tokens)
            # Keep upstream's token counters in sync: NesyAgent copies them onto the saved plan.
            self.input_token_count = self.telemetry.prompt_tokens
            self.output_token_count = self.telemetry.completion_tokens
            self.input_token_maxx = self.telemetry.max_prompt_tokens
            return (completion.choices[0].message.content or "").strip()

    return BudgetedChatLLM()


def _default_openai_factory(*, base_url: str | None, api_key: str | None, timeout: float) -> Any:
    from openai import OpenAI

    kwargs: dict[str, Any] = {"timeout": timeout, "max_retries": 0}
    if base_url:
        kwargs["base_url"] = base_url
    if api_key:
        kwargs["api_key"] = api_key
    return OpenAI(**kwargs)


def _repair_if_json(text: str, json_mode: bool) -> str:
    if not json_mode:
        return text
    try:
        from json_repair import repair_json
    except Exception:  # pragma: no cover - optional dependency
        return text
    return repair_json(text, ensure_ascii=False)


# --- The stub backend (offline plumbing self-test) ------------------------


class StubChatLLM:
    """Offline stand-in for the adapter: fires "calls", never opens a socket.

    Exists so the whole runner -- subset selection, oracle strip, agent loop, plan write, telemetry,
    verdict -- is exercised with no network and no API key. A stub arm is **never reportable**
    (``assess_arm`` rejects it by backend), because its plan is canned rather than reasoned.
    """

    backend = "stub"

    #: Shape-only itinerary: enough for the plan to be non-empty and JSON-serializable, and
    #: deliberately not enough to pass any check -- a stub must never look like a good plan.
    STUB_PLAN: dict[str, Any] = {
        "people_number": 1,
        "start_city": "",
        "target_city": "",
        "itinerary": [{"day": 1, "activities": []}],
    }

    def __init__(self, *, plan: dict[str, Any] | None = None, script: Sequence[str] | None = None):
        self.name = "stub"
        self.model = "stub"
        self.telemetry = LLMTelemetry()
        self.input_token_count = 0
        self.output_token_count = 0
        self.input_token_maxx = 0
        self._plan = plan if plan is not None else dict(self.STUB_PLAN)
        self._script = list(
            script
            or [
                'notedown(description="Day 1", content="stub note")',
                'plan(query="stub")',
            ]
        )
        self._step = 0

    def reset_for_query(self) -> None:
        """Rewind the canned action script so every query gets the same stub behaviour."""
        self._step = 0

    def __call__(self, messages, one_line=True, json_mode=False):  # noqa: ANN001
        self.telemetry.calls += 1
        self.telemetry.prompt_tokens += 10
        self.telemetry.completion_tokens += 5
        self.telemetry.max_prompt_tokens = max(self.telemetry.max_prompt_tokens, 10)
        self.input_token_count = self.telemetry.prompt_tokens
        self.output_token_count = self.telemetry.completion_tokens
        self.input_token_maxx = self.telemetry.max_prompt_tokens
        if json_mode:
            return json.dumps(self._plan, ensure_ascii=False)
        action = self._script[min(self._step, len(self._script) - 1)]
        self._step += 1
        return action


class StubEnv:
    """Minimal ``WorldEnv`` stand-in for the stub backend: no database, no tools."""

    def reset(self) -> None:
        return None

    def __call__(self, action: str) -> str:  # pragma: no cover - stub script avoids env calls
        return f"StubEnv ignored action: {action}"


# --- English prompts for the pure-neuro arm -------------------------------

_ACT_HEADER_EN = """Collect information for a query plan using interleaving 'Action', and 'Observation' steps. Ensure you gather valid information related to transportation(including inter and inner city), dining, attractions, and accommodation. All information including time, cost, location and others must be written in notebook, which will then be input into the Planner tool. Note that the nested use of tools is not allowed. 'Action' can have 19 different types:

city_list = {city_list}. All the cities name you use must be in this list.
"""

_ACT_BODY_EN = """Your action will be executed in the following format: action, so any additional text like 'Action: ' is not allowed and just one line is allowed for each action.

You must finish your response within {max_steps} steps including plan.

Select the transportation, dining, attractions, and accommodation information you need to plan your trip and write them in the notebook. Not EVERYTHING is needed, only what you need to plan the trip. For example, when you get ten or more accommodations, you only need to note down the information of the accommodation you want to stay in, usually one, and note it down in the notebook. You must not note down all the accommodations information. And usually, 2-4 attractions are enough for one day.

What you note down in the notebook should be a plan or plans for days. May be notedown(description = "Day 1(Day 1 morning is also acceptable)", content = "At 8:00, have breakfast at hotel A, then go to attraction B, using metro(together with the cost, time, stations and other information). Attraction B will cost xxx yuan and xxx hours. Then go to restaurant C for lunch, using taxi(together with the cost, time, distance and other information). Restaurant C will cost xxx yuan. Then... ###More details here###.")

Limitations of the plan:
1. Breakfast can be in the hotel for free and must be in 6:00-9:00, lunch must be in 11:00-13:00, dinner must be in 17:00-20:00.
2. The attraction or restaurant must be open when you plan to go there.
3. All activities must not conflict with each other.
4. The activity before must be finished before the next activity starts.
5. Accommodation should be planned for each night, and the accommodation should be a continuous stay if not specified by the user's query. If only one day is planned, accommodation is not needed.

### EXAMPLE ###
...... // Some actions before planning, looking up the information
Action[X]: notedown(description='Day 1', content='At 8:00, have breakfast at hotel A, then go to attraction B, using metro(together with the cost, time, stations and other information). Attraction B will cost xxx yuan and xxx hours. Then go to restaurant C for lunch, using taxi(together with the cost, time, distance and other information). Restaurant C will cost xxx yuan. Then... ###More details here###.')
...... // More actions and observations
// The first day plan must include the transportation from the start city to the target city, and the last activity must be the transportation back to the start city.
Action[n]: plan(query="My friend and I want to travel to Nanjing for three days with a budget of 4000 yuan. We prefer the metro and like Jiangsu-Zhejiang cuisine. Please give us a travel plan.")
### EXAMPLE END ###

Do not forget to note down the ###transportation information between locations### before planning. Intercity transportation information should be noted down before planning too.

!!!Must not use next_page() too often!!!

Remember to note down all information you need in the notebook before planning.

!!!The intercity transport back to the start city must be noted down before planning!!!

!!!next_page() should only be used when you need to get the next page of the latest Result history. Once you get the suitable information, you must STOP using this function.!!!

Query:
"""


def act_instruction_en(max_steps: int = DEFAULT_MAX_STEPS) -> str:
    """The zero-shot ``Act`` instruction, in English, with the English city list.

    Upstream ships only a Chinese ``ZEROSHOT_ACT_INSTRUCTION``: it hard-codes the Chinese city
    names, which the English ``WorldEnv`` rejects on every tool call, so an English ``Act`` run
    against the shipped prompt fails structurally rather than for any reason worth reporting. The
    tool documentation (``func_doc``) is reused verbatim from upstream's own English prompt module,
    so the tool contract the model sees is upstream's, not ours.
    """
    from chinatravel.agent.pure_neuro_agent.prompts import prompts_en
    from chinatravel.environment.language import city_names

    cities = json.dumps(city_names("en"), ensure_ascii=False)
    return (
        _ACT_HEADER_EN.format(city_list=cities)
        + prompts_en.func_doc
        + _ACT_BODY_EN.format(max_steps=max_steps)
    )


def react_instruction(lang: str) -> str:
    """Upstream's one-shot ReAct instruction for ``lang`` (English variant exists upstream)."""
    if lang == "en":
        from chinatravel.agent.pure_neuro_agent.prompts.prompts_en import (
            ONESHOT_REACT_INSTRUCTION,
        )

        return ONESHOT_REACT_INSTRUCTION
    from chinatravel.agent.pure_neuro_agent.prompts import ONESHOT_REACT_INSTRUCTION

    return ONESHOT_REACT_INSTRUCTION


def zeroshot_react_instruction(lang: str) -> str:
    """Zero-shot ReAct instruction; upstream has no English variant, so reuse the Act body."""
    if lang == "en":
        return act_instruction_en()
    from chinatravel.agent.pure_neuro_agent.prompts import ZEROSHOT_REACT_INSTRUCTION

    return ZEROSHOT_REACT_INSTRUCTION


def plan_prompt_for(lang: str) -> str:
    """The ``plan()`` prompt (``DIRECT_PROMPT``) in the right language.

    ``ActAgent.plan`` defaults to the Chinese one regardless of ``lang``.
    """
    if lang == "en":
        from chinatravel.agent.pure_neuro_agent.prompts.prompts_en import DIRECT_PROMPT

        return DIRECT_PROMPT
    from chinatravel.agent.pure_neuro_agent.prompts import DIRECT_PROMPT

    return DIRECT_PROMPT


# --- Agent construction ---------------------------------------------------


def arm_for_agent(agent: str) -> str:
    """Which arm ``agent`` belongs to."""
    for arm, agents in ARM_AGENTS.items():
        if agent in agents:
            return arm
    raise ValueError(f"unknown agent {agent!r}")


def resolve_agent(arm: str, agent: str | None) -> str:
    """Validate ``agent`` against ``arm``, defaulting to the arm's first agent."""
    if arm not in ARM_AGENTS:
        raise ValueError(f"unknown arm {arm!r} (expected one of {ARMS})")
    if agent is None:
        return ARM_AGENTS[arm][0]
    if agent not in ARM_AGENTS[arm]:
        raise ValueError(
            f"--agent {agent!r} is not part of --arm {arm!r}; "
            f"choose from {ARM_AGENTS[arm]} (or pass --arm {arm_for_agent(agent)})"
        )
    return agent


def build_agent(
    agent_name: str,
    *,
    env: Any,
    llm: Any,
    lang: str,
    max_steps: int,
    cache_dir: str | os.PathLike,
    log_dir: str | os.PathLike,
    debug: bool = False,
) -> Any:
    """Construct one upstream agent, working around ``init_agent``'s English defects.

    Deliberately does **not** call ``chinatravel.agent.load_model.init_agent``: its ``RuleNeSy``
    branch drops ``lang`` (so an English run gets Chinese nl2sl prompts) and its ``Act`` branch
    pins the Chinese instruction. Everything else -- the agent classes themselves -- is upstream's.
    """
    cache_dir = str(cache_dir)
    log_dir = str(log_dir)
    if agent_name in PURE_NEURO_AGENTS:
        from chinatravel.agent.pure_neuro_agent.pure_neuro_agent import ActAgent, ReActAgent

        if agent_name == "Act":
            prompt = act_instruction_en(max_steps) if lang == "en" else _upstream_act_prompt()
            return ActAgent(
                env=env,
                backbone_llm=llm,
                prompt=prompt,
                max_steps=max_steps,
                plan_prompt=plan_prompt_for(lang),
                debug=debug,
            )
        prompt = react_instruction(lang) if agent_name == "ReAct" else zeroshot_react_instruction(lang)
        return ReActAgent(
            env=env,
            backbone_llm=llm,
            prompt=prompt,
            max_steps=max_steps,
            plan_prompt=plan_prompt_for(lang),
            debug=debug,
        )

    if agent_name == "RuleNeSy":
        from chinatravel.agent.nesy_agent.rule_driven_rec import RuleDrivenAgent

        return RuleDrivenAgent(
            env=env,
            backbone_llm=llm,
            cache_dir=cache_dir,
            log_dir=log_dir,
            debug=debug,
            lang=lang,
        )
    if agent_name == "LLMNeSy":
        from chinatravel.agent.nesy_agent.llm_driven_rec import LLMDrivenAgent

        return LLMDrivenAgent(
            method="LLMNeSy",
            env=env,
            backbone_llm=llm,
            cache_dir=cache_dir,
            log_dir=log_dir,
            debug=debug,
            lang=lang,
        )
    raise ValueError(f"unsupported agent {agent_name!r}")


def _upstream_act_prompt() -> str:
    from chinatravel.agent.pure_neuro_agent.prompts import ZEROSHOT_ACT_INSTRUCTION

    return ZEROSHOT_ACT_INSTRUCTION


# --- Per-query execution --------------------------------------------------


def _visible(query: dict[str, Any]) -> dict[str, Any]:
    """Strip every oracle/verifier field before an agent sees the query.

    Released familiar-100 queries carry ``hard_logic_py``; the held-out set does not. Reuses the
    shipped harness's own ``visible_query`` so the two can never drift apart.
    """
    from solve_script_with_harness import visible_query

    return visible_query(query)


def _coerce_plan(raw: Any) -> dict[str, Any]:
    """Normalize an agent answer into the dict ``results/<method>/<uid>.json`` holds.

    Mirrors ``run_exp.py``: a ``str`` answer is JSON-parsed, and unparseable text is preserved under
    ``"plan"`` rather than discarded -- an unparseable answer is a real, reportable failure mode of
    the LLM-only arm and must be visible in the artifact, not silently replaced.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except Exception:
            return {"plan": raw}
        return parsed if isinstance(parsed, dict) else {"plan": parsed}
    return {"plan": raw}


def run_one_query(
    agent: Any,
    agent_name: str,
    query: dict[str, Any],
    *,
    budget_sec: float | None,
    load_translation_cache: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Solve one query. Returns ``(plan_or_None, telemetry)``; **never raises**.

    Every failure mode -- budget exhausted, per-query timeout, provider error, a bug in an upstream
    agent -- is recorded in the telemetry dict and the run continues with the next query. That is
    the whole point: one bad query must not lose the arm.
    """
    uid = query.get("uid", "?")
    llm = getattr(agent, "backbone_llm", None)
    telemetry_obj: LLMTelemetry | None = getattr(llm, "telemetry", None)
    if telemetry_obj is not None:
        telemetry_obj.reset()
    reset_hook = getattr(llm, "reset_for_query", None)
    if callable(reset_hook):
        reset_hook()

    record: dict[str, Any] = {
        "uid": uid,
        "agent": agent_name,
        "ok": False,
        "error": None,
        "timed_out": False,
        "agent_success": None,
        "steps": None,
    }
    started = time.perf_counter()
    saved_stdout, saved_stderr = sys.stdout, sys.stderr
    try:
        plan = _invoke(
            agent,
            agent_name,
            query,
            budget_sec=budget_sec,
            load_translation_cache=load_translation_cache,
            record=record,
        )
        record["ok"] = True
    except QueryTimeout as exc:
        plan = None
        record["timed_out"] = True
        record["error"] = str(exc)
    except CallBudgetExhausted as exc:
        plan = None
        record["error"] = f"call budget exhausted: {exc}"
    except BaseException as exc:  # noqa: BLE001 - a broken query is data, not a crash
        plan = None
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc(limit=8)
    finally:
        # ``NesyAgent.run`` reassigns the global ``sys.stdout``/``sys.stderr`` to a file Logger and
        # never restores them; without this the worker's own output disappears into the last
        # query's log file.
        sys.stdout, sys.stderr = saved_stdout, saved_stderr

    record["wall_sec"] = round(time.perf_counter() - started, 2)
    record["steps"] = getattr(agent, "cur_step", record["steps"])
    if telemetry_obj is not None:
        record.update(telemetry_obj.as_dict())
    else:
        record.update(LLMTelemetry().as_dict())
    record["plan_written"] = plan is not None
    record["plan_nonempty"] = bool(plan) and bool(plan.get("itinerary"))
    return plan, record


def _invoke(
    agent: Any,
    agent_name: str,
    query: dict[str, Any],
    *,
    budget_sec: float | None,
    load_translation_cache: bool,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Call the right upstream entry point for ``agent_name``, under the per-query budget."""

    def _call() -> dict[str, Any]:
        if agent_name in PURE_NEURO_AGENTS:
            return_info = agent(query["nature_language"])
            record["agent_success"] = not str(return_info["ans"]).startswith('{"error"')
            plan = _coerce_plan(return_info["ans"])
            llm = agent.backbone_llm
            plan["input_token_count"] = getattr(llm, "input_token_count", 0)
            plan["output_token_count"] = getattr(llm, "output_token_count", 0)
            plan["input_token_maxx"] = getattr(llm, "input_token_maxx", 0)
            return plan
        succ, plan = agent.run(
            dict(query),
            load_cache=load_translation_cache,
            oralce_translation=False,
            preference_search=False,
        )
        record["agent_success"] = bool(succ)
        return _coerce_plan(plan)

    if not budget_sec or budget_sec <= 0:
        return _call()
    return _with_timeout(_call, budget_sec)


def _with_timeout(fn: Callable[[], Any], budget_sec: float) -> Any:
    """Run ``fn`` under a wall-clock cap, raising ``QueryTimeout`` when it overruns.

    Uses ``func_timeout`` when available (the same dependency ``run_tpc.py`` uses) and otherwise
    runs unbounded -- the LLM side is still bounded by ``--max-calls * --call-timeout-sec``, so an
    absent optional dependency degrades the cap rather than removing every bound.
    """
    try:
        from func_timeout import FunctionTimedOut, func_timeout
    except Exception:  # pragma: no cover - optional dependency
        return fn()
    try:
        return func_timeout(budget_sec, fn)
    except FunctionTimedOut as exc:
        raise QueryTimeout(f"query exceeded --budget-sec={budget_sec}") from exc


# --- Verdict --------------------------------------------------------------


def assess_arm(summary: dict[str, Any]) -> tuple[bool, str]:
    """Decide whether an arm is reportable, and say why. Pure function of ``summary``.

    The rule the report depends on: **an arm whose LLM never fired is UNMEASURED, not a null
    result.** A zero-call run looks like a clean "the LLM does not help" finding while actually
    being "the LLM was never asked" -- exactly the trap already documented for the Phase 2 LLM
    parse stage, where a wrong model id 404'd on every call and the silent exception fallback made
    the arm look identical to the deterministic path.
    """
    calls = int(summary.get("llm_calls_total", 0) or 0)
    queries = int(summary.get("queries", 0) or 0)
    plans = int(summary.get("plans_written", 0) or 0)
    failures = int(summary.get("llm_failures_total", 0) or 0)
    timeouts = int(summary.get("llm_timeouts_total", 0) or 0)

    if str(summary.get("llm_backend")) == "stub":
        return False, (
            "UNMEASURED (stub backend): this run exercised the plumbing offline with canned "
            "responses. It proves the tooling works; it says nothing about the arm's quality."
        )
    if queries == 0:
        return False, "UNMEASURED: no queries were run."
    if calls == 0:
        return False, (
            "UNMEASURED: the LLM never fired (llm_calls_total=0), so this arm has no result at "
            "all. Do NOT report it as a null result -- fix the endpoint/model/key first and rerun."
        )
    if plans == 0:
        return False, (
            "UNMEASURED: the LLM fired but not one query produced a plan file; there is nothing "
            "for eval_tpc.py to score."
        )
    bad = failures + timeouts
    if bad >= calls:
        return False, (
            f"UNMEASURED: every LLM call failed or timed out ({bad}/{calls}); the plans on disk "
            "come from the degradation path, not from the model."
        )
    if bad > calls * 0.2:
        return True, (
            f"MEASURED but DEGRADED: {bad}/{calls} LLM calls failed or timed out. Report the "
            "number with that caveat -- it is a lower bound on the arm, not the arm."
        )
    return True, (
        f"MEASURED: {calls} LLM calls over {queries} queries, {plans} plans written. Score with "
        "eval_tpc.py and report as a screen (reduced subset/budget), never as a promotion row."
    )


def summarize(records: Iterable[dict[str, Any]], *, base: dict[str, Any],
              price_in: float = DEFAULT_PRICE_IN_PER_MTOK,
              price_out: float = DEFAULT_PRICE_OUT_PER_MTOK) -> dict[str, Any]:
    """Aggregate per-query records into the arm summary, incl. the reportability verdict."""
    rows = list(records)
    n = len(rows)
    prompt_tokens = sum(int(r.get("prompt_tokens", 0) or 0) for r in rows)
    completion_tokens = sum(int(r.get("completion_tokens", 0) or 0) for r in rows)
    calls = sum(int(r.get("llm_calls", 0) or 0) for r in rows)
    summary = dict(base)
    summary.update(
        {
            "queries": n,
            "ok": sum(1 for r in rows if r.get("ok")),
            "failed": sum(1 for r in rows if not r.get("ok")),
            "timed_out": sum(1 for r in rows if r.get("timed_out")),
            "agent_success": sum(1 for r in rows if r.get("agent_success")),
            "plans_written": sum(1 for r in rows if r.get("plan_written")),
            "plans_nonempty": sum(1 for r in rows if r.get("plan_nonempty")),
            "call_budget_exhausted": sum(
                1 for r in rows if r.get("llm_call_budget_exhausted")
            ),
            "llm_calls_total": calls,
            "llm_failures_total": sum(int(r.get("llm_failures", 0) or 0) for r in rows),
            "llm_timeouts_total": sum(int(r.get("llm_timeouts", 0) or 0) for r in rows),
            "llm_calls_per_query": round(calls / n, 2) if n else 0.0,
            "prompt_tokens_total": prompt_tokens,
            "completion_tokens_total": completion_tokens,
            "tokens_per_query": round((prompt_tokens + completion_tokens) / n) if n else 0,
            "est_cost_usd": round(
                prompt_tokens / 1e6 * price_in + completion_tokens / 1e6 * price_out, 4
            ),
            "est_cost_usd_per_query": round(
                (prompt_tokens / 1e6 * price_in + completion_tokens / 1e6 * price_out) / n, 4
            )
            if n
            else 0.0,
            "price_in_per_mtok": price_in,
            "price_out_per_mtok": price_out,
            "wall_sec_mean": round(
                sum(float(r.get("wall_sec", 0.0) or 0.0) for r in rows) / n, 1
            )
            if n
            else 0.0,
        }
    )
    reportable, verdict = assess_arm(summary)
    summary["reportable"] = reportable
    summary["verdict"] = verdict
    return summary


# --- Runner ---------------------------------------------------------------


@dataclass
class ArmConfig:
    """Everything a worker needs to build its own env + agent + LLM. Must stay picklable."""

    arm: str
    agent: str
    lang: str
    model: str
    llm_backend: str
    base_url: str | None
    max_steps: int
    budget_sec: float
    call_timeout_sec: float
    max_calls: int
    retries: int
    max_tokens: int | None
    enable_thinking: bool
    results_dir: str
    telemetry_dir: str
    cache_dir: str
    log_dir: str
    load_translation_cache: bool
    debug: bool


_WORKER: dict[str, Any] = {}


def build_llm(config: ArmConfig) -> Any:
    """Build the arm's LLM. ``stub`` never touches the network; the rest read ``.env`` in-process."""
    if config.llm_backend == "stub":
        return StubChatLLM()

    from chinatravel.agent.phase2.llm_client import (
        DEFAULT_DEEPINFRA_BASE_URL,
        _thinking_disabled_extra_body,
        load_local_env,
    )

    # Loads DEEPINFRA_API_KEY (etc.) from .env into this process only; nothing is sourced or echoed.
    load_local_env()
    base_url = config.base_url
    api_key = None
    if config.llm_backend == "deepinfra":
        base_url = base_url or os.environ.get("DEEPINFRA_BASE_URL") or DEFAULT_DEEPINFRA_BASE_URL
        api_key = os.environ.get("DEEPINFRA_API_KEY")
    else:
        base_url = base_url or os.environ.get("TPC_P2_LLM_BASE_URL")
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("TPC_P2_LLM_API_KEY")
    extra_body = _thinking_disabled_extra_body(
        {"enable_thinking": True} if config.enable_thinking else {}, config.model
    )
    return make_budgeted_llm(
        model=config.model,
        base_url=base_url,
        api_key=api_key,
        timeout_sec=config.call_timeout_sec,
        max_calls=config.max_calls,
        retries=config.retries,
        max_tokens=config.max_tokens,
        extra_body=extra_body,
    )


def build_env(config: ArmConfig) -> Any:
    """Build the arm's environment: the real sandbox ``WorldEnv``, or the stub for offline runs."""
    if config.llm_backend == "stub":
        return StubEnv()
    from chinatravel.environment.world_env import WorldEnv

    return WorldEnv(lang=config.lang)


def build_runtime(config: ArmConfig) -> tuple[Any, Any]:
    """``(env, agent)`` for one worker. One agent is reused across that worker's queries."""
    env = build_env(config)
    llm = build_llm(config)
    agent = build_agent(
        config.agent,
        env=env,
        llm=llm,
        lang=config.lang,
        max_steps=config.max_steps,
        cache_dir=config.cache_dir,
        log_dir=config.log_dir,
        debug=config.debug,
    )
    return env, agent


def _init_worker(config: ArmConfig) -> None:  # pragma: no cover - exercised only in worker procs
    _WORKER["config"] = config
    _WORKER["env"], _WORKER["agent"] = build_runtime(config)


def _worker_solve(uid: str) -> dict[str, Any]:  # pragma: no cover - runs in a worker process
    config: ArmConfig = _WORKER["config"]
    query = _load_visible_query(config, uid)
    return solve_and_write(_WORKER["agent"], config, query)


def _load_visible_query(config: ArmConfig, uid: str) -> dict[str, Any]:
    queries = _WORKER.get("queries")
    if queries is None:
        raise RuntimeError("worker has no query cache")
    return queries[uid]


def solve_and_write(agent: Any, config: ArmConfig, query: dict[str, Any]) -> dict[str, Any]:
    """Solve one visible query, write its plan and telemetry, return the telemetry record."""
    plan, record = run_one_query(
        agent,
        config.agent,
        query,
        budget_sec=config.budget_sec,
        load_translation_cache=config.load_translation_cache,
    )
    uid = query.get("uid", "unknown")
    if plan is not None:
        results_dir = Path(config.results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / f"{uid}.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
    telemetry_dir = Path(config.telemetry_dir)
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    (telemetry_dir / f"{uid}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return record


def run_arm(
    config: ArmConfig,
    queries: dict[str, dict[str, Any]],
    uids: Sequence[str],
    *,
    workers: int = 1,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Run every uid, sequentially (``workers <= 1``) or across worker processes.

    A worker crash or a per-query exception costs that query only: the record still lands in the
    telemetry directory and the loop moves on.
    """
    records: list[dict[str, Any]] = []
    if workers <= 1:
        _WORKER["queries"] = queries
        _, agent = build_runtime(config)
        for uid in uids:
            record = solve_and_write(agent, config, queries[uid])
            records.append(record)
            if progress:
                progress(record)
        return records

    ctx_init = (config, queries)
    with futures.ProcessPoolExecutor(
        max_workers=workers, initializer=_init_pool_worker, initargs=ctx_init
    ) as pool:
        future_map = {pool.submit(_worker_solve, uid): uid for uid in uids}
        for fut in futures.as_completed(future_map):
            uid = future_map[fut]
            try:
                record = fut.result()
            except BaseException as exc:  # noqa: BLE001 - a dead worker is one lost query
                record = {
                    "uid": uid,
                    "agent": config.agent,
                    "ok": False,
                    "error": f"worker died: {type(exc).__name__}: {exc}",
                    "plan_written": False,
                    "plan_nonempty": False,
                    **LLMTelemetry().as_dict(),
                }
            records.append(record)
            if progress:
                progress(record)
    return records


def _init_pool_worker(config: ArmConfig, queries: dict[str, dict[str, Any]]) -> None:
    # pragma: no cover - runs in a worker process
    _WORKER["queries"] = queries
    _init_worker(config)


def load_visible_queries(split: str, lang: str) -> tuple[str, dict[str, dict[str, Any]]]:
    """Load ``split`` and return ``(lang_used, {uid: visible_query})``.

    Reuses the shipped harness's language-fallback loader, so a split that only resolves in the
    other language tree still runs and the caller learns which language it actually got.
    """
    from solve_script_with_harness import load_queries_with_lang

    lang_used, _uids, query_data = load_queries_with_lang(split, lang)
    return lang_used, {uid: _visible(q) for uid, q in query_data.items()}


def _print_summary(summary: dict[str, Any]) -> None:
    print("=" * 78)
    print(f"ARM {summary['arm']} / agent {summary['agent']} / model {summary['model']}")
    print(f"  split={summary['subset_split']} n={summary['queries']} lang={summary['lang']}")
    print(f"  results dir : results/{summary['method']}/")
    print(f"  telemetry   : {summary['telemetry_dir']}")
    print("-" * 78)
    print(f"  ok / failed / timed out     {summary['ok']} / {summary['failed']} / {summary['timed_out']}")
    print(f"  plans written / non-empty   {summary['plans_written']} / {summary['plans_nonempty']}")
    print(f"  LLM calls (total / query)   {summary['llm_calls_total']} / {summary['llm_calls_per_query']}")
    print(f"  LLM failures / timeouts     {summary['llm_failures_total']} / {summary['llm_timeouts_total']}")
    print(f"  tokens per query            {summary['tokens_per_query']}")
    print(f"  est cost (total / query)    ${summary['est_cost_usd']} / ${summary['est_cost_usd_per_query']}")
    print(f"  mean wall per query (s)     {summary['wall_sec_mean']}")
    print("-" * 78)
    print(f"  REPORTABLE: {summary['reportable']}")
    print(f"  VERDICT:    {summary['verdict']}")
    print("=" * 78)
    print(
        "  score with: .venv/bin/python eval_tpc.py "
        f"--splits {summary['subset_split']} --method {summary['method']} --lang {summary['lang']}"
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--arm", choices=ARMS, default=LLM_ONLY_ARM,
                   help="llm-only: a model plans autonomously with the env tools, no solver. "
                        "upstream: the neuro-symbolic baselines shipped in chinatravel/agent/.")
    p.add_argument("--agent", default=None,
                   help=f"Agent within the arm. llm-only: {ARM_AGENTS[LLM_ONLY_ARM]}; "
                        f"upstream: {ARM_AGENTS[UPSTREAM_ARM]}. Defaults to the arm's first entry.")
    p.add_argument("--split", default=None,
                   help="Raw split name; overrides --split-set.")
    p.add_argument("--split-set",
                   choices=["val", "test", "familiar_100", "familiar_100_val", "familiar_100_test"],
                   default=DEFAULT_SPLIT_SET,
                   help="Split alias (same vocabulary as phase2_quick_eval.py).")
    p.add_argument("--n", type=int, default=DEFAULT_N, help="Subset size (queries to run).")
    p.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Subset selection seed.")
    p.add_argument("--fold", type=int, default=0)
    p.add_argument("--folds", type=int, default=1)
    p.add_argument("--lang", choices=["zh", "en"], default="en")
    p.add_argument("--method", default=None,
                   help="Output directory name: plans land at results/<method>/<uid>.json. "
                        "Defaults to report_ablation_<arm>_<agent>_<model>_<lang>.")
    p.add_argument("--llm-backend", choices=["deepinfra", "openai", "stub"], default=None,
                   help="Default: TPC_P2_LLM_BACKEND if it names one of these, else 'stub'. "
                        "'stub' is an offline plumbing self-test and is never reportable.")
    p.add_argument("--model", default=None,
                   help=f"Model id (default {DEFAULT_MODEL}, or TPC_P2_LLM_MODEL).")
    p.add_argument("--base-url", default=None, help="OpenAI-compatible endpoint override.")
    p.add_argument("--enable-thinking", action="store_true",
                   help="Leave Qwen3 thinking mode on (off by default: ~10x slower per call).")
    p.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS,
                   help="Act/ReAct step cap (llm-only arm).")
    p.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS,
                   help="Hard ceiling on LLM calls per query; exceeding it fails that query only.")
    p.add_argument("--call-timeout-sec", type=float, default=DEFAULT_CALL_TIMEOUT_SEC,
                   help="Per-LLM-call timeout. With --max-calls this bounds a query's LLM time.")
    p.add_argument("--max-tokens", type=int, default=4096, help="Per-call completion cap.")
    p.add_argument("--retries", type=int, default=1,
                   help="Extra attempts after a failed call (0 = none).")
    p.add_argument("--budget-sec", type=float, default=DEFAULT_BUDGET_SEC,
                   help="Per-query wall-clock cap (0 disables).")
    p.add_argument("--workers", type=int, default=1,
                   help="Worker processes. One agent (and one WorldEnv) per worker.")
    p.add_argument("--load-translation-cache", action="store_true",
                   help="upstream arm: reuse a cached nl2sl translation. Off by default so the "
                        "LLM demonstrably fires (a warm cache yields llm_calls=0 = UNMEASURED).")
    p.add_argument("--price-in-per-mtok", type=float, default=DEFAULT_PRICE_IN_PER_MTOK)
    p.add_argument("--price-out-per-mtok", type=float, default=DEFAULT_PRICE_OUT_PER_MTOK)
    p.add_argument("--telemetry-dir", default=None,
                   help=f"Default {TELEMETRY_ROOT}/<method>/.")
    p.add_argument("--splits-dir", default=None,
                   help="Where to write the subset split file. Default: the repo's default_splits, "
                        "which is the only place eval_tpc.py looks -- point it elsewhere only in "
                        "tests. The run itself always loads the source split and filters, so this "
                        "never changes which queries are solved.")
    p.add_argument("--no-materialize-split", action="store_true",
                   help="Do not write the <split>_n<N> subset split file.")
    p.add_argument("--debug", action="store_true", help="Verbose agent output.")
    p.add_argument("--dry-run", action="store_true",
                   help="Resolve the subset (and write the subset split file, so a dry run is also "
                        "how you prepare one) and exit without solving or calling the LLM.")
    return p


def resolve_backend(explicit: str | None) -> str:
    """Backend to use: the flag, else ``TPC_P2_LLM_BACKEND`` when usable, else the offline stub.

    Defaulting to ``stub`` rather than to a live provider keeps the "flags off makes zero LLM
    calls" habit: this script never reaches the network unless told to.
    """
    if explicit:
        return explicit
    env_backend = str(os.environ.get("TPC_P2_LLM_BACKEND", "")).lower()
    if env_backend in {"deepinfra", "openai"}:
        return env_backend
    return "stub"


def default_method(arm: str, agent: str, model: str, lang: str) -> str:
    slug = model.replace("/", "-").replace(":", "-")
    return f"report_ablation_{arm.replace('-', '_')}_{agent}_{slug}_{lang}"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    agent_name = resolve_agent(args.arm, args.agent)
    split_name = args.split or reh.resolve_split_set(args.split_set)[0]
    uids = select_subset(split_name, n=args.n, seed=args.seed, fold=args.fold, folds=args.folds)
    if not uids:
        print(f"No uids selected from split {split_name!r}.", file=sys.stderr)
        return 2

    backend = resolve_backend(args.llm_backend)
    model = args.model or os.environ.get("TPC_P2_LLM_MODEL") or DEFAULT_MODEL
    if backend == "stub":
        model = "stub"
    method = args.method or default_method(args.arm, agent_name, model, args.lang)
    subset_split = split_name
    if not args.no_materialize_split:
        subset_split = materialize_subset_split(
            split_name, uids, splits_dir=Path(args.splits_dir) if args.splits_dir else None
        )

    telemetry_dir = Path(args.telemetry_dir) if args.telemetry_dir else TELEMETRY_ROOT / method
    results_dir = PROJECT_ROOT / "results" / method

    print(f"# phase2 report ablation: arm={args.arm} agent={agent_name} backend={backend}")
    print(f"  split={split_name} subset_split={subset_split} n={len(uids)} seed={args.seed} "
          f"fold={args.fold}/{args.folds}")
    print(f"  model={model} call_timeout={args.call_timeout_sec}s max_calls={args.max_calls} "
          f"budget={args.budget_sec}s workers={args.workers}")
    print(f"  method={method} -> results/{method}/<uid>.json")
    if backend == "stub":
        print("  NOTE: stub backend -- offline plumbing self-test, NOT a reportable arm.")
    print("  NOTE: this is a SCREEN (reduced subset/budget, one repeat), never a promotion row.\n",
          flush=True)

    if args.dry_run:
        print(f"dry run: would solve {len(uids)} queries: {uids[:5]}{' ...' if len(uids) > 5 else ''}")
        return 0

    # Load from the *original* split, never from the materialized subset: the subset file exists
    # only so eval_tpc.py scores exactly these uids, and (with --splits-dir) it may not even live
    # where upstream's loader looks. Loading the source split and filtering keeps the run
    # independent of where the subset file was written.
    lang_used, all_queries = load_visible_queries(split_name, args.lang)
    missing = [uid for uid in uids if uid not in all_queries]
    if missing:
        print(f"Split {split_name!r} is missing {len(missing)} selected uid(s): {missing[:3]}",
              file=sys.stderr)
        return 2
    queries = {uid: all_queries[uid] for uid in uids}

    config = ArmConfig(
        arm=args.arm,
        agent=agent_name,
        lang=lang_used,
        model=model,
        llm_backend=backend,
        base_url=args.base_url,
        max_steps=args.max_steps,
        budget_sec=args.budget_sec,
        call_timeout_sec=args.call_timeout_sec,
        max_calls=args.max_calls,
        retries=args.retries,
        max_tokens=args.max_tokens,
        enable_thinking=args.enable_thinking,
        results_dir=str(results_dir),
        telemetry_dir=str(telemetry_dir),
        cache_dir=str(PROJECT_ROOT / "cache" / "report_ablations" / method),
        log_dir=str(PROJECT_ROOT / "cache" / "report_ablations" / method / "logs"),
        load_translation_cache=args.load_translation_cache,
        debug=args.debug,
    )

    done = 0

    def _progress(record: dict[str, Any]) -> None:
        nonlocal done
        done += 1
        print(
            f"[{done}/{len(uids)}] {record['uid']} ok={record.get('ok')} "
            f"calls={record.get('llm_calls')} wall={record.get('wall_sec')}s "
            f"{('err=' + str(record.get('error'))) if record.get('error') else ''}",
            flush=True,
        )

    started = time.perf_counter()
    records = run_arm(config, queries, uids, workers=args.workers, progress=_progress)
    wall = time.perf_counter() - started

    summary = summarize(
        records,
        base={
            "arm": args.arm,
            "agent": agent_name,
            "model": model,
            "llm_backend": backend,
            "lang": lang_used,
            "split": split_name,
            "subset_split": subset_split,
            "n_requested": len(uids),
            "seed": args.seed,
            "fold": args.fold,
            "folds": args.folds,
            "method": method,
            "results_dir": str(results_dir),
            "telemetry_dir": str(telemetry_dir),
            "max_steps": args.max_steps,
            "max_calls": args.max_calls,
            "call_timeout_sec": args.call_timeout_sec,
            "budget_sec": args.budget_sec,
            "workers": args.workers,
            "enable_thinking": bool(args.enable_thinking),
            "load_translation_cache": bool(args.load_translation_cache),
            "run_wall_sec": round(wall, 1),
            "measurement_kind": "screen",
        },
        price_in=args.price_in_per_mtok,
        price_out=args.price_out_per_mtok,
    )
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    (telemetry_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    _print_summary(summary)
    print(f"\nwrote {telemetry_dir / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
