#!/usr/bin/env python
"""Assemble a submission from results/best.

Drops private (underscore-prefixed) top-level keys such as _eval_score from every plan and
writes submissions/fabiundstefan_<version>/<uid>.json, then zips them with the archive root
fabiundstefan_<version>/ (matching the v3 layout). The .gitkeep marker is skipped.
"""
import argparse
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", required=True, help="e.g. v4 -> submissions/fabiundstefan_v4[.zip]")
    args = ap.parse_args()

    name = "fabiundstefan_{}".format(args.version)
    best_dir = os.path.join(ROOT, "results", "best")
    out_dir = os.path.join(ROOT, "submissions", name)
    os.makedirs(out_dir, exist_ok=True)

    count = 0
    for fname in sorted(os.listdir(best_dir)):
        if not fname.endswith(".json") or fname == ".gitkeep":
            continue
        with open(os.path.join(best_dir, fname)) as f:
            plan = json.load(f)
        clean = {k: v for k, v in plan.items() if not k.startswith("_")}
        with open(os.path.join(out_dir, fname), "w") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        count += 1

    zip_path = os.path.join(ROOT, "submissions", name + ".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in sorted(os.listdir(out_dir)):
            if fname.endswith(".json"):
                zf.write(os.path.join(out_dir, fname), arcname=os.path.join(name, fname))

    print("assembled {} plans -> {} and {}".format(count, out_dir, zip_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
