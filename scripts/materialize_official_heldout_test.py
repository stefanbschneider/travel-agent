#!/usr/bin/env python3
"""Materialize the HF ``LAMDA-NeSy/ChinaTravel`` ``phase2/competition_test.csv`` split locally.

Why this exists: on 2026-08-20 (HF revision ``44d5dbf3bba26bdf9a212c3e76d3242b67f0d349``, per the
dataset's own ``lastModified``) the ChinaTravel dataset repo published ``phase2/competition_test.csv``
-- 100 rows, every one flagged ``official_phase2_evaluation=true``, under UIDs prefixed
``phase2_extended_...`` (disjoint from the ``phase2_familiar_...`` development set already committed
under ``chinatravel/data/en/TPC_IJCAI_2026_phase2_familiar_100_data/``). Its own
``PHASE2_RELEASE_NOTES.md`` on that dataset repo calls it "the official Phase 2 competition test
split," and it is the first time this repository has ever seen that split's oracle fields
(``hard_logic_py``/``hard_logic_nl``) -- see
``docs/tpc_phase2_eval.md#r37--identity-check-the-published-held-out-test-set`` for the identity
check (replaying the frozen ``v1``/``v2`` submission archives against it reproduces the organizers'
published scores within about a point, on byte-identical sandbox data).

This writes only local, evaluation-only files, matching every other ``materialize_hf_split.py``
output: one ``<uid>.json`` per row under ``chinatravel/data/en/<name>/`` and a UID list at
``chinatravel/evaluation/default_splits/<name>.txt``. Both paths must stay gitignored -- this file is
the actual competition answer key, unlike the untranslated ``hf_medium``/``easy``/``human`` splits
which are merely development data -- which is why ``--name`` is required to keep the existing ``hf_*``
``.gitignore`` prefix rule.

    .venv/bin/python scripts/materialize_official_heldout_test.py
    .venv/bin/python agent_env/scripts/solve_script_with_harness.py \\
        --method <method> --split hf_phase2_official_competition_test
    .venv/bin/python eval_tpc.py --splits hf_phase2_official_competition_test --method <method>

The CSV is fetched pinned to the revision above by default (reproducible), and its bytes are
checksummed against the value recorded at discovery time. Pass ``--revision main`` for the current
tip (unchecksummed), or ``--from-csv <path>`` to read an already-downloaded copy offline.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.request
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

HF_CSV_URL = (
    "https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel/resolve/{revision}/"
    "phase2/competition_test.csv"
)
DEFAULT_REVISION = "44d5dbf3bba26bdf9a212c3e76d3242b67f0d349"  # pinned: the 2026-08-20 publish
DEFAULT_NAME = "hf_phase2_official_competition_test"

# sha256 of the raw CSV bytes at DEFAULT_REVISION, recorded at discovery time (2026-09-05). Only
# checked when fetching that exact revision -- a different revision is, by definition, different
# bytes, so checking here would just be a confusing false alarm.
EXPECTED_SHA256 = "fbc3379e930c6fc22071bbd2fedaf7c4d34d47cc3a157e8db22cffeb99715447"


def fetch_csv_text(revision: str, timeout: float = 60.0) -> str:
    url = HF_CSV_URL.format(revision=revision)
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
        raw = resp.read()
    if revision == DEFAULT_REVISION:
        digest = hashlib.sha256(raw).hexdigest()
        if digest != EXPECTED_SHA256:
            raise ValueError(
                f"Downloaded CSV at revision {revision!r} does not match the recorded checksum "
                f"(expected {EXPECTED_SHA256}, got {digest}) -- the file may have been rewritten "
                "at this revision, which should not happen for a pinned commit. Refusing to "
                "materialize a split from unverified data."
            )
    return raw.decode("utf-8")


def parse_rows(csv_text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    return [
        row
        for row in reader
        if row.get("official_phase2_evaluation", "").strip().lower() == "true"
    ]


def materialize(csv_text: str, name: str, *, project_root: Path = PROJECT_ROOT) -> dict[str, Any]:
    rows = parse_rows(csv_text)
    if not rows:
        raise ValueError(
            "No official_phase2_evaluation=true rows found in the CSV -- refusing to write an "
            "empty split."
        )

    data_dir = project_root / "chinatravel" / "data" / "en" / name
    data_dir.mkdir(parents=True, exist_ok=True)
    ids = []
    for row in rows:
        uid = row["uid"]
        ids.append(uid)
        out = {
            "uid": uid,
            "nature_language": row["nature_language"],
            "start_city": row["start_city"],
            "target_city": row["target_city"],
            "days": int(row["days"]),
            "people_number": int(row["people_number"]),
            "hard_logic_py": json.loads(row["hard_logic_py"]),
        }
        (data_dir / f"{uid}.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    split_file = project_root / "chinatravel" / "evaluation" / "default_splits" / f"{name}.txt"
    split_file.parent.mkdir(parents=True, exist_ok=True)
    split_file.write_text("\n".join(ids) + "\n", encoding="utf-8")
    return {
        "name": name,
        "n": len(ids),
        "data_dir": str(data_dir),
        "split_file": str(split_file),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--name",
        default=DEFAULT_NAME,
        help=f"Local split name (default: {DEFAULT_NAME}). Must start with 'hf_' to stay "
        "gitignored -- this dataset carries the real competition answer key.",
    )
    ap.add_argument(
        "--revision",
        default=DEFAULT_REVISION,
        help="HF dataset git revision/sha to fetch from (default: pinned to the 2026-08-20 "
        "publish, checksum-verified). Pass 'main' for the current tip (unchecksummed).",
    )
    ap.add_argument(
        "--from-csv",
        default=None,
        help="Read the CSV from a local file instead of fetching from HF (offline use; skips "
        "the checksum check regardless of --revision).",
    )
    args = ap.parse_args()
    if not args.name.startswith("hf_"):
        raise SystemExit(
            f"--name {args.name!r} must start with 'hf_' -- see the .gitignore hf_* rule; this "
            "dataset's hard_logic_py is the real competition answer key and must never be "
            "committed."
        )
    if args.from_csv:
        csv_text = Path(args.from_csv).read_text(encoding="utf-8")
    else:
        csv_text = fetch_csv_text(args.revision)
    result = materialize(csv_text, args.name)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
