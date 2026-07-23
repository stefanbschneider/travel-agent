"""Stage 3 LLM refine: prompt, cache key, and response parsing for bounded plan repair.

`normalize.build_llm_parse_prompt` is the parse-stage sibling; this module is refine's own
prompt/parsing surface, kept separate because it prompts from the *plan* + a checker failure
summary rather than the raw NL query, and normalize.py is already large. A proposed edit
authorizes nothing: it is just a typed op description. `TPCAgent.apply_refine_edits` grounds each
op against WorldEnv and `TPCAgent.ground_and_check` re-checks the whole batch before commit --
see `orchestrator.llm_refine` for the control flow that ties this together.
"""

from __future__ import annotations

import hashlib
import json

# Typed edit vocabulary the refine prompt asks for and the parser accepts. Free-form plan
# rewrites are never allowed -- every op is applied by a bounded, WorldEnv-grounded TPCAgent
# helper (see tpc_agent.py's apply_refine_edits/_refine_* methods).
REFINE_ALLOWED_OPS = frozenset({"reorder_day", "shift_activity_window", "swap_activity", "drop_activity"})
MAX_REFINE_EDITS = 6


def _stable_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def llm_refine_cache_key(query: dict, prompt: str) -> str:
    uid = str(query.get("uid") or "unknown")
    return f"refine_{uid}_{_stable_prompt_hash(prompt)}"


def _compact_plan_for_prompt(plan: dict) -> list:
    """Strip a plan down to day/type/position/start_time/end_time -- enough for the model to name
    an existing activity and propose a time/order edit, without spending tokens on cost/tickets/
    transport-leg detail the edit ops don't need."""
    out = []
    for day in (plan or {}).get("itinerary", []) or []:
        if not isinstance(day, dict):
            continue
        acts = []
        for act in day.get("activities", []) or []:
            if not isinstance(act, dict):
                continue
            acts.append({
                "type": act.get("type"),
                "position": act.get("position") or act.get("From") or act.get("To"),
                "start_time": act.get("start_time"),
                "end_time": act.get("end_time"),
            })
        out.append({"day": day.get("day"), "activities": acts})
    return out


def build_llm_refine_prompt(query: dict, plan: dict, failure_summary: dict) -> str:
    """Build the Stage 3 repair prompt. Sees only the visible query allowlist (mirrors
    ``normalize.build_llm_parse_prompt``), the current (already WorldEnv-grounded) plan, and the
    no-oracle checker's own failure summary -- never ``hard_logic_py``/``hard_logic``/``plan``
    oracle fields or any ``*_py`` verifier field."""
    visible = {
        "uid": query.get("uid"),
        "people_number": query.get("people_number"),
        "start_city": query.get("start_city"),
        "target_city": query.get("target_city"),
        "nature_language": query.get("nature_language", ""),
    }
    compact_plan = _compact_plan_for_prompt(plan)
    return (
        "You are repairing a travel itinerary that fails automatic acceptance checks. You do not\n"
        "decide facts: every edit you propose is re-grounded against the real environment (POI\n"
        "existence, opening hours, transport routes) and only kept if the deterministic checker then\n"
        "accepts the plan and its quality does not get worse. Propose the SMALLEST set of edits that\n"
        "could fix the listed failures -- do not rewrite the plan, do not invent new POI names or\n"
        "days that are not already in the plan below.\n\n"
        "Return STRICT JSON only (no markdown/code fences) with this schema:\n"
        "{\n"
        "  \"edits\": [\n"
        "    {\"op\": \"shift_activity_window\", \"day\": int, \"location\": string,\n"
        "     \"start_time\": \"HH:MM\", \"end_time\": \"HH:MM\"},\n"
        "    {\"op\": \"swap_activity\", \"day\": int, \"location_a\": string, \"location_b\": string},\n"
        "    {\"op\": \"drop_activity\", \"day\": int, \"location\": string},\n"
        "    {\"op\": \"reorder_day\", \"day\": int, \"order\": [string, ...]}\n"
        "  ]\n"
        "}\n"
        f"Propose at most {MAX_REFINE_EDITS} edits, only the ops above (any other \"op\" value is\n"
        "dropped). \"location\"/\"location_a\"/\"location_b\"/entries in \"order\" must each be the\n"
        "exact \"position\" of an activity ALREADY in the plan below -- never a new place. \"day\" is\n"
        "the plan's 1-based day number, matching the \"day\" field below. If nothing you propose\n"
        "could plausibly help, return {\"edits\": []}.\n\n"
        "Visible request JSON:\n"
        f"{json.dumps(visible, ensure_ascii=False, indent=2)}\n\n"
        "Current plan (day/activities only; each activity's position is its name):\n"
        f"{json.dumps(compact_plan, ensure_ascii=False, indent=2)}\n\n"
        "Checker failure summary -- fix these, don't touch anything not listed here. "
        "\"failed_clauses\" names the specific POI/location (and window, where relevant) each "
        "failing requirement is about -- prefer editing exactly those activities over guessing. "
        "\"space_gaps\" lists each activity whose inbound leg does not already connect from the "
        "previous activity's position (\"expected_from\") -- a reorder/shift that fixes the listed "
        "location without restoring this connection will not pass. "
        "\"activity_feasible_windows\" lists, per already-scheduled activity, its real opening/"
        "closing hours (\"open\"/\"close\"), the earliest it can actually be reached "
        "(\"earliest_reachable\"), and the latest it must end to still reach the next fixed "
        "activity (\"must_end_before_next_starts_at\") -- a shift_activity_window edit outside "
        "these bounds cannot ground and will be dropped, so stay within them:\n"
        f"{json.dumps(failure_summary, ensure_ascii=False, indent=2)}"
    )


def parse_llm_refine_edits(text: str) -> list[dict]:
    """Tolerant strict-JSON extraction for the refine response.

    Raises ``ValueError`` on malformed JSON/shape (mirrors ``normalize._parse_llm_json_blob``'s
    raise-on-failure contract, so the caller can distinguish "LLM/JSON broke" from "LLM proposed
    nothing") -- this includes an ``edits`` key that is missing or not a list (e.g. the model wrote
    ``{"edit": ...}`` or ``{"edits": "none"}``), since silently treating that as "no edits" would
    mask a real prompt/model regression as a legitimate no-op. An explicit ``{"edits": []}`` is not
    an error and returns ``[]``. Every returned edit's ``op`` is one of ``REFINE_ALLOWED_OPS`` --
    anything else is silently dropped, not raised on, since a model may echo an unsupported op
    alongside otherwise-valid ones.
    """
    raw = (text or "").strip()
    if not raw:
        return []
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
        raw = raw.rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"llm_refine invalid JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise ValueError("llm_refine response must be a JSON object")
    if "edits" not in payload:
        raise ValueError("llm_refine response missing 'edits' key")
    edits = payload["edits"]
    if not isinstance(edits, list):
        raise ValueError("llm_refine response 'edits' must be a list")
    out = []
    for edit in edits[:MAX_REFINE_EDITS]:
        if isinstance(edit, dict) and str(edit.get("op") or "") in REFINE_ALLOWED_OPS:
            out.append(edit)
    return out
