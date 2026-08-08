"""What attraction_type value does the oracle actually use for a given English phrase?

Scans every released/HF set for queries whose visible text matches a probe phrase and prints the
oracle's own required attraction-type literals, so a candidate parser mapping is chosen from
evidence rather than from intuition. Measurement only.
"""
from __future__ import annotations
import collections
import re
import sys
from pathlib import Path

ROOT = Path("/Users/stefanshschneider/Projects/private/china-travel-agent")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from phase2_generalization_probe import load_hf, load_local  # type: ignore

PHRASES = {
    "hist+cult": r"historical and cultural|cultural and historical",
    "history&culture": r"histor\w+ and cultur\w+|cultur\w+ and histor\w+",
    "historical area": r"historical areas?",
    "children": r"suitable for children|for kids|with children",
    "date": r"\bgoing on a date\b|\bdate\b",
    "like/love X": r"\b(?:i|we)\s+(?:like|love|prefer|enjoy)\b",
    "wellness/relax": r"wellness|relax",
    "food court": r"food court",
    "universities": r"universit(?:y|ies)",
}

TYPE_RE = re.compile(r"\{([^}]*)\}\s*<=\s*attraction_type_set")


def oracle_types(query) -> list[str]:
    out = []
    for clause in query.get("hard_logic_py") or []:
        if "attraction_type_set" not in clause:
            continue
        m = TYPE_RE.search(clause.replace("\n", " "))
        if m:
            out.extend(v.strip().strip("'\"") for v in m.group(1).split(","))
    return out


def main():
    sets = [("familiar_100", "local", "tpc_phase2_familiar_100"),
            ("local_150", "local", "tpc_phase2_test"),
            ("hf_easy", "hf", "easy"), ("hf_medium", "hf", "medium"),
            ("hf_human", "hf", "human")]
    tally = {k: collections.Counter() for k in PHRASES}
    examples = {k: [] for k in PHRASES}
    for label, kind, name in sets:
        ids, data = load_local(name) if kind == "local" else load_hf(name)
        for uid in ids:
            q = data[uid]
            text = str(q.get("nature_language") or "")
            types = oracle_types(q)
            for key, pat in PHRASES.items():
                if re.search(pat, text, re.I):
                    tally[key][tuple(sorted(types)) or ("<none>",)] += 1
                    if len(examples[key]) < 2:
                        examples[key].append((label, uid, types))
    for key in PHRASES:
        print(f"\n### {key}")
        for types, n in tally[key].most_common(6):
            print(f"   {n:>4}  {types}")


if __name__ == "__main__":
    main()
