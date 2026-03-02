#!/usr/bin/env python3
"""Agent control loop entrypoint.

Runs `seedpipe-watch --once` repeatedly at a fixed cadence, suitable for
agent-managed long-running polling in local/dev environments.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run watch scans in a continuous control loop")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Delay between scan cycles (default: 5.0)")
    parser.add_argument("--max-cycles", type=int, default=0, help="Max scan cycles before exit; 0 means run forever")
    parser.add_argument(
        "--watch-args",
        default="",
        help="Additional args forwarded to tools.watch (example: \"--pipeline all --inbox-root /inbox\")",
    )
    return parser.parse_args()


def run_cycle(watch_args: list[str]) -> int:
    cmd = [sys.executable, "-m", "tools.watch", "--once", *watch_args]
    proc = subprocess.run(cmd)
    return int(proc.returncode)


def main() -> int:
    args = parse_args()
    watch_args = shlex.split(args.watch_args)
    interval = max(0.0, float(args.interval_seconds))
    max_cycles = max(0, int(args.max_cycles))

    cycles = 0
    while True:
        code = run_cycle(watch_args)
        if code != 0:
            return code
        cycles += 1
        if max_cycles and cycles >= max_cycles:
            return 0
        if interval:
            time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
