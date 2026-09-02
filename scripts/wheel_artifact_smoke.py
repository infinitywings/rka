#!/usr/bin/env python3
"""Install one built Core wheel and run the startup smoke outside the checkout."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def venv_python(environment: Path) -> Path:
    """Return the interpreter path for a venv on Windows or POSIX."""
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def one_wheel(wheel_dir: Path) -> Path:
    wheels = sorted(wheel_dir.glob("rka_core-*.whl"))
    if len(wheels) != 1:
        rendered = ", ".join(path.name for path in wheels) or "none"
        raise RuntimeError(f"expected exactly one rka_core wheel in {wheel_dir}, found: {rendered}")
    return wheels[0].resolve()


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--wheel-dir",
        type=Path,
        default=ROOT / "dist",
        help="Directory containing exactly one rka_core-*.whl artifact.",
    )
    args = parser.parse_args()

    wheel = one_wheel(args.wheel_dir.expanduser().resolve())
    with tempfile.TemporaryDirectory(prefix="rka-wheel-artifact-smoke-") as temp:
        temp_root = Path(temp)
        environment = temp_root / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        python = venv_python(environment)
        if not python.is_file():
            raise RuntimeError(f"venv interpreter was not created at {python}")

        run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheel),
            ]
        )
        run(
            [
                str(python),
                str(ROOT / "scripts" / "core_startup_smoke.py"),
                "--python",
                str(python),
                "--cwd",
                str(temp_root / "cwd"),
            ]
        )

    print(f"Wheel artifact smoke passed: {wheel.name} on {sys.platform}.")


if __name__ == "__main__":
    main()
