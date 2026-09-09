#!/usr/bin/env python3
"""
run.py: entry point for the evaluation run harness.

Thin CLI wrapper: parse the knobs and hand off to runner.Runner, which submits a
scenario's workload, watches the cluster, and writes the per-task metrics. The
implementation lives in the runner/ package (scenario, record, watchers,
recorder, output, core); this file is just the command line.

Every knob defaults to the scenario value. A --timeout-seconds of 0 means no
global timeout (the run ends only when every task is terminal).

Usage:
    python run.py --scenario scenarios/conflicts-rho020 --replica 0
    python run.py --scenario scenarios/conflicts-rho020 --replica 0 --timeout-seconds 0
    python run.py --scenario scenarios/overhead-rho000 --mode baseline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from runner import Runner

DEFAULT_PROGRESS_SECONDS = 1.0
DEFAULT_FLUSH_SECONDS = 30.0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Submit a scenario workload, watch the cluster, record metrics."
    )
    p.add_argument(
        "--scenario", required=True, help="path to a scenarios/<name> directory"
    )
    p.add_argument(
        "--replica",
        type=int,
        default=0,
        help="replica index (selects tasks_r<i>.csv and run_<i>/)",
    )
    p.add_argument(
        "--results", help="results directory (default results/<name>/run_<replica>)"
    )
    p.add_argument("--tasks-file", help="explicit tasks CSV (overrides the scenario's)")

    # Modulable knobs; None means "use the scenario value".
    p.add_argument(
        "--rate-seconds",
        type=float,
        dest="rate_seconds",
        help="override inter-arrival time",
    )
    p.add_argument(
        "--sanitize-interval-seconds",
        type=int,
        dest="sanitize_interval_seconds",
        help="override sanitize interval (used only for the timeout)",
    )
    p.add_argument("--namespace", help="override task namespace")
    p.add_argument(
        "--mode", choices=["system", "baseline"], help="override submission mode"
    )
    p.add_argument(
        "--timeout-seconds",
        type=float,
        dest="timeout_seconds",
        help="global run timeout; 0 means no timeout "
        "(default: submission span + 10 sanitize windows)",
    )
    p.add_argument(
        "--baseline-image", default="busybox:musl", help="image for baseline Jobs"
    )
    p.add_argument(
        "--progress-seconds",
        type=float,
        default=DEFAULT_PROGRESS_SECONDS,
        help="progress refresh interval",
    )
    p.add_argument(
        "--flush-seconds",
        type=float,
        default=DEFAULT_FLUSH_SECONDS,
        help="partial tasks.csv flush interval",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if not (Path(args.scenario) / "config.json").exists():
        raise SystemExit(f"error: {args.scenario}/config.json not found")
    return Runner(args).run()


if __name__ == "__main__":
    sys.exit(main())
