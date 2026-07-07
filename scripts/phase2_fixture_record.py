#!/usr/bin/env python3
"""Record a pasted LLM response into the Phase-2 fixture cache.

Input can be passed with --response-file or stdin.
The file format matches FixtureLLMClient: {"response": "..."}
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--key", required=True, help="Fixture cache key (e.g. parse_<uid>_<hash>).")
    p.add_argument(
        "--fixtures-dir",
        default=str(PROJECT_ROOT / "cache" / "phase2_fixtures" / "llm"),
        help="Directory used by TPC_P2_LLM_FIXTURES.",
    )
    p.add_argument("--response-file", default=None, help="Path to raw LLM response text.")
    p.add_argument("--force", action="store_true", help="Overwrite existing fixture file.")
    return p.parse_args()


def _read_response(args: argparse.Namespace) -> str:
    if args.response_file:
        return Path(args.response_file).read_text(encoding="utf-8")
    return sys.stdin.read()


def main() -> None:
    args = parse_args()
    response = _read_response(args)
    if not response.strip():
        raise SystemExit("Empty response; provide --response-file or pipe text via stdin.")

    fixtures_dir = Path(args.fixtures_dir)
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    out = fixtures_dir / f"{args.key}.json"
    if out.exists() and not args.force:
        raise SystemExit(f"Fixture already exists: {out} (use --force to overwrite)")

    out.write_text(
        json.dumps({"response": response}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(str(out))


if __name__ == "__main__":
    main()
