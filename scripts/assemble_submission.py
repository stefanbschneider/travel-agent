#!/usr/bin/env python
"""Assemble a submission from results/best.

Drops private (underscore-prefixed) top-level keys such as _eval_score from every plan and
writes submissions/phase1/fabiundstefan_<version>/<uid>.json, then zips them with the archive
root fabiundstefan_<version>/ (matching the v3 layout). The .gitkeep marker is skipped.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUBMISSIONS_DIR = os.path.join(ROOT, "submissions", "phase1")


def latest_submission_version():
    """Return the highest N among existing ``v<N>`` git tags, or 0 when none exist.

    Submission versions are tracked entirely by git tags named ``v1``, ``v2``, and so on,
    so the next submission is one greater than the highest existing tag.
    """
    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v[0-9]*"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    numbers = [int(tag[1:]) for tag in result.stdout.split() if re.fullmatch(r"v\d+", tag)]
    return max(numbers) if numbers else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--version",
        default=None,
        help="submission version like v5; defaults to the next version after the highest v<N> git tag",
    )
    args = ap.parse_args()

    version = args.version
    if version is None:
        latest = latest_submission_version()
        if latest is None:
            ap.error("could not read git tags to derive the version; pass --version explicitly")
        version = "v{}".format(latest + 1)
    elif not re.fullmatch(r"v\d+", version):
        ap.error("version must look like v<number>, for example v5")

    name = "fabiundstefan_{}".format(version)
    best_dir = os.path.join(ROOT, "results", "best")
    out_dir = os.path.join(SUBMISSIONS_DIR, name)
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

    zip_path = os.path.join(SUBMISSIONS_DIR, name + ".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname in sorted(os.listdir(out_dir)):
            if fname.endswith(".json"):
                zf.write(os.path.join(out_dir, fname), arcname=os.path.join(name, fname))

    print("assembled {} plans as {} -> {} and {}".format(count, version, out_dir, zip_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
