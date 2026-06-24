#!/usr/bin/env python
"""Evaluate results/best on tpc_phase1 and print the headline metrics, one per line.

Runs eval_tpc.py with live terminal output so progress indicators (for example tqdm)
remain visible. Metrics are parsed from the newly appended tail of
your_tpc_scores.json (append-only file).
"""
import ast
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDER = [("Overall", "overall"), ("Overall (official)", "overall_official"), ("FPR", "FPR"), ("C-LPR", "C-LPR"),
         ("MicEPR", "MicEPR"), ("MacEPR", "MacEPR"),
         ("DAV", "DAV"), ("ATT", "ATT"), ("DDR", "DDR")]
SCORES_FILE = os.path.join(ROOT, "your_tpc_scores.json")


def _parse_scores_from_text(text: str):
    scores = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("{") and "overall" in line:
            cleaned = re.sub(r"np\.float\d*\(([^()]+)\)", r"\1", line)
            try:
                candidate = ast.literal_eval(cleaned)
                if isinstance(candidate, dict):
                    scores = candidate
            except (ValueError, SyntaxError):
                pass
    return scores


def _read_new_scores(start_offset: int):
    if not os.path.exists(SCORES_FILE):
        return None

    try:
        with open(SCORES_FILE, encoding="utf-8") as f:
            f.seek(start_offset)
            tail = f.read()
    except OSError:
        return None

    scores = _parse_scores_from_text(tail)
    if isinstance(scores, dict):
        return scores

    # Fallback: scan full file in case offsets changed due to external writers.
    try:
        with open(SCORES_FILE, encoding="utf-8") as f:
            full_text = f.read()
    except OSError:
        return None
    return _parse_scores_from_text(full_text)


def main():
    cmd = [sys.executable, "eval_tpc.py", "--splits", "tpc_phase1", "--method", "best", "--lang", "en"]
    start_offset = os.path.getsize(SCORES_FILE) if os.path.exists(SCORES_FILE) else 0

    print("score: running eval_tpc.py (live output follows)")
    proc = subprocess.Popen(cmd, cwd=ROOT)
    heartbeat_every = 60
    last_heartbeat = time.monotonic()
    while True:
        rc = proc.poll()
        if rc is not None:
            break
        now = time.monotonic()
        if now - last_heartbeat >= heartbeat_every:
            print("score: eval still running...", flush=True)
            last_heartbeat = now
        time.sleep(0.25)

    if rc != 0:
        return rc

    scores = _read_new_scores(start_offset)
    if not isinstance(scores, dict):
        print("score: could not parse metrics from your_tpc_scores.json", file=sys.stderr)
        return 1

    print("=== results/best on tpc_phase1 ===")
    for label, key in ORDER:
        if key in scores:
            print("{}: {:.4f}".format(label, float(scores[key])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
