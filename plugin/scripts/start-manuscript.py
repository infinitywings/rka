#!/usr/bin/env python3
"""Compatibility wrapper for the atomic ``rka writer init`` workflow.

The workflow lives in the RKA package so the CLI and plugin cannot drift.  No
project default, credential substitution, or partial directory copy occurs in
this wrapper.
"""

from __future__ import annotations

import shutil
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    rka = shutil.which("rka")
    if rka is None:
        print("ERROR: rka is not on PATH; install the local RKA CLI first", file=sys.stderr)
        return 1
    result = subprocess.run(  # noqa: S603 - fixed executable resolved from PATH
        [rka, "writer", "init", *(argv if argv is not None else sys.argv[1:])],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
