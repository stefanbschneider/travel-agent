#!/usr/bin/env python3
"""Dump the exact Stage-1 LLM parse prompt + cache key for a query.

Typical loop:
1) Generate prompt/key with this script.
2) Paste prompt into Copilot/Kiro manually.
3) Save the model's JSON response with scripts/phase2_fixture_record.py.
4) Run harness with TPC_P2_LLM_BACKEND=fixture and TPC_P2_LLM_PARSE=1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from chinatravel.agent.phase2 import normalize
from chinatravel.data.load_datasets import load_query

HIDDEN_QUERY_KEYS = {"hard_logic", "hard_logic_py", "hard_logic_nl"}


def _visible_query(query: dict) -> dict:
    return {k: v for k, v in query.items() if k not in HIDDEN_QUERY_KEYS}


def _load_query(split: str, uid: str | None, lang: str) -> tuple[str, dict]:
    args = argparse.Namespace(splits=split, lang=lang, oracle_translation=True)
    query_ids, query_data = load_query(args)
    if not query_ids:
        raise RuntimeError(f"No queries found for split: {split}")
    picked = uid or query_ids[0]
    if picked not in query_data:
        raise RuntimeError(f"uid {picked!r} not found in split {split!r}")
    q = dict(query_data[picked])
    q.setdefault("uid", picked)
    return picked, _visible_query(q)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", default="tpc_phase2_val")
    p.add_argument("--uid", default=None)
    p.add_argument("--lang", default="en", choices=["en", "zh"])
    p.add_argument(
        "--out-dir",
        default=str(PROJECT_ROOT / "cache" / "phase2_fixtures" / "prompts"),
        help="Directory to write <uid>.prompt.txt and <uid>.meta.json",
    )
    p.add_argument("--print-only", action="store_true", help="Print prompt/key only; do not write files.")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    uid, visible = _load_query(args.split, args.uid, args.lang)
    deterministic = normalize.parse_to_ir(visible).raw
    prompt = normalize.build_llm_parse_prompt(visible, deterministic)
    cache_key = normalize.llm_parse_cache_key(visible, prompt)

    print(f"uid={uid}")
    print(f"cache_key={cache_key}")
    print("--- prompt ---")
    print(prompt)

    if args.print_only:
        return

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{uid}.prompt.txt").write_text(prompt, encoding="utf-8")
    (out_dir / f"{uid}.meta.json").write_text(
        json.dumps(
            {
                "uid": uid,
                "split": args.split,
                "lang": args.lang,
                "cache_key": cache_key,
                "prompt_file": f"{uid}.prompt.txt",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
