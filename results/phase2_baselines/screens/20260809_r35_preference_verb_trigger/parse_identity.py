"""Do two revisions of the parser produce identical solver constraints on a given set?

Compares the full parsed solver-dict variants (the object the planner actually consumes) query by
query between this tree and another tree, by importing the other tree's parse_constraints in a
subprocess. Cheap, and it proves inertness on a register instead of inferring it from equal
aggregate probe columns.

usage: parse_identity.py <other_tree> <set-spec> [...]
  set-spec: local:<split> | hf:<hf_split>
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path("/Users/stefanshschneider/Projects/private/china-travel-agent")
VENV = str(ROOT / ".venv" / "bin" / "python")

DUMP = r'''
import argparse, json, sys
from pathlib import Path
tree = Path(sys.argv[1])
sys.path.insert(0, str(tree)); sys.path.insert(0, str(tree / "scripts"))
import os
os.chdir(tree)
import parse_constraints as pc
from chinatravel.agent.tpc_agent.solver_constraints import solver_constraint_variants
kind, name = sys.argv[2].split(":", 1)
if kind == "local":
    from chinatravel.data.load_datasets import load_query
    ids, data = load_query(argparse.Namespace(splits=name, lang="en", oracle_translation=True))
else:
    from parser_vs_oracle import load_hf_queries
    ids, data = load_hf_queries("default", [name])
out = {}
for uid in ids:
    q = dict(data[uid]); q.setdefault("uid", uid)
    try:
        raw = pc.parse_query_no_oracle(q)
        variants = solver_constraint_variants(q, raw, use_oracle=False)
    except Exception as exc:
        variants = [{"__error__": repr(exc)}]
    out[uid] = json.dumps(variants, sort_keys=True, ensure_ascii=False, default=str)
print("@@JSON@@" + json.dumps(out))
'''


def dump(tree: str, spec: str) -> dict:
    p = subprocess.run([VENV, "-c", DUMP, tree, spec], capture_output=True, text=True,
                       env={"HF_HUB_OFFLINE": "1", "PATH": "/usr/bin:/bin",
                            "HOME": str(Path.home()), "HF_DATASETS_OFFLINE": "1"})
    for line in p.stdout.splitlines():
        if line.startswith("@@JSON@@"):
            return json.loads(line[len("@@JSON@@"):])
    raise SystemExit(f"no output for {tree} {spec}:\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}")


def main():
    other, specs = sys.argv[1], sys.argv[2:]
    for spec in specs:
        a = dump(str(ROOT), spec)
        b = dump(other, spec)
        assert set(a) == set(b), "uid mismatch"
        diff = [uid for uid in a if a[uid] != b[uid]]
        print(f"{spec}: {len(a)} queries, {len(diff)} with a different parse")
        for uid in diff[:5]:
            print(f"   {uid}\n     this : {a[uid][:200]}\n     other: {b[uid][:200]}")


if __name__ == "__main__":
    main()
