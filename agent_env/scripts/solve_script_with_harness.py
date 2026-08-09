#!/usr/bin/env python3
"""Solve ChinaTravel queries with a non-interactive agent harness and evaluate them.

This is the organizer-confirmed Phase 2 entry point. The evaluation host runs, from the root of
the submitted package (organizers' 2026-08-06 clarification):

    python agent_env/scripts/solve_script_with_harness.py --method <method> --split <split>

Both values come from the command line and neither may be hard-coded: ``--split`` names the
held-out split to load, ``--method`` names the output directory, and every plan must land at
``results/<method>/<uid>.json``. Nothing else is passed, so this invocation must be the whole
submission. It therefore defaults to ``--harness tpc``: this repository's deterministic,
no-oracle ``TPCAgent`` solver, run in-process, making zero LLM calls and zero subprocess calls.
The external-CLI harnesses (``opencode``, ``codex``) remain available for the LLM-agent baseline
comparison, but only when asked for explicitly with ``--harness``.

The held-out queries carry no DSL, constraint-code, ground-truth or verifier-only field
(``hard_logic``, ``hard_logic.py``, ``hard_logic_py``, ``hard_logic_nl``, ...). Every path here
therefore treats those fields as optional: they are stripped from anything the agent sees
(``visible_query``) and their *absence* only disables the local oracle-side scoring convenience
(``evaluate_one``'s ``has_oracle``), never the solve.

Under ``--harness tpc`` the run is also bounded by a whole-run wall-clock envelope (the
organizers' confirmed 5 hours for 100 queries) rather than by a fixed per-query budget; see
``solve_phase2.query_budget_sec``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from typing import Any

# Wall-clock zero for the organizer envelope: interpreter startup, imports, and the WorldEnv /
# database load all run inside the organizers' 5 hours, so the clock starts here rather than at
# the first solve.
PROCESS_START_MONOTONIC = time.monotonic()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "agent_env" / "config.toml"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# The verifier-only fields the organizers named (2026-08-06). They are absent from the formal
# held-out data; this set exists so a *local* run on released data hides them just the same. The
# ``hard_logic`` prefix rule below is what actually makes the guard exhaustive -- the explicit set
# is the documented list, not the mechanism.
HIDDEN_QUERY_KEYS = {"hard_logic", "hard_logic.py", "hard_logic_py", "hard_logic_nl"}

# ``tpc`` is this repository's own deterministic solver and the default; the other two shell out
# to an external CLI and are opt-in only.
TPC_HARNESS = "tpc"
EXTERNAL_HARNESSES = ("opencode", "codex")
HARNESS_CHOICES = (TPC_HARNESS,) + EXTERNAL_HARNESSES
DEFAULT_HARNESS = TPC_HARNESS


def _is_oracle_query_key(key: object) -> bool:
    return isinstance(key, str) and (
        key in HIDDEN_QUERY_KEYS or key.startswith("hard_logic")
    )


OUTPUT_OPEN_TAG = "<output>"
OUTPUT_CLOSE_TAG = "</output>"


def default_tool_python() -> str:
    return "uv run python"


def normalize_lang(lang: Any) -> str:
    value = str(lang).lower()
    if value not in {"zh", "en"}:
        raise ValueError("ChinaTravel language must be 'zh' or 'en'.")
    return value


def _load_queries_for_lang(split: str, lang: str) -> tuple[list[str], dict[str, Any]]:
    from chinatravel.data.load_datasets import load_query

    args = argparse.Namespace(
        splits=split,
        lang=lang,
        oracle_translation=True,
    )
    query_ids, query_data = load_query(args)
    if not query_ids:
        raise RuntimeError(f"No queries found for split: {split}")
    return query_ids, query_data


DEFAULT_SPLITS_DIR = PROJECT_ROOT / "chinatravel" / "evaluation" / "default_splits"


def available_splits() -> list[str]:
    """Split names this tree can name on the command line, for use in error messages only.

    A split is nameable when ``default_splits/<name>.txt`` exists. That file is necessary but not
    sufficient -- the query JSON must also be present -- so this list is a hint for a human who
    mistyped a name, never a validation whitelist. The held-out split the organizers pass is not
    in this tree at packaging time and must keep working, which is exactly why nothing here may
    reject a name that is missing from the list.
    """
    try:
        names = sorted(
            path.stem
            for path in DEFAULT_SPLITS_DIR.glob("*.txt")
            if not path.stem.endswith("_suboptimal")
        )
    except OSError:
        return []
    return names


def _abbreviate(text: object, limit: int = 400) -> str:
    """Shorten a loader error so the actionable first line is not buried.

    Upstream's resolver embeds every missing UID in its message; on a 300-query split that is
    thousands of characters of noise around one sentence that matters.
    """
    value = str(text)
    if len(value) <= limit:
        return value
    return value[:limit] + f"... [{len(value) - limit} more chars]"


def _is_split_resolution_failure(exc: BaseException) -> bool:
    """Is ``exc`` "this split is not in this language tree", as opposed to "this data is broken"?

    Only the former may trigger the cross-language retry below. The distinction matters because
    the two failures want opposite handling: a split that lives in the other tree should be found
    there, while a corrupt query file or an unreadable directory must surface as itself rather
    than be papered over by silently solving a *different* dataset.

    - ``FileNotFoundError`` -- the split's ``default_splits/<split>.txt`` or one of its query files
      is not in this tree. (Deliberately not ``OSError``: ``PermissionError`` and friends are
      environment faults, not resolution answers.)
    - ``ValueError`` -- upstream's ``_resolve_local_query_paths`` raises it for "unable to resolve
      local split" and "does not contain every configured UID", and ``load_query_local`` for a UID
      mismatch. ``json.JSONDecodeError`` subclasses ``ValueError`` and is excluded by name: a query
      file that exists but is malformed is broken data, not a wrong tree.
    - ``RuntimeError`` -- ``_load_queries_for_lang``'s own "no queries found" guard.

    Anything else (an HF ``datasets`` error on the ``zh`` path, an ``OSError``, an import failure)
    propagates unchanged.
    """
    if isinstance(exc, json.JSONDecodeError):
        return False
    return isinstance(exc, (FileNotFoundError, ValueError, RuntimeError))


def load_queries_with_lang(
    split: str, lang: str
) -> tuple[str, list[str], dict[str, Any]]:
    """Load ``split``, falling back to the other language if ``lang`` does not *resolve* it.

    Returns the language actually used, so the caller can build ``WorldEnv`` and the evaluators
    to match the queries it got rather than the language it asked for.

    Upstream's loader looks for an ``en`` split under ``chinatravel/data/en/`` and a ``zh`` one
    under ``chinatravel/data/``, and raises when the split is in neither. The organizers give us
    the split *name* on the command line but not which of those two trees their held-out queries
    land in, and an unresolved split is the single worst failure available to us: no plans at all,
    a zero for the whole run. So try the other language before giving up, and report both
    failures if neither resolves.

    The retry is limited to resolution failures (``_is_split_resolution_failure``). A broken query
    file or an unreadable tree raises as itself: falling back there would mask a real data fault
    *and* silently solve a different dataset than the one that was asked for.

    Costs nothing when the split resolves normally -- the fallback is only reached on the path
    that was previously an immediate crash.
    """
    lang = normalize_lang(lang)
    try:
        query_ids, query_data = _load_queries_for_lang(split, lang)
        return lang, query_ids, query_data
    except Exception as primary:
        if not _is_split_resolution_failure(primary):
            raise
        other = "zh" if lang == "en" else "en"
        try:
            query_ids, query_data = _load_queries_for_lang(split, other)
        except Exception as secondary:
            hint = ", ".join(available_splits()) or "(none found)"
            raise RuntimeError(
                f"Split {split!r} did not resolve in either language, so there is nothing to "
                f"solve. Check that chinatravel/evaluation/default_splits/{split}.txt exists and "
                f"that its query JSON files are present under chinatravel/data/en/ (--lang en) or "
                f"chinatravel/data/ (--lang zh).\n"
                f"  lang={lang}: {_abbreviate(primary)}\n"
                f"  lang={other}: {_abbreviate(secondary)}\n"
                f"  splits nameable in this tree: {hint}"
            ) from primary
        print(
            f"warning: split {split!r} did not resolve at lang={lang} ({primary}); "
            f"loaded {len(query_ids)} queries at lang={other} instead."
        )
        return other, query_ids, query_data


def load_queries(split: str, lang: str) -> tuple[list[str], dict[str, Any]]:
    _, query_ids, query_data = load_queries_with_lang(split, lang)
    return query_ids, query_data


def load_one_query(
    split: str, uid: str | None, lang: str = "en"
) -> tuple[str, dict[str, Any]]:
    query_ids, query_data = load_queries(split, lang)
    query_uid = uid or query_ids[0]
    if query_uid not in query_data:
        raise RuntimeError(f"Query uid {query_uid!r} not found in split {split!r}")
    return query_uid, query_data[query_uid]


def visible_query(query: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in query.items() if not _is_oracle_query_key(key)}


def json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=json_default),
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        raise ValueError("Cannot pass null as a Codex -c value.")
    return str(value)


def output_source_name(harness: str) -> str:
    if harness == TPC_HARNESS:
        return "TPCAgent"
    return "Codex" if harness == "codex" else "OpenCode"


def extract_tagged_output(text: str) -> str:
    match = re.search(
        r"<output>\s*(.*?)\s*</output>", text, flags=re.DOTALL | re.IGNORECASE
    )
    if not match:
        preview = text.strip()[:500].replace("\n", "\\n")
        raise ValueError(
            f"Agent output did not contain <output>...</output>. Preview: {preview!r}"
        )
    return match.group(1).strip()


def repair_json_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end >= start:
        stripped = stripped[start : end + 1]
    return re.sub(r",(\s*[}\]])", r"\1", stripped)


def extract_json_object(
    text: str, *, require_tags: bool = False, source_name: str = "Agent"
) -> dict[str, Any]:
    stripped = extract_tagged_output(text) if require_tags else text.strip()
    try:
        value = json.loads(repair_json_text(stripped))
    except json.JSONDecodeError:
        preview = stripped[:500].replace("\n", "\\n")
        raise ValueError(
            f"{source_name} output did not contain parseable JSON. Preview: {preview!r}"
        ) from None
    if not isinstance(value, dict):
        raise ValueError(f"{source_name} output was valid JSON but not a JSON object.")
    return value


def load_plan_from_output_txt(
    output_txt_path: Path, require_tags: bool, source_name: str
) -> dict[str, Any]:
    return extract_json_object(
        output_txt_path.read_text(encoding="utf-8"),
        require_tags=require_tags,
        source_name=source_name,
    )


def build_prompt(
    split: str,
    uid: str,
    query: dict[str, Any],
    tool_python: str,
    lang: str,
) -> str:
    query_text = json.dumps(query, ensure_ascii=False, indent=2)
    cli_python = f"{tool_python} -m agent_env.cli --lang {lang}"
    return f"""You are solving one ChinaTravel benchmark query.

Work quietly. Do not narrate your plan, progress, or calculations. Use CLI calls only
to gather exact facts. Keep the itinerary relaxed and simple. After gathering enough
facts, immediately return the final JSON object between {OUTPUT_OPEN_TAG} and {OUTPUT_CLOSE_TAG}.

Use the local CLI API to inspect the environment. The repository root is:
{PROJECT_ROOT}

Run CLI commands from that repository root using this Python command:
{tool_python}

Use this command for every `agent_env.cli` call. Do not use bare `python`.

Important commands:
- {cli_python} tools
- {cli_python} call attractions_keys '{{"city":"<target_city>"}}'
- {cli_python} call restaurants_keys '{{"city":"<target_city>"}}'
- {cli_python} call accommodations_keys '{{"city":"<target_city>"}}'
- {cli_python} call intercity_transport_select '{{"start_city":"<start_city>","end_city":"<target_city>","intercity_type":"train","earliest_leave_time":"07:00"}}'
- {cli_python} call goto '{{"city":"<target_city>","start":"<exact start>","end":"<exact end>","start_time":"HH:MM","transport_type":"metro"}}'

Use exact names, prices, costs, times, distances, TrainID/FlightID values, and transport
segments returned by the CLI. Do not invent environment facts.

Output the JSON result between these tags:
{OUTPUT_OPEN_TAG}
{{...valid JSON matching chinatravel/evaluation/output_schema.json...}}
{OUTPUT_CLOSE_TAG}

Split: {split}
UID: {uid}
Visible query:
{query_text}
"""


def provider_model_name(model: str, provider_id: str) -> str:
    prefix = f"{provider_id}/"
    if model.startswith(prefix):
        return model[len(prefix) :]
    if "/" in model:
        return model.rsplit("/", 1)[1]
    return model


def build_opencode_config(opencode_config: dict[str, Any], model: str) -> dict[str, Any]:
    provider = opencode_config.get("provider", {})
    if not isinstance(provider, dict):
        raise ValueError("Config section [opencode.provider] must be a table.")

    provider_id = str(provider.get("id") or "dashscope")
    model_id = provider_model_name(model, provider_id)
    api_key_env = str(opencode_config.get("api_key_env") or "DASHSCOPE_API_KEY")

    provider_options: dict[str, Any] = {
        "baseURL": str(provider.get("base_url") or provider.get("baseURL") or ""),
        "apiKey": f"{{env:{api_key_env}}}",
    }
    extra_options = provider.get("options", {})
    if isinstance(extra_options, dict):
        provider_options.update(extra_options)
    if not provider_options["baseURL"]:
        raise ValueError("[opencode.provider].base_url is required.")

    model_config: dict[str, Any] = {
        "name": str(provider.get("model_name") or model_id),
        "tool_call": bool(provider.get("tool_call", True)),
    }
    model_options = provider.get("model_options", {})
    if isinstance(model_options, dict):
        model_config["options"] = model_options

    return {
        "$schema": "https://opencode.ai/config.json",
        "provider": {
            provider_id: {
                "npm": str(provider.get("npm") or "@ai-sdk/openai-compatible"),
                "name": str(provider.get("name") or provider_id),
                "options": provider_options,
                "models": {model_id: model_config},
            }
        },
        "model": model if "/" in model else f"{provider_id}/{model}",
    }


def apply_opencode_env(env: dict[str, str], opencode_config: dict[str, Any]) -> None:
    api_key = opencode_config.get("api_key")
    api_key_env = str(opencode_config.get("api_key_env") or "DASHSCOPE_API_KEY")
    if api_key:
        env[api_key_env] = str(api_key)


def extract_opencode_text(stdout: str) -> str:
    text_parts = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "text":
            continue
        part = event.get("part", {})
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            text_parts.append(part["text"])
    if not text_parts and stdout.strip():
        return stdout.strip()
    return "".join(text_parts).strip()


def extract_opencode_error(stdout: str) -> str | None:
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "error":
            continue
        error = event.get("error")
        if isinstance(error, dict):
            data = error.get("data")
            if isinstance(data, dict) and data.get("message"):
                return str(data["message"])
            if error.get("message"):
                return str(error["message"])
            return json.dumps(error, ensure_ascii=False, default=json_default)
        if error:
            return str(error)
        return "OpenCode emitted an error event."
    return None


def run_opencode(
    prompt: str,
    run_dir: Path,
    output_txt_path: Path,
    model: str | None,
    timeout: int,
    opencode_config: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    if not model:
        raise ValueError("[opencode].model is required.")

    opencode_json_path = run_dir / "opencode.json"
    write_json(opencode_json_path, build_opencode_config(opencode_config, str(model)))

    cmd = [
        "opencode",
        "run",
        "--dir",
        str(PROJECT_ROOT),
        "--model",
        str(model),
        "--format",
        "json",
    ]
    if bool(opencode_config.get("dangerously_skip_permissions", True)):
        cmd.append("--dangerously-skip-permissions")
    agent = opencode_config.get("agent")
    if agent:
        cmd.extend(["--agent", str(agent)])
    variant = opencode_config.get("variant")
    if variant:
        cmd.extend(["--variant", str(variant)])
    cmd.append(prompt)

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["OPENCODE_CONFIG"] = str(opencode_json_path)
    apply_opencode_env(env, opencode_config)
    completed = subprocess.run(
        cmd,
        cwd=run_dir,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    opencode_error = extract_opencode_error(completed.stdout)
    if opencode_error:
        stderr = completed.stderr
        if stderr:
            stderr = f"{stderr.rstrip()}\n{opencode_error}\n"
        else:
            stderr = f"{opencode_error}\n"
        return subprocess.CompletedProcess(
            completed.args, completed.returncode or 1, completed.stdout, stderr
        )
    if completed.returncode == 0:
        output_txt_path.write_text(
            extract_opencode_text(completed.stdout), encoding="utf-8"
        )
    return completed


def apply_codex_env(env: dict[str, str], codex_config: dict[str, Any]) -> None:
    api_key = codex_config.get("api_key")
    api_key_env = codex_config.get("api_key_env")
    provider = codex_config.get("provider", {})
    if not isinstance(provider, dict):
        provider = {}
    env_key = str(provider.get("env_key") or api_key_env or "OPENAI_API_KEY")
    if api_key:
        env[env_key] = str(api_key)


def build_codex_config_overrides(codex_config: dict[str, Any]) -> list[tuple[str, Any]]:
    overrides: list[tuple[str, Any]] = []

    provider = codex_config.get("provider", {})
    if isinstance(provider, dict) and provider:
        provider_id = provider.get("id")
        if provider_id:
            provider_id = str(provider_id)
            overrides.append(("model_provider", provider_id))
            provider_keys = {
                "name": provider.get("name"),
                "base_url": provider.get("base_url"),
                "env_key": provider.get("env_key") or codex_config.get("api_key_env"),
                "wire_api": provider.get("wire_api"),
            }
            for key, value in provider_keys.items():
                if value is not None:
                    overrides.append((f"model_providers.{provider_id}.{key}", value))

    extra_config = codex_config.get("extra_config", {})
    if isinstance(extra_config, dict):
        for key, value in extra_config.items():
            overrides.append((str(key), value))

    return overrides


def run_codex(
    prompt: str,
    run_dir: Path,
    output_txt_path: Path,
    model: str | None,
    timeout: int,
    codex_config: dict[str, Any],
) -> subprocess.CompletedProcess[str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(run_dir),
        "--add-dir",
        str(PROJECT_ROOT),
        "--sandbox",
        str(codex_config.get("sandbox") or "workspace-write"),
        "--output-last-message",
        str(output_txt_path),
    ]
    output_schema = bool(codex_config.get("output_schema", False))
    if output_schema:
        cmd.extend(
            [
                "--output-schema",
                str(PROJECT_ROOT / "chinatravel" / "evaluation" / "output_schema.json"),
            ]
        )
    if model:
        cmd.extend(["--model", model])
    for key, value in build_codex_config_overrides(codex_config):
        cmd.extend(["--config", f"{key}={toml_value(value)}"])
    cmd.append("-")

    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    apply_codex_env(env, codex_config)
    return subprocess.run(
        cmd,
        cwd=run_dir,
        env=env,
        text=True,
        input=prompt,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def evaluate_one(
    split: str,
    uid: str,
    query: dict[str, Any],
    plan: dict[str, Any],
    lang: str = "en",
) -> dict[str, Any]:
    from chinatravel.evaluation.commonsense_constraint import (
        evaluate_commonsense_constraints,
    )
    from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
    from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
    from chinatravel.agent.tpc_agent.parsed_verifier import evaluate_parsed_constraints
    from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants
    from chinatravel.symbol_verification.concept_func import func_dict
    from chinatravel.evaluation.utils import load_json_file
    import parse_constraints
    from copy import deepcopy

    query_index = [uid]
    query_data = {uid: query}
    result_data = {uid: plan}
    schema = load_json_file(
        str(PROJECT_ROOT / "chinatravel" / "evaluation" / "output_schema.json")
    )

    # Official (oracle) scoring needs hard_logic_py, which is only present for benchmark queries
    # (always true for split-loaded oracle_translation=True queries, but not for a caller-supplied
    # query file/NL string without it). Gate the true-side computation on the *key's presence*, not
    # truthiness: a query with hard_logic_py=[] still has an oracle (a vacuously-true one) and must
    # keep scoring that way, matching pre-existing split-run behavior exactly.
    has_oracle = "hard_logic_py" in query

    schema_rate, schema_result_agg, schema_pass_id = evaluate_schema_constraints(
        query_index, result_data, schema=schema
    )
    macro_comm, micro_comm, common_result_agg, commonsense_pass_id = (
        evaluate_commonsense_constraints(
            query_index, query_data, result_data, verbose=False, lang=lang
        )
    )
    if has_oracle:
        (
            macro_logi,
            micro_logi,
            conditional_macro_logi,
            conditional_micro_logi,
            logi_result_agg,
            logi_pass_id,
        ) = evaluate_hard_constraints_v2(
            query_index,
            query_data,
            result_data,
            env_pass_id=commonsense_pass_id,
            verbose=False,
            lang=lang,
        )
    else:
        macro_logi = micro_logi = conditional_macro_logi = conditional_micro_logi = None
        logi_result_agg = None
        logi_pass_id = []

    parsed_raw = parse_constraints.parse_query_no_oracle(query)
    parsed_variants = solver_constraint_variants(query, parsed_raw, use_oracle=False)
    parsed_constraints = parsed_variants[0] if parsed_variants else {}
    parsed_results = evaluate_parsed_constraints(
        parsed_constraints,
        plan,
        query.get("target_city", ""),
    )
    parsed_total = len(parsed_results)
    parsed_succ = sum(1 for r in parsed_results if bool(r))
    parsed_logical_micro = (100.0 * parsed_succ / parsed_total) if parsed_total else 100.0
    parsed_logical_macro = 100.0 if parsed_succ == parsed_total else 0.0
    commonsense_pass = uid in commonsense_pass_id
    parsed_conditional_micro = parsed_logical_micro if commonsense_pass else 0.0
    parsed_conditional_macro = parsed_logical_macro if commonsense_pass else 0.0
    parsed_logical_pass = parsed_succ == parsed_total

    schema_pass = uid in schema_pass_id
    true_logical_pass = (uid in logi_pass_id) if has_oracle else None
    all_pass_true = (
        (schema_pass and commonsense_pass and true_logical_pass) if has_oracle else None
    )
    all_pass_parsed = schema_pass and commonsense_pass and parsed_logical_pass

    def _default_pr_scores(is_all_pass: bool) -> tuple[float, float, float]:
        if not is_all_pass:
            return 0.0, 0.0, 0.0

        def clamp(value: Any) -> float:
            try:
                return max(0.0, min(1.0, float(value)))
            except Exception:
                return 0.0

        default_pr = [
            """
attraction_count = 0
for activity in allactivities(plan):
    if activity_type(activity) == 'attraction':
        attraction_count += 1
result=attraction_count/(4*day_count(plan))
""",
            """
time_cost = 0
transport_count = 0
for activity in allactivities(plan):
    transports = activity_transports(activity)
    if transports!=[]:
        transport_count += 1
        time_cost += innercity_transport_time(transports)
if transport_count > 0:
    average_time_cost = time_cost / transport_count
    result= (-1/105) * average_time_cost + 8/7
else:
    result=0
""",
            """
res_count=0
for activity in allactivities(plan):
    if activity_type(activity) in ['breakfast', 'lunch', 'dinner']:
        res_count+=1
res_count=res_count/(day_count(plan))
result=res_count/3
""",
        ]

        scores: list[float] = []
        for constraint in default_pr:
            vars_dict = deepcopy(func_dict)
            vars_dict["plan"] = plan
            try:
                exec(constraint, {"__builtins__": {"set": set}}, vars_dict)
                scores.append(clamp(vars_dict.get("result", 0.0)))
            except Exception:
                scores.append(0.0)
        return scores[0] * 100.0, scores[1] * 100.0, scores[2] * 100.0

    if has_oracle:
        dav_true, att_true, ddr_true = _default_pr_scores(all_pass_true)
        fpr_true = 100.0 if all_pass_true else 0.0
        # Aligned with eval_tpc.py: 0.1*MicEPR + 0.1*MacEPR + 0.25*C-LPR + 0.05*DAV + 0.05*ATT + 0.05*DDR + 0.4*FPR
        overall_true = (
            0.1 * micro_comm
            + 0.1 * macro_comm
            + 0.25 * conditional_micro_logi
            + 0.05 * dav_true
            + 0.05 * att_true
            + 0.05 * ddr_true
            + 0.4 * fpr_true
        )
    else:
        dav_true = att_true = ddr_true = fpr_true = overall_true = None
    dav_parsed, att_parsed, ddr_parsed = _default_pr_scores(all_pass_parsed)

    fpr_parsed = 100.0 if all_pass_parsed else 0.0

    overall_parsed = (
        0.1 * micro_comm
        + 0.1 * macro_comm
        + 0.25 * parsed_conditional_micro
        + 0.05 * dav_parsed
        + 0.05 * att_parsed
        + 0.05 * ddr_parsed
        + 0.4 * fpr_parsed
    )

    return {
        "split": split,
        "uid": uid,
        "has_oracle": has_oracle,
        "schema_pass": schema_pass,
        "commonsense_pass": commonsense_pass,
        "logical_pass": true_logical_pass,
        "all_pass": all_pass_true,
        "schema_rate": schema_rate,
        "commonsense_micro": micro_comm,
        "commonsense_macro": macro_comm,
        "logical_micro": micro_logi,
        "logical_macro": macro_logi,
        "conditional_logical_micro": conditional_micro_logi,
        "conditional_logical_macro": conditional_macro_logi,
        "parsed_constraints_total": parsed_total,
        "parsed_constraints_satisfied": parsed_succ,
        "parsed_logical_pass": parsed_logical_pass,
        "parsed_logical_micro": parsed_logical_micro,
        "parsed_logical_macro": parsed_logical_macro,
        "conditional_parsed_logical_micro": parsed_conditional_micro,
        "conditional_parsed_logical_macro": parsed_conditional_macro,
        "all_pass_parsed": all_pass_parsed,
        "dav_true": dav_true,
        "att_true": att_true,
        "ddr_true": ddr_true,
        "fpr_true": fpr_true,
        "overall_true": overall_true,
        "dav_parsed": dav_parsed,
        "att_parsed": att_parsed,
        "ddr_parsed": ddr_parsed,
        "fpr_parsed": fpr_parsed,
        "overall_parsed": overall_parsed,
        "schema_details": schema_result_agg.to_dict(orient="records"),
        "commonsense_details": common_result_agg.to_dict(orient="records"),
        "logical_details": (
            logi_result_agg.to_dict(orient="records") if has_oracle else []
        ),
        "parsed_constraints_eval": {
            "checks": [bool(r) for r in parsed_results],
            "constraints": parsed_constraints,
        },
    }


def evaluate_split(
    split: str,
    method: str,
    query_ids: list[str],
    query_data: dict[str, Any],
    lang: str = "en",
    parse_failure_ids: list[str] | None = None,
) -> dict[str, Any]:
    from chinatravel.evaluation.commonsense_constraint import (
        evaluate_commonsense_constraints,
    )
    from chinatravel.evaluation.hard_constraint import evaluate_hard_constraints_v2
    from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
    from chinatravel.evaluation.utils import load_json_file

    result_dir = PROJECT_ROOT / "results" / method
    parse_failure_ids = parse_failure_ids or []
    parse_failure_set = set(parse_failure_ids)
    result_data = {}
    evaluated_ids = []
    for uid in query_ids:
        if uid in parse_failure_set:
            continue
        result_path = result_dir / f"{uid}.json"
        if result_path.exists():
            result_data[uid] = read_json(result_path)
            evaluated_ids.append(uid)

    if evaluated_ids:
        schema = load_json_file(
            str(PROJECT_ROOT / "chinatravel" / "evaluation" / "output_schema.json")
        )
        schema_rate, schema_result_agg, schema_pass_id = evaluate_schema_constraints(
            evaluated_ids, result_data, schema=schema
        )
        macro_comm, micro_comm, common_result_agg, commonsense_pass_id = (
            evaluate_commonsense_constraints(
                evaluated_ids, query_data, result_data, verbose=False, lang=lang
            )
        )
        (
            macro_logi,
            micro_logi,
            conditional_macro_logi,
            conditional_micro_logi,
            logi_result_agg,
            logi_pass_id,
        ) = evaluate_hard_constraints_v2(
            evaluated_ids,
            query_data,
            result_data,
            env_pass_id=commonsense_pass_id,
            verbose=False,
            lang=lang,
        )
        schema_details = schema_result_agg.to_dict(orient="records")
        commonsense_details = common_result_agg.to_dict(orient="records")
        logical_details = logi_result_agg.to_dict(orient="records")
    else:
        schema_rate = macro_comm = micro_comm = 0
        macro_logi = micro_logi = conditional_macro_logi = conditional_micro_logi = 0
        schema_pass_id = []
        commonsense_pass_id = []
        logi_pass_id = []
        schema_details = []
        commonsense_details = []
        logical_details = []

    for failed_uid in parse_failure_ids:
        schema_details.append(
            {"data_id": failed_uid, "schema": 0, "parse_failure": True}
        )
        commonsense_details.append({"data_id": failed_uid, "parse_failure": True})
        logical_details.append({"data_id": failed_uid, "parse_failure": True})

    all_pass = set(schema_pass_id) & set(commonsense_pass_id) & set(logi_pass_id)
    parsed_count = len(evaluated_ids)
    parse_failure_count = len(parse_failure_ids)
    evaluated_count = parsed_count + parse_failure_count
    pass_rate_scale = parsed_count / evaluated_count if evaluated_count else 0
    return {
        "split": split,
        "method": method,
        "evaluated": evaluated_count,
        "parsed_evaluated": parsed_count,
        "parse_failures": parse_failure_count,
        "schema_pass_count": len(schema_pass_id),
        "commonsense_pass_count": len(commonsense_pass_id),
        "logical_pass_count": len(logi_pass_id),
        "all_pass_count": len(all_pass),
        "all_pass_ids": sorted(all_pass),
        "schema_rate": schema_rate * pass_rate_scale,
        "commonsense_micro": micro_comm * pass_rate_scale,
        "commonsense_macro": macro_comm * pass_rate_scale,
        "logical_micro": micro_logi * pass_rate_scale,
        "logical_macro": macro_logi * pass_rate_scale,
        "conditional_logical_micro": conditional_micro_logi * pass_rate_scale,
        "conditional_logical_macro": conditional_macro_logi * pass_rate_scale,
        "schema_details": schema_details,
        "commonsense_details": commonsense_details,
        "logical_details": logical_details,
    }


def failed_evaluation(split: str, uid: str, reason: str) -> dict[str, Any]:
    return {
        "split": split,
        "uid": uid,
        "schema_pass": False,
        "commonsense_pass": False,
        "logical_pass": False,
        "all_pass": False,
        "schema_rate": 0,
        "commonsense_micro": 0,
        "commonsense_macro": 0,
        "logical_micro": 0,
        "logical_macro": 0,
        "conditional_logical_micro": 0,
        "conditional_logical_macro": 0,
        "schema_details": [{"data_id": uid, "schema": 0}],
        "commonsense_details": [{"data_id": uid}],
        "logical_details": [{"data_id": uid}],
        "parse_failure": True,
        "failure_reason": reason,
    }


def config_section(config: dict[str, Any], name: str) -> dict[str, Any]:
    section = config.get(name, {})
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise ValueError(f"Config section [{name}] must be a table.")
    return section


def choose(cli_value: Any, config_value: Any, default: Any) -> Any:
    if cli_value is not None:
        return cli_value
    if config_value is not None:
        return config_value
    return default


def choose_nonempty(cli_value: Any, config_value: Any, default: Any) -> Any:
    value = choose(cli_value, config_value, default)
    if isinstance(value, str) and not value.strip():
        return default
    return value


def method_model_name(model: str | None) -> str:
    if not model:
        return "model"
    return provider_model_name(str(model), str(model).split("/", 1)[0])


def safe_path_component(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return sanitized.strip("_") or "unnamed"


def validate_method(method: str) -> str:
    """Reject a ``--method`` that would write outside ``results/``. Returns it unchanged.

    Deliberately a *guard*, not a sanitizer. The organizers' contract is that each plan lands at
    ``results/<method>/<uid>.json`` for the ``<method>`` they passed, so rewriting the value would
    put plans where they will not be read -- the failure this validation exists to prevent, not a
    fix for it. Nesting is therefore allowed: ``--method a/b`` writes ``results/a/b/<uid>.json``,
    which *is* ``results/<method>/<uid>.json`` for that method.

    What cannot be honoured is a method that escapes ``results/`` altogether (``..`` components, an
    absolute path). There the required layout is unsatisfiable by construction, so fail loudly at
    startup -- before a 5-hour run writes a complete set of plans somewhere nobody will look.
    """
    results_root = (PROJECT_ROOT / "results").resolve()
    candidate = Path(method)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(
            f"--method {method!r} must name a location inside results/; plans have to land at "
            "results/<method>/<uid>.json."
        )
    try:
        target = (results_root / candidate).resolve()
        target.relative_to(results_root)
    except (ValueError, OSError) as exc:
        raise ValueError(
            f"--method {method!r} resolves outside results/, so plans could not be written to "
            f"results/<method>/<uid>.json ({exc})."
        ) from None
    return method


def default_method(model: str | None, split: str, harness: str) -> str:
    if harness == TPC_HARNESS:
        # No model to name (the deterministic path has none); reuse solve_phase2.py's method
        # convention so a harness run and a local `solve_phase2.py` run of the same split share
        # `results/<method>/` and resume each other.
        return f"phase2_e2e_{safe_path_component(split)}"
    return "-".join(
        [
            safe_path_component(method_model_name(model)),
            safe_path_component(split),
            safe_path_component(harness),
        ]
    )


def load_solve_phase2_module():
    """Import ``solve_phase2`` from this directory lazily.

    Lazy because ``solve_phase2`` imports *this* module for its evaluation helpers; importing it
    at module level would be circular. Also keeps the external-CLI harnesses free of the solver's
    import cost.
    """
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import solve_phase2  # noqa: PLC0415 (deliberately deferred; see docstring)

    return solve_phase2


def run_tpc_split(
    *,
    split: str,
    lang: str,
    method: str,
    uid: str | None,
    limit: int | None,
    resume: bool,
    budget_sec: float | None,
    total_budget_sec: float | None,
    workers: int | None,
    work_dir: str | None,
) -> dict[str, Any]:
    """Solve a split with the deterministic no-oracle solver, in-process.

    Writes the same official layout as every other harness (``results/<method>/<uid>.json``,
    plus per-query ``evaluation.json``/``telemetry.json`` and a split summary under
    ``<work_dir>/``). No subprocess, no LLM call, no network.

    ``total_budget_sec=None`` means "unspecified", which resolves to the organizers' confirmed
    5-hour envelope unless ``TPC_P2_TOTAL_BUDGET_SEC`` overrides it. Pass ``0`` to disable the
    envelope and use a fixed per-query budget instead.
    """
    sp2 = load_solve_phase2_module()
    if total_budget_sec is None and "TPC_P2_TOTAL_BUDGET_SEC" not in os.environ:
        total_budget_sec = sp2.DEFAULT_TOTAL_BUDGET_SEC
    total_budget_sec = sp2.resolve_total_budget_sec(total_budget_sec)
    return sp2.run_split(
        split,
        method=method,
        limit=limit,
        uid=uid,
        resume=resume,
        budget_sec=budget_sec,
        total_budget_sec=total_budget_sec,
        workers=workers,
        start_monotonic=PROCESS_START_MONOTONIC,
        lang=lang,
        work_dir=work_dir,
    )


def solve_query(
    *,
    harness: str,
    split: str,
    lang: str,
    uid: str,
    query: dict[str, Any],
    method: str,
    model: str | None,
    timeout: int,
    work_dir: str,
    harness_config: dict[str, Any],
    no_run_harness: bool,
    plan_file: str | None,
    tool_python: str,
    require_output_tags: bool,
) -> dict[str, Any] | None:
    public_query = visible_query(query)

    run_dir = PROJECT_ROOT / work_dir / f"{split}_{uid}"
    prompt_path = run_dir / "prompt.txt"
    output_txt_path = run_dir / "output.txt"
    output_json_path = run_dir / "output.json"
    eval_path = run_dir / "evaluation.json"
    result_path = PROJECT_ROOT / "results" / method / f"{uid}.json"

    prompt = build_prompt(split, uid, public_query, tool_python, lang)
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")

    print(f"Loaded query: split={split} uid={uid}")
    print(f"Prompt: {prompt_path}")

    if plan_file:
        plan = read_json(Path(plan_file))
    elif no_run_harness:
        print(f"Skipping {output_source_name(harness)} call because --no-run-harness was set.")
        return None
    else:
        if harness == "opencode":
            completed = run_opencode(
                prompt=prompt,
                run_dir=run_dir,
                output_txt_path=output_txt_path,
                model=model,
                timeout=timeout,
                opencode_config=harness_config,
            )
            stdout_path = run_dir / "opencode_stdout.jsonl"
            stderr_path = run_dir / "opencode_stderr.txt"
            failure_label = "opencode run"
        elif harness == "codex":
            completed = run_codex(
                prompt=prompt,
                run_dir=run_dir,
                output_txt_path=output_txt_path,
                model=model,
                timeout=timeout,
                codex_config=harness_config,
            )
            stdout_path = run_dir / "codex_stdout.txt"
            stderr_path = run_dir / "codex_stderr.txt"
            failure_label = "codex exec"
        else:
            raise ValueError(f"Unsupported harness: {harness}")

        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            raise RuntimeError(
                f"{failure_label} failed with exit code {completed.returncode}. "
                f"See {stdout_path} and {stderr_path}."
            )
        try:
            plan = load_plan_from_output_txt(
                output_txt_path,
                require_tags=require_output_tags,
                source_name=output_source_name(harness),
            )
        except ValueError as exc:
            (run_dir / "parse_error.txt").write_text(str(exc), encoding="utf-8")
            evaluation = failed_evaluation(split, uid, str(exc))
            write_json(eval_path, evaluation)
            print(
                f"{output_source_name(harness)} finished but did not produce a JSON plan. "
                f"See {output_txt_path}, {stdout_path}, {stderr_path}, and "
                f"{run_dir / 'parse_error.txt'}."
            )
            print(f"Marked parse failure as completely wrong: {eval_path}")
            print(
                json.dumps(
                    evaluation, ensure_ascii=False, indent=2, default=json_default
                )
            )
            return evaluation

    write_json(output_json_path, plan)
    write_json(result_path, plan)
    print(f"Saved plan: {result_path}")

    evaluation = evaluate_one(split, uid, query, plan, lang)
    write_json(eval_path, evaluation)
    print(f"Saved evaluation: {eval_path}")
    print(json.dumps(evaluation, ensure_ascii=False, indent=2, default=json_default))
    return evaluation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load a ChinaTravel split, solve it with a harness, and evaluate the output."
    )
    parser.add_argument(
        "--config", default=str(DEFAULT_CONFIG_PATH), help="TOML config path."
    )
    parser.add_argument(
        "--split",
        default=None,
        help=(
            "ChinaTravel split name to solve; the organizers pass the held-out split here. "
            "Overrides [run].split, which the submission archive deliberately leaves unset."
        ),
    )
    parser.add_argument(
        "--lang",
        choices=["zh", "en"],
        default=None,
        help="Query and sandbox language. Overrides [run].lang.",
    )
    parser.add_argument(
        "--uid", default=None, help="Optional query UID. Overrides [run].uid."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit split queries. Overrides [run].limit.",
    )
    parser.add_argument(
        "--method",
        default=None,
        help=(
            "Method name; plans are written to results/<method>/<uid>.json. Used verbatim, so "
            "the organizers' value decides the output directory. Overrides [run].method. "
            "Default: 'phase2_e2e_<split>' for --harness tpc, else <model>-<split>-<harness>."
        ),
    )
    parser.add_argument(
        "--harness",
        choices=list(HARNESS_CHOICES),
        default=None,
        help=(
            "Harness to run. Overrides [run].harness. Default 'tpc' is this repository's "
            "deterministic in-process solver; 'opencode'/'codex' shell out to an external CLI."
        ),
    )
    parser.add_argument(
        "--budget-sec",
        type=float,
        default=None,
        help="tpc harness only: per-query solve budget in seconds. Overrides [tpc].budget_sec.",
    )
    parser.add_argument(
        "--total-budget-sec",
        type=float,
        default=None,
        help=(
            "tpc harness only: whole-run wall-clock envelope in seconds (default: the "
            "organizers' confirmed 5 hours). <=0 disables it. Overrides [tpc].total_budget_sec."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            "tpc harness only: worker processes solving queries in parallel. "
            "Default: CPU count - 1. Overrides [tpc].workers."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional model override for the selected harness.",
    )
    parser.add_argument(
        "--opencode-model",
        default=None,
        help="Optional model passed to opencode run. Overrides [opencode].model.",
    )
    parser.add_argument(
        "--codex-model",
        default=None,
        help="Optional model passed to codex exec. Overrides [codex].model.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=None,
        help="OpenCode subprocess timeout in seconds.",
    )
    parser.add_argument(
        "--no-run-harness",
        action="store_true",
        default=None,
        help="Load the query and write the prompt, but do not call the harness.",
    )
    parser.add_argument(
        "--run-harness",
        action="store_false",
        dest="no_run_harness",
        help="Force the harness on when [run].no_run_harness is true.",
    )
    parser.add_argument(
        "--no-run-opencode",
        action="store_true",
        default=None,
        help="Deprecated alias for --no-run-harness.",
    )
    parser.add_argument(
        "--run-opencode",
        action="store_false",
        dest="no_run_opencode",
        help="Deprecated alias for --run-harness.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=None,
        help="Skip queries that already have result JSON files.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Do not skip existing result JSON files.",
    )
    parser.add_argument(
        "--plan-file",
        default=None,
        help="Evaluate an existing plan JSON. Overrides [run].plan_file.",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Directory for prompts, raw OpenCode output, and evaluation JSON.",
    )
    parser.add_argument(
        "--tool-python",
        default=None,
        help="Python command the harness should use for agent_env.cli. Overrides [run].tool_python.",
    )
    parser.add_argument(
        "--no-require-output-tags",
        action="store_true",
        default=None,
        help="Parse raw JSON without requiring <output> tags.",
    )
    return parser.parse_args()


def resolve_split_argument(
    cli_split: object, config_split: object, config_path: Path
) -> str:
    """Return the split to solve, or refuse to guess one.

    There used to be an ``"easy"`` fallback here. It was worse than no default at all: ``easy`` is
    an upstream split whose query JSON this archive does not ship, so an argument-less run spent
    its startup loading a WorldEnv and then died inside the loader -- a resolution error about a
    split nobody asked for. Whatever the caller meant, it was not that. Since the organizers always
    pass ``--split``, the only callers who reach this branch are humans who forgot it, and the
    useful thing to hand them is the command they meant to type.
    """
    # Not ``choose_nonempty``: that helper drops straight to the default when the CLI value is
    # blank, skipping the config. Here a blank ``--split ""`` should mean "I named nothing", so
    # each source is tried in turn and only a non-blank one counts.
    value = None
    for candidate in (cli_split, config_split):
        if candidate is None:
            continue
        text = str(candidate).strip()
        if text:
            value = text
            break

    if value is None:
        hint = ", ".join(available_splits()) or "(none found)"
        raise SystemExit(
            "error: no split selected.\n"
            "  Pass --split explicitly (this is what the evaluation host does):\n"
            "      python agent_env/scripts/solve_script_with_harness.py "
            "--method <method> --split <split>\n"
            "  for example:\n"
            "      python agent_env/scripts/solve_script_with_harness.py "
            "--method my_run --split tpc_phase2_test\n"
            f"  or set [run].split in {config_path} (the shipped config leaves it unset on "
            "purpose, so a command-line value is never overridden).\n"
            f"  Splits nameable in this tree: {hint}"
        )
    return value


def main() -> None:
    args = parse_args()
    config = read_config(Path(args.config))
    run_config = config_section(config, "run")
    harness = str(choose(args.harness, run_config.get("harness"), DEFAULT_HARNESS))
    if harness not in HARNESS_CHOICES:
        raise ValueError(f"Harness must be one of: {', '.join(HARNESS_CHOICES)}.")
    harness_config = config_section(config, harness)
    opencode_config = config_section(config, "opencode")
    codex_config = config_section(config, "codex")

    split = resolve_split_argument(args.split, run_config.get("split"), Path(args.config))
    lang = normalize_lang(choose(args.lang, run_config.get("lang"), "en"))
    uid = choose(args.uid, run_config.get("uid"), None)
    limit = choose(args.limit, run_config.get("limit"), None)

    if harness == TPC_HARNESS:
        method = validate_method(
            str(
                choose_nonempty(
                    args.method,
                    run_config.get("method"),
                    default_method(None, split, harness),
                )
            )
        )
        work_dir = str(
            choose_nonempty(
                args.work_dir, run_config.get("work_dir"), f"agent_env/runs/{method}"
            )
        )
        print(f"Config: {Path(args.config)}")
        print(
            f"Run: split={split} lang={lang} harness={harness} method={method} "
            "solver=deterministic TPCAgent (no LLM, no subprocess)"
        )
        # Echoed before the run, not just after it: the organizers' required output location is
        # results/<method>/<uid>.json, and a run that is killed mid-split still shows where it wrote.
        print(f"Results: {PROJECT_ROOT / 'results' / method}/<uid>.json")
        summary = run_tpc_split(
            split=split,
            lang=lang,
            method=method,
            uid=str(uid) if uid else None,
            limit=int(limit) if limit is not None else None,
            resume=bool(choose(args.resume, run_config.get("resume"), False)),
            budget_sec=choose(args.budget_sec, harness_config.get("budget_sec"), None),
            total_budget_sec=choose(
                args.total_budget_sec, harness_config.get("total_budget_sec"), None
            ),
            workers=choose(args.workers, harness_config.get("workers"), None),
            work_dir=work_dir,
        )
        print(f"\nSaved plans: {PROJECT_ROOT / 'results' / method}")
        # The summary's ``self_*`` numbers are the solver's own view of the plans it kept, not the
        # official score. Scoring them means pointing eval_tpc.py at the same --method, and getting
        # that pairing wrong reads as a flawless 0.0 rather than as a mistake -- so print the exact
        # command rather than leaving it to be reconstructed.
        print(
            "\nScore this run with (note --splits, and the same --method):\n"
            f"    python eval_tpc.py --splits {split} --method {method}"
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default))
        return

    if harness == "opencode":
        harness_model_arg = choose(args.model, args.opencode_model, None)
        selected_config = opencode_config
    else:
        harness_model_arg = choose(args.model, args.codex_model, None)
        selected_config = codex_config
    model = choose(harness_model_arg, selected_config.get("model"), None)
    method = validate_method(
        str(
            choose_nonempty(
                args.method,
                run_config.get("method"),
                default_method(model, split, harness),
            )
        )
    )
    timeout = int(choose(args.timeout, selected_config.get("timeout"), 900))
    work_dir = str(
        choose_nonempty(
            args.work_dir, run_config.get("work_dir"), f"agent_env/runs/{method}"
        )
    )
    tool_python = str(
        choose(args.tool_python, run_config.get("tool_python"), default_tool_python())
    )
    no_run_alias = choose(args.no_run_harness, args.no_run_opencode, None)
    no_run_harness = bool(
        choose(
            no_run_alias,
            choose(run_config.get("no_run_harness"), run_config.get("no_run_opencode"), None),
            False,
        )
    )
    resume = bool(choose(args.resume, run_config.get("resume"), False))
    plan_file = choose(args.plan_file, run_config.get("plan_file"), None)
    require_output_tags = bool(
        choose(
            (
                None
                if args.no_require_output_tags is None
                else not args.no_require_output_tags
            ),
            selected_config.get("require_output_tags"),
            True,
        )
    )

    query_ids, query_data = load_queries(split, lang)
    if uid:
        uid = str(uid)
        if uid not in query_data:
            raise RuntimeError(f"Query uid {uid!r} not found in split {split!r}")
        selected_ids = [uid]
    else:
        selected_ids = query_ids
        if limit is not None:
            limit = int(limit)
            if limit >= 1:
                selected_ids = selected_ids[:limit]

    print(f"Config: {Path(args.config)}")
    print(
        f"Run: split={split} lang={lang} queries={len(selected_ids)} harness={harness} method={method} "
        f"model={model or '<config default>'} resume={resume}"
    )

    evaluations = []
    skipped_completed = 0
    for index, uid in enumerate(selected_ids, start=1):
        print(f"\n[{index}/{len(selected_ids)}] Solving {uid}")
        result_path = PROJECT_ROOT / "results" / method / f"{uid}.json"
        if resume and result_path.exists():
            skipped_completed += 1
            print(f"Skipping completed query because result exists: {result_path}")
            continue
        evaluation = solve_query(
            harness=harness,
            split=split,
            lang=lang,
            uid=uid,
            query=query_data[uid],
            method=method,
            model=model,
            timeout=timeout,
            work_dir=work_dir,
            harness_config=harness_config,
            no_run_harness=no_run_harness,
            plan_file=plan_file,
            tool_python=tool_python,
            require_output_tags=require_output_tags,
        )
        if evaluation is not None:
            evaluations.append(evaluation)

    parse_failures = sum(
        1 for evaluation in evaluations if evaluation.get("parse_failure")
    )
    parse_failure_ids = [
        evaluation["uid"]
        for evaluation in evaluations
        if evaluation.get("parse_failure")
    ]
    if (evaluations or skipped_completed) and not args.uid:
        summary_path = PROJECT_ROOT / work_dir / f"{split}_summary.json"
        summary = evaluate_split(
            split,
            method,
            selected_ids,
            query_data,
            lang,
            parse_failure_ids=parse_failure_ids,
        )
        summary["skipped_completed"] = skipped_completed
        write_json(summary_path, summary)
        print(f"\nSaved split summary: {summary_path}")
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default))

    print(f"\nParse failures: {parse_failures}")
    if resume:
        print(f"Skipped completed queries: {skipped_completed}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
