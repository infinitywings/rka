"""PyInstaller entry point for the bundled `rka serve` sidecar.

The bundled sidecar enables embeddings by default so semantic search works
out of the box on a fresh install. Users can override via env var.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("RKA_EMBEDDINGS_ENABLED", "true")

from rka.cli import main


def run() -> None:
    sys.argv = [sys.argv[0], "serve", *sys.argv[1:]]
    main()


if __name__ == "__main__":
    run()
