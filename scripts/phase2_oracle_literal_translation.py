"""Build and verify a zh->en map for the HF oracle DSL's Chinese literals, and price the
structural scoring cap those literals impose on every free-prose measurement we make.

Static, read-only, no solve, no LLM, no network beyond the local HF cache. Instrument for
`docs/tpc_phase2_roadmap.md#p23--make-the-free-prose-register-scoreable`.

**The problem.** The four Hugging Face splits (`easy`, `medium`, `human`, `preference_base50`) are
the project's only free-prose register — the one the held-out set most resembles. Their
`nature_language_en` is English but their `hard_logic_py` literals are **native Chinese**, and they
are never translated. Scored under `--lang en` the plan's own facts come from
`chinatravel/environment/database_en/`, so they are English strings: a clause of the form
`'\u535a\u7269\u9986' in attraction_type(x)` is **structurally unsatisfiable**, whatever the parser
and solver do. Every such clause is a guaranteed C-LPR loss, and every query containing one is
pinned at `FPR = 0`.

**The fix this script verifies.** `database/` and `database_en/` are row-parallel (identical row
counts, same order), so a zh->en value map is *derivable from the shipped data itself* — no
translation model, no guessing. After `normalize_concept_value` canonicalizes the English casing
variants, the map is 1:1: this script fails loudly if it is not.

    HF_HUB_OFFLINE=1 .venv/bin/python scripts/phase2_oracle_literal_translation.py \\
        --out-dir results/phase2_baselines/screens/<date>_oracle_literal_translation

Applying the map to a materialized split's oracle is a **separate, evaluation-only** step and the
result must never ship (same rule as `scripts/materialize_hf_split.py`: delete after scoring, and
never committed -- see `.gitignore`'s `*_en_oracle` rule). This script builds and verifies the map,
prices the cap (`build_map` / `price_cap`), and exposes the literal-level rewrite
(`translate_clause` / `translate_hard_logic`) that `scripts/materialize_hf_split.py
--translate-oracle-literals` applies to a materialized split's `hard_logic_py`; use `--emit-map` to
write the map standalone for inspection.
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for path in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

CJK = re.compile(r"[\u4e00-\u9fff]+")

# (database subdirectory, concept kind for normalize_concept_value, columns to map).
# The concept columns are the closed vocabularies the verifier's own DSL quotes; `name` covers the
# POI-name literals a `required_*`/`excluded_*` clause quotes.
SOURCES = (
    ("attractions", "attraction", ("type", "name")),
    ("restaurants", "restaurant", ("cuisine", "name")),
    ("accommodations", "accommodation", ("featurehoteltype", "name")),
)

HF_SPLITS = ("easy", "medium", "human", "preference_base50")

# A negated clause ("... not in ...") over an untranslated literal is trivially *true*, not
# unsatisfiable, so it must not be counted toward the cap.
NEGATION = re.compile(r"not\s+in|!=|not\s*\(|==\s*False")

# Matches a single- or double-quoted Python string literal, escapes included. Used to find the
# exact spans a translation is allowed to touch -- a bare CJK regex over the whole clause would
# also match Chinese text that happens to sit outside a literal (comments, or in principle an
# identifier), and the DSL never puts Chinese anywhere else, but scoping to literals is free and
# strictly safer.
STRING_LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")


def build_map() -> tuple[dict[str, str], dict]:
    """Derive zh -> canonical-en from the row-parallel bilingual databases.

    Raises on any ambiguity: two different English values for one Chinese literal would make the
    translation a guess, which is exactly what this instrument exists to avoid.
    """
    import pandas as pd

    from chinatravel.environment.concept_labels import normalize_concept_value

    candidates: dict[str, set[str]] = defaultdict(set)
    row_counts = Counter()
    for subdir, kind, columns in SOURCES:
        for zh_path in sorted(glob.glob(str(REPO_ROOT / "chinatravel" / "environment" / "database"
                                            / subdir / "*" / "*.csv"))):
            en_path = zh_path.replace("/database/", "/database_en/")
            if not os.path.exists(en_path):
                raise FileNotFoundError(f"no English counterpart for {zh_path}")
            zh_df, en_df = pd.read_csv(zh_path), pd.read_csv(en_path)
            if len(zh_df) != len(en_df):
                raise ValueError(f"row counts differ, map is not derivable: {zh_path} "
                                 f"({len(zh_df)} vs {len(en_df)})")
            row_counts[subdir] += len(zh_df)
            for column in columns:
                if column not in zh_df.columns or column not in en_df.columns:
                    continue
                for zh_value, en_value in zip(zh_df[column], en_df[column]):
                    if not isinstance(zh_value, str) or not isinstance(en_value, str):
                        continue
                    zh_value, en_value = zh_value.strip(), en_value.strip()
                    if column != "name":
                        en_value = normalize_concept_value(kind, en_value)
                    candidates[zh_value].add(en_value)

    ambiguous = {k: sorted(v) for k, v in candidates.items() if len(v) > 1}
    if ambiguous:
        raise ValueError("zh->en map is ambiguous after canonicalization; refusing to guess: "
                         f"{list(ambiguous.items())[:5]}")

    mapping = {k: next(iter(v)) for k, v in candidates.items()}

    # A composite concept value is quoted *part by part* by the DSL, so register each part.
    # Two shapes, both alignment-free: "博物馆/纪念馆" -> "Museum/Memorial Hall" splits into the same
    # number of parts, so parts pair positionally; "美术馆/艺术馆" -> "Art Museum" has one English
    # value for several Chinese ones, and since both came from the same database row they denote
    # that same single category, so every part maps to the whole value. A many-to-many split with
    # differing part counts is left alone — pairing it would be a guess.
    for zh_value, en_value in list(mapping.items()):
        if "/" not in zh_value:
            continue
        zh_parts = [p.strip() for p in zh_value.split("/") if p.strip()]
        en_parts = [p.strip() for p in en_value.split("/") if p.strip()]
        if len(zh_parts) == len(en_parts):
            for zh_part, en_part in zip(zh_parts, en_parts):
                mapping.setdefault(zh_part, en_part)
        elif len(en_parts) == 1:
            for zh_part in zh_parts:
                mapping.setdefault(zh_part, en_value)

    return mapping, {"database_rows": dict(row_counts), "entries": len(mapping)}


def translate_clause(clause: str, mapping: dict[str, str]) -> tuple[str, list[str]]:
    """Rewrite every fully-mappable Chinese string literal in one ``hard_logic_py`` clause to its
    English equivalent. Returns ``(possibly-rewritten clause, unmapped CJK runs left as-is)``.

    Only touches quoted string literals (never bare identifiers or comments), and only rewrites a
    literal when *every* CJK run inside it is in the map -- a partially-mappable literal (a
    POI-name fragment like a branch suffix, or a generic location) is left untouched verbatim and
    its unmapped run(s) reported, rather than guessed at. A literal with no CJK content, or one
    that fails to parse as a Python string (should not happen on real ``hard_logic_py``, but the
    fallback is "leave it alone" rather than raise, since one malformed clause must not abort a
    whole split), passes through unchanged.
    """
    unmapped: list[str] = []

    def _sub(match: re.Match) -> str:
        raw = match.group(0)
        try:
            value = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return raw
        if not isinstance(value, str):
            return raw
        tokens = CJK.findall(value)
        if not tokens:
            return raw
        if not all(token in mapping for token in tokens):
            unmapped.extend(token for token in tokens if token not in mapping)
            return raw
        translated = value
        for token in tokens:
            translated = translated.replace(token, mapping[token])
        return repr(translated)

    return STRING_LITERAL.sub(_sub, clause), unmapped


def translate_hard_logic(clauses: list[str], mapping: dict[str, str]) -> dict:
    """Translate one query's ``hard_logic_py`` clause list. Returns the new clause list plus a
    small report (clauses changed, CJK runs that had no map entry) -- evaluation-only, and the
    caller is responsible for never shipping the result (see module docstring)."""
    new_clauses = []
    changed = 0
    unmapped_all: list[str] = []
    for clause in clauses:
        new_clause, unmapped = translate_clause(clause, mapping)
        if new_clause != clause:
            changed += 1
        unmapped_all.extend(unmapped)
        new_clauses.append(new_clause)
    return {"clauses": new_clauses, "changed": changed,
            "unmapped": sorted(set(unmapped_all))}


def price_cap(mapping: dict[str, str], *, limit: int | None = None) -> list[dict]:
    """For each HF split: how many oracle clauses, and how many queries, can never pass under `en`.

    Reports mappability alongside, since a mappable literal is one the translation recovers.
    """
    from parser_vs_oracle import load_hf_queries

    rows = []
    for split in HF_SPLITS:
        try:
            ids, data = load_hf_queries("default", [split])
        except Exception as exc:
            rows.append({"split": split, "skipped": repr(exc)})
            continue
        if limit:
            ids = ids[:limit]
        n_clauses = n_cjk = n_cjk_negated = n_mappable = 0
        queries_blocked = 0
        unmapped = Counter()
        for uid in ids:
            blocked = False
            for clause in data[uid].get("hard_logic_py") or []:
                n_clauses += 1
                tokens = CJK.findall(clause)
                if not tokens:
                    continue
                n_cjk += 1
                if NEGATION.search(clause):
                    n_cjk_negated += 1
                    continue
                blocked = True
                if all(token in mapping for token in tokens):
                    n_mappable += 1
                else:
                    for token in tokens:
                        if token not in mapping:
                            unmapped[token] += 1
            queries_blocked += blocked
        n = len(ids)
        rows.append({
            "split": split,
            "n": n,
            "oracle_clauses": n_clauses,
            "cjk_literal_clauses": n_cjk,
            "cjk_literal_clauses_negated_so_trivially_true": n_cjk_negated,
            "unsatisfiable_under_en": n_cjk - n_cjk_negated,
            "unsatisfiable_and_fully_mappable": n_mappable,
            "queries_with_unsatisfiable_clause": queries_blocked,
            "fpr_ceiling_under_en": round(100 * (1 - queries_blocked / n), 2) if n else None,
            "c_lpr_ceiling_under_en": (round(100 * (1 - (n_cjk - n_cjk_negated) / n_clauses), 2)
                                       if n_clauses else None),
            "top_unmapped_literals": dict(unmapped.most_common(10)),
        })
    return rows


def render_markdown(report: dict) -> str:
    lines = [
        "# zh->en oracle-literal map, and the structural scoring cap it lifts",
        "",
        f"Map entries: **{report['map']['entries']}** (derived from "
        f"{sum(report['map']['database_rows'].values())} row-parallel database rows, "
        "1:1 after `normalize_concept_value` — the builder raises otherwise).",
        "",
        "| HF split | n | oracle clauses | unsatisfiable under `en` | of those, mappable | "
        "queries blocked | FPR ceiling | C-LPR ceiling |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in report["cap"]:
        if row.get("skipped"):
            lines.append(f"| {row['split']} | — | skipped: {row['skipped']} | | | | | |")
            continue
        lines.append(
            f"| {row['split']} | {row['n']} | {row['oracle_clauses']} | "
            f"{row['unsatisfiable_under_en']} | {row['unsatisfiable_and_fully_mappable']} | "
            f"{row['queries_with_unsatisfiable_clause']} | **{row['fpr_ceiling_under_en']}** | "
            f"{row['c_lpr_ceiling_under_en']} |"
        )
    lines += [
        "",
        "`FPR ceiling` is the highest FPR any solver can score on that split under `--lang en`, "
        "however perfect. Read every free-prose FPR measurement against it, not against 100.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="first N queries per split (smoke)")
    parser.add_argument("--out-dir", default=None, help="write report.json / summary.md here")
    parser.add_argument("--emit-map", default=None,
                        help="also write the verified zh->en map as JSON to this path")
    parser.add_argument("--skip-cap", action="store_true",
                        help="build and verify the map only; do not touch the HF cache")
    args = parser.parse_args()

    os.environ.setdefault("HF_HUB_OFFLINE", "1")

    mapping, meta = build_map()
    report = {"measurement_kind": "screen", "map": meta,
              "cap": [] if args.skip_cap else price_cap(mapping, limit=args.limit)}
    text = render_markdown(report)
    print(text)

    if args.emit_map:
        Path(args.emit_map).parent.mkdir(parents=True, exist_ok=True)
        Path(args.emit_map).write_text(json.dumps(mapping, ensure_ascii=False, indent=2,
                                                 sort_keys=True), encoding="utf-8")
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        (out / "summary.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
