"""Cross-platform regression tests for CLI console output."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_serve_banner_survives_a_legacy_cp1252_console(tmp_path: Path):
    code = """
import sys
import types

uvicorn = types.ModuleType("uvicorn")
uvicorn.run = lambda *args, **kwargs: None
sys.modules["uvicorn"] = uvicorn

from rka.cli import main

main.main(
    args=["serve", "--host", "127.0.0.1", "--port", "9712"],
    standalone_mode=False,
)
"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"
    env["RKA_DATA_DIR"] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Starting RKA server at http://127.0.0.1:9712" in result.stdout
