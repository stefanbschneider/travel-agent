from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import phase2_record_baseline as baseline
from agent_env.adapter import ChinaTravelEnvAdapter
from chinatravel.data.load_datasets import load_query
from solve_script_with_harness import load_queries as harness_load_queries
from solve_script_with_harness import visible_query


SPLIT = "tpc_phase2_familiar_100"
EXPECTED_ARCHIVE_SHA256 = "32a88161342681400f8ded52d0babd5894ed78e5cd359860689561003566519c"
EXPECTED_VISIBLE_FIELDS = {
    "uid",
    "start_city",
    "target_city",
    "days",
    "people_number",
    "nature_language",
}


def _familiar_paths(project_root: Path) -> tuple[Path, Path]:
    data_dir = (
        project_root
        / "chinatravel"
        / "data"
        / "en"
        / "TPC_IJCAI_2026_phase2_familiar_100_data"
    )
    split_path = (
        project_root
        / "chinatravel"
        / "evaluation"
        / "default_splits"
        / f"{SPLIT}.txt"
    )
    return data_dir, split_path


def test_familiar_import_preserves_verified_source_records(project_root: Path):
    data_dir, split_path = _familiar_paths(project_root)
    manifest = json.loads((data_dir / "_provenance.json").read_text(encoding="utf-8"))

    assert manifest["dataset_id"] == "ijcai2026_phase2_familiar_100"
    assert manifest["split_name"] == SPLIT
    assert manifest["language"] == "en"
    assert manifest["record_count"] == 100
    assert manifest["archive"]["sha256"] == EXPECTED_ARCHIVE_SHA256
    assert len(manifest["members"]) == 100

    split_uids = split_path.read_text(encoding="utf-8").splitlines()
    member_uids = []
    for member in manifest["members"]:
        raw = (data_dir / member["path"]).read_bytes()
        assert len(raw) == member["size_bytes"]
        assert hashlib.sha256(raw).hexdigest() == member["sha256"]
        record = json.loads(raw)
        assert record["uid"] == Path(member["path"]).stem
        assert set(record) == EXPECTED_VISIBLE_FIELDS | {"hard_logic_py"}
        member_uids.append(record["uid"])

    assert split_uids == member_uids
    assert len(set(split_uids)) == 100


def test_familiar_agent_paths_hide_all_oracle_fields():
    oracle_args = argparse.Namespace(splits=SPLIT, lang="en", oracle_translation=True)
    query_ids, oracle_queries = load_query(oracle_args)
    uid = query_ids[0]
    oracle_query = oracle_queries[uid]
    assert "hard_logic_py" in oracle_query
    harness_ids, harness_queries = harness_load_queries(SPLIT)
    assert harness_ids == query_ids
    assert harness_queries[uid] == oracle_query

    public_args = argparse.Namespace(splits=SPLIT, lang="en", oracle_translation=False)
    public_ids, public_queries = load_query(public_args)
    assert public_ids == query_ids
    assert set(public_queries[uid]) == EXPECTED_VISIBLE_FIELDS

    adapter_result = ChinaTravelEnvAdapter().load_query(SPLIT, uid=uid)
    assert adapter_result["success"] is True
    assert adapter_result["query"] == public_queries[uid]

    future_oracle_probe = dict(oracle_query, hard_logic_future="must stay hidden")
    assert visible_query(future_oracle_probe) == public_queries[uid]


def test_familiar_source_metadata_is_projected_into_ledger_rows():
    source = baseline._data_source_metadata(SPLIT)

    assert source["dataset_id"] == "ijcai2026_phase2_familiar_100"
    assert source["language"] == "en"
    assert source["record_count"] == 100
    assert source["archive_sha256"] == EXPECTED_ARCHIVE_SHA256
    assert source["id"].endswith(EXPECTED_ARCHIVE_SHA256)

    row = baseline._to_history_row(
        {
            "split_name": SPLIT,
            "data_source": source,
            "rehearsal": {"modes": {}, "ceiling": {}},
            "parser": {},
        }
    )
    assert row["data_source_id"] == source["id"]
    assert row["data_source_kind"] == "official_archive"
    assert row["data_source_archive_sha256"] == EXPECTED_ARCHIVE_SHA256


def test_familiar_source_metadata_is_written_to_history_csv(tmp_path: Path):
    source = baseline._data_source_metadata(SPLIT)
    csv_path = tmp_path / "history.csv"
    baseline._write_history_csv(
        csv_path,
        [
            {
                "split_name": SPLIT,
                "data_source": source,
                "rehearsal": {"modes": {}, "ceiling": {}},
                "parser": {},
            }
        ],
    )

    with csv_path.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["data_source_id"] == source["id"]
    assert row["data_source_url"] == source["source_url"]
    assert row["data_source_archive_sha256"] == EXPECTED_ARCHIVE_SHA256
