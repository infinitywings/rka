# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — bundled `rka serve` sidecar.

The output binary (`dist/rka-serve`) is the long-running sidecar that the
Tauri shell spawns. It serves the FastAPI REST API + web UI on
127.0.0.1:9712, runs the background enrichment worker as a thread, and
exposes /api/health + /api/capabilities for the multi-client verification
suite (D8).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SPEC_DIR = Path(os.path.abspath(SPECPATH))  # noqa: F821 - SPECPATH injected by PyInstaller
PROJECT_ROOT = SPEC_DIR.parent.parent
ENTRY = str(SPEC_DIR / "entry_points" / "entry_serve.py")
HOOKS_DIR = str(SPEC_DIR / "hooks")


def _collect_data(rel_pattern: str, dest_prefix: str) -> list[tuple[str, str]]:
    base = PROJECT_ROOT
    out: list[tuple[str, str]] = []
    for path in base.glob(rel_pattern):
        if not path.is_file():
            continue
        rel = path.relative_to(base)
        dest = os.path.join(dest_prefix, str(rel.parent)) if rel.parent.parts else dest_prefix
        out.append((str(path), dest))
    return out


datas: list[tuple[str, str]] = []
datas += _collect_data("rka/db/*.sql", ".")
datas += _collect_data("rka/db/migrations/*.sql", ".")
datas += _collect_data("rka/skills/*.md", ".")
datas += _collect_data("rka/skills/**/*.md", ".")
datas += _collect_data("web/dist/index.html", ".")
datas += _collect_data("web/dist/assets/*", ".")
datas += _collect_data("web/dist/**/*", ".")

# FastAPI route modules — explicit imports in rka/api/app.py mean PyInstaller's
# static analysis usually finds them, but a couple are imported lazily inside
# lifespan(). Enumerate to be safe.
hiddenimports = [
    "rka.api.routes.academic",
    "rka.api.routes.artifacts",
    "rka.api.routes.audit",
    "rka.api.routes.checkpoints",
    "rka.api.routes.claims",
    "rka.api.routes.clusters",
    "rka.api.routes.context",
    "rka.api.routes.decisions",
    "rka.api.routes.enrich",
    "rka.api.routes.events",
    "rka.api.routes.graph",
    "rka.api.routes.hooks",
    "rka.api.routes.literature",
    "rka.api.routes.llm",
    "rka.api.routes.maintenance",
    "rka.api.routes.missions",
    "rka.api.routes.notes",
    "rka.api.routes.onboarding",
    "rka.api.routes.project",
    "rka.api.routes.research_map",
    "rka.api.routes.researcher_tools",
    "rka.api.routes.review_queue",
    "rka.api.routes.search",
    "rka.api.routes.summary",
    "rka.api.routes.tags",
    "rka.api.routes.topics",
    "rka.api.routes.workspace",
    # Lazy / dynamic imports inside service layer
    "rka.services.knowledge_pack",
    "rka.services.worker",
    "rka.services.workspace",
    # Embeddings stack (RKA_EMBEDDINGS_ENABLED=true by default in bundled sidecar)
    "fastembed",
    "fastembed.text",
    "fastembed.text.text_embedding",
    "onnxruntime",
    "tokenizers",
    "sqlite_vec",
    # LLM stack (config-driven; bundled for parity with full install)
    "litellm",
    "instructor",
    # uvicorn standard extras
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.uvloop",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]


a = Analysis(  # noqa: F821
    [ENTRY],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[HOOKS_DIR],
    hooksconfig={},
    runtime_hooks=[str(SPEC_DIR / "hooks" / "rt_rka_env.py")],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide6"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="rka-serve",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
