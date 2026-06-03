"""RKA cred-vault subsystem — local-first credential management.

Phase 1 scope: global creds only (no per-project addons), file layout
under $XDG_CONFIG_HOME/rka (fallback ~/.config/rka), drift detection
against Claude Desktop, Claude Code, rka-server, rka-orchestrator,
and host binaries.

The `cred` click group is exported here and registered on the main
CLI via `from rka.cli_cred import cred; main.add_command(cred)`.
"""

from __future__ import annotations

from rka.cli_cred.commands import cred

__all__ = ["cred"]
