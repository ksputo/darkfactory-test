#!/usr/bin/env python3
"""Fake `factory.py` for factory_ui tests. It follows specs/interfaces.md only as far as the UI reads it.

FAKE_WIRED   comma-separated commands to list when called with no arguments
FAKE_FAIL    comma-separated commands that exit 1 with a stderr line
FAKE_HOLD    path; every command except `show` waits until this file exists
FAKE_RECORD_ID  run ID printed (and created) by `record` and `run`

`show RUN_ID` reads runs/RUN_ID/fake-show.txt: first line is the exit code, the rest is stderr.
Every call is appended to calls.log next to this file.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def wired():
    return [name for name in os.environ.get("FAKE_WIRED", "").split(",") if name]


def log_call(argv):
    with (ROOT / "calls.log").open("a") as handle:
        handle.write(" ".join(argv) + "\n")


def hold():
    gate = os.environ.get("FAKE_HOLD")
    deadline = time.monotonic() + 60
    while gate and not Path(gate).exists() and time.monotonic() < deadline:
        time.sleep(0.02)


def show(run_id):
    flag = ROOT / "runs" / run_id / "fake-show.txt"
    if not flag.is_file():
        return 0
    first, _, rest = flag.read_text().partition("\n")
    if rest.strip():
        print(rest.strip(), file=sys.stderr)
    return int(first)


def main(argv):
    if not argv:
        print("\n".join(wired()))
        return 0
    command = argv[0]
    log_call(argv)
    if command not in wired():
        print(f"fake factory: unknown command {command}", file=sys.stderr)
        return 2
    if command == "show":
        return show(argv[1])
    failing = command in os.environ.get("FAKE_FAIL", "").split(",")
    if not failing:
        print(f"fake {command} starting", file=sys.stderr, flush=True)
    hold()
    if failing:
        print(f"fake: {command} failed on purpose", file=sys.stderr)
        return 1
    if command in ("record", "run"):
        run_id = os.environ.get("FAKE_RECORD_ID", "run-fake")
        (ROOT / "runs" / run_id).mkdir(parents=True, exist_ok=True)
        print(run_id)
    print(f"fake {command} done", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
