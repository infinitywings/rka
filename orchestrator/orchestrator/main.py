"""CLI entry point.

Scaffold stub — full implementation arrives with T7 (graph topology) and
T12 (pilot run). Today this exists so `pip install -e .` produces a
working entry-point binary and so the package imports cleanly.
"""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rka-orchestrator",
        description="RKA + LangGraph orchestrator (Phase 1).",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("version", help="Print orchestrator version")
    run = sub.add_parser("run", help="Execute one workflow thread end-to-end")
    run.add_argument("--mission-id", required=False)
    run.add_argument("--thread-id", required=False)
    run.add_argument("--budget-usd", type=float, default=5.0)
    return parser


def cli(argv: list[str] | None = None) -> int:
    from orchestrator import __version__

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in (None, "version"):
        print(f"rka-orchestrator {__version__}")
        return 0
    if args.command == "run":
        print(
            "[scaffold] `run` is unimplemented; arrives in T7+T12 "
            "(graph topology + pilot)."
        )
        return 0
    return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(cli())
