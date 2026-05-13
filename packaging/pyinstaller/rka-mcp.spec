# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — bundled `rka mcp` stdio proxy.

The output binary (`dist/rka-mcp`) is the stateless MCP proxy. Each
supported client (Claude Desktop, Claude Code, Cursor, VSCode-Copilot,
Codex CLI, Codex Mac App, Antigravity) invokes this through the stable
launcher script `~/Library/Application Support/RKA/bin/rka-mcp.sh`,
which the Tauri shell rewrites on each app launch.
"""
from __future__ import annotations

import os
from pathlib import Path

SPEC_DIR = Path(os.path.abspath(SPECPATH))  # noqa: F821
PROJECT_ROOT = SPEC_DIR.parent.parent
ENTRY = str(SPEC_DIR / "entry_points" / "entry_mcp.py")
HOOKS_DIR = str(SPEC_DIR / "hooks")


hiddenimports = [
    "mcp",
    "mcp.server",
    "mcp.server.fastmcp",
    "mcp.server.stdio",
    "mcp.server.streamable_http",
    "httpx",
    "rka.mcp.server",
    "rka.cli",
]


a = Analysis(  # noqa: F821
    [ENTRY],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[HOOKS_DIR],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide6",
        "fastembed", "onnxruntime", "tokenizers", "sqlite_vec",
        "litellm", "instructor",
    ],
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
    name="rka-mcp",
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
