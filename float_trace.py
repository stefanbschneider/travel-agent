#!/usr/bin/env python
"""
float_trace.py — cross-platform float determinism probe for the phase-1 verifier.

The phase-1 score reads FIXED plans (results/best/*.json, tracked in git) but the
verifier RECOMPUTES geodesic distances via geopy. Those recomputed values are the
only thing that can differ between machines (x86-64 Linux vs Apple-Silicon macOS),
because everything else the scorer touches is byte-identical tracked data.

This script wraps geopy.distance.geodesic, runs the SAME commonsense + hard-constraint
evaluators the real eval runs, and dumps every recomputed distance bit-exactly
(float.hex(), which round-trips exactly). Run it on both machines and `diff` the
two JSON files: differing lines are the exact coordinate pairs whose geodesic
diverges, and the pass-set section shows which query flips.

Usage:
    .venv/bin/python float_trace.py --split tpc_phase1 --lang en \
        --ids 20250320174446059265,2025... \
        --out trace_$(uname -m).json

    # or pull the failing ids from a file (one id per line):
    .venv/bin/python float_trace.py --ids-file failing_ids.txt --out trace_$(uname -m).json

Then, on each machine, run it, copy both JSONs to one place, and:
    diff trace_x86_64.json trace_arm64.json
"""
import argparse
import json
import os
import platform
import sys
from argparse import Namespace

# ---- 1. Install the geodesic recorder BEFORE the verifier imports it --------
import geopy.distance as _gd

_real_geodesic = _gd.geodesic
_RECORD = {}


def _coord_repr(x):
    # Coordinates arrive as (lat, lon) tuples/lists of floats (occasionally strings).
    try:
        return "(" + ",".join(repr(float(v)) for v in x) + ")"
    except Exception:
        return repr(x)


class _RecordingDistance:
    """Wraps a real geopy Distance so attribute access still works, and records
    the exact km value (bit-exact via .hex()) keyed by the input coordinate pair."""

    def __init__(self, a, b):
        self._d = _real_geodesic(a, b)
        km = float(self._d.kilometers)
        key = _coord_repr(a) + " -> " + _coord_repr(b)
        # If the same pair is seen twice the value must match; assert catches
        # intra-run nondeterminism (would be a separate, scarier bug).
        prev = _RECORD.get(key)
        entry = {"km": repr(km), "hex": km.hex()}
        if prev is not None and prev["hex"] != entry["hex"]:
            entry["INTRA_RUN_MISMATCH"] = prev["hex"]
        _RECORD[key] = entry

    def __getattr__(self, name):
        return getattr(self._d, name)


def _recording_geodesic(a, b, *args, **kwargs):
    if args or kwargs:  # unusual call form — fall back, don't record
        return _real_geodesic(a, b, *args, **kwargs)
    return _RecordingDistance(a, b)


_gd.geodesic = _recording_geodesic

# ---- 2. Now import the repo (it will pick up the wrapped geodesic) ----------
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)

from chinatravel.data.load_datasets import load_query  # noqa: E402
from chinatravel.evaluation.utils import load_json_file  # noqa: E402
from chinatravel.evaluation.commonsense_constraint import (  # noqa: E402
    evaluate_commonsense_constraints,
)
from chinatravel.evaluation.hard_constraint import (  # noqa: E402
    evaluate_hard_constraints_v2,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="tpc_phase1")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--method", default="best", help="results/<method> dir with plans")
    ap.add_argument("--ids", default="", help="comma-separated query ids to probe")
    ap.add_argument("--ids-file", default="", help="file with one query id per line")
    ap.add_argument("--out", default="trace_%s.json" % platform.machine())
    args = ap.parse_args()

    load_args = Namespace(splits=args.split, lang=args.lang, method=args.method,
                          index=None)
    query_index, query_data = load_query(load_args)

    # Which ids to probe
    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    if args.ids_file:
        with open(args.ids_file) as f:
            ids += [ln.strip() for ln in f if ln.strip()]
    if ids:
        query_index = [i for i in ids if i in query_data]
        missing = [i for i in ids if i not in query_data]
        if missing:
            print("WARNING: ids not in split/data:", missing, file=sys.stderr)
    # else: probe the whole split (slower but exhaustive)

    # Load the fixed plans (same as `load_result` in eval_tpc.py)
    results_dir = os.path.join(_here, "results", args.method)
    plans = {}
    for qid in query_index:
        p = os.path.join(results_dir, "%s.json" % qid)
        plans[qid] = load_json_file(p) if os.path.exists(p) else {}

    # Run the SAME evaluators the real eval runs -> recorder captures every geodesic
    _, _, _, commonsense_pass = evaluate_commonsense_constraints(
        query_index, query_data, plans, verbose=False, lang=args.lang
    )
    _, _, _, _, _, logi_pass = evaluate_hard_constraints_v2(
        query_index, query_data, plans, env_pass_id=commonsense_pass,
        verbose=False, lang=args.lang,
    )

    out = {
        "platform": {
            "machine": platform.machine(),
            "system": platform.system(),
            "python": sys.version.split()[0],
            "geopy": getattr(__import__("geopy"), "__version__", "?"),
            "numpy": __import__("numpy").__version__,
        },
        "probed_ids": sorted(query_index),
        "commonsense_pass": sorted(commonsense_pass),
        "hard_pass": sorted(logi_pass),
        "failed_commonsense": sorted(set(query_index) - set(commonsense_pass)),
        "failed_hard": sorted(set(commonsense_pass) - set(logi_pass)),
        # geodesic calls, sorted for a stable diff
        "geodesic": {k: _RECORD[k] for k in sorted(_RECORD)},
    }
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)

    print("wrote %s" % args.out)
    print("platform:", out["platform"])
    print("probed %d ids | %d geodesic calls recorded"
          % (len(query_index), len(_RECORD)))
    print("failed commonsense:", out["failed_commonsense"])
    print("failed hard       :", out["failed_hard"])


if __name__ == "__main__":
    main()
