#!/usr/bin/env python
"""Evaluate results/best on tpc_phase1 and print the headline metrics, one per line.

Parses the metrics dict from eval_tpc.py's stdout (its your_tpc_scores.json is opened in
append mode, so it accumulates and is not safe to read as a single object).
"""
import ast
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDER = [("Overall", "overall"), ("FPR", "FPR"), ("C-LPR", "C-LPR"),
         ("MicEPR", "MicEPR"), ("MacEPR", "MacEPR"),
         ("DAV", "DAV"), ("ATT", "ATT"), ("DDR", "DDR")]


def main():
    cmd = [sys.executable, "eval_tpc.py", "--splits", "tpc_phase1", "--method", "best", "--lang", "en"]
    proc = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    sys.stdout.write(proc.stdout)

    scores = None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and "overall" in line:
            try:
                scores = ast.literal_eval(line)
            except (ValueError, SyntaxError):
                pass
    if not isinstance(scores, dict):
        print("score: could not parse metrics from eval output", file=sys.stderr)
        return proc.returncode or 1

    print("=== results/best on tpc_phase1 ===")
    for label, key in ORDER:
        if key in scores:
            print("{}: {:.4f}".format(label, float(scores[key])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
