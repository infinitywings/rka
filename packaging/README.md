# RKA Desktop Packaging

This directory contains the macOS desktop-app packaging for RKA. It lives on the long-lived `release/desktop` branch and is **NOT** part of mainline development.

## Branch model

- **`main`** — RKA source. All feature work happens here. Versions ship as semver tags (e.g. `v2.3.5`).
- **`release/desktop`** — desktop-app packaging artifacts. Single long-lived branch; not version-suffixed. Pulls from `main` when a desktop release is cut.

The desktop branch packages every future RKA version. It does not fork per release.

## Layout

```
packaging/
├── pyinstaller/       # Python sidecar binaries (rka-serve, rka-mcp)
├── tauri/             # Rust + WKWebView shell, sidecar manager, onboarding UI
└── tests/             # Integration tests for the 7-client MCP-config onboarding matrix
```

## Cutting a release

1. From `main` at the version tag, merge into `release/desktop`:
   ```
   git checkout release/desktop
   git merge --no-ff v<version>
   ```
2. Run AppleDouble cleanup (FuSpace volumes mint `._*` resource forks that break builds):
   ```
   find . -maxdepth 2 -name '._*' -not -path './.git/*' -delete
   ```
3. Build the sidecar binaries:
   ```
   ./packaging/pyinstaller/build.sh
   ```
4. Build the Tauri app + DMG:
   ```
   cd packaging/tauri && cargo tauri build
   ```
5. Verify the DMG installs cleanly on a test Mac with no prior RKA install.

## FuSpace developer notes

If the working tree lives on the FuSpace volume (the original RKA developer's setup), macOS mints AppleDouble (`._*`) resource-fork files for every file written. This breaks both PyInstaller and Tauri's build scripts (which scan directories for `.toml` / data files and choke on the resource forks).

Two mitigations, used together:

1. **Pre-build AppleDouble purge** — `find . -maxdepth 6 -name '._*' -not -path './.git/*' -delete`. The `packaging/pyinstaller/build.sh` wrapper runs this automatically.
2. **Route cargo's target directory off FuSpace** — `export CARGO_TARGET_DIR="$HOME/.cache/rka-tauri-target"` before any `cargo check` / `cargo tauri build` / `cargo tauri dev`. Otherwise Tauri's permissions-file scanner trips over `._default.toml` resource forks under `target/debug/build/tauri-*/out/permissions/`.

Both mitigations are no-ops on non-FuSpace volumes.

## Phase 1 vs Phase 2 distribution

| Phase | Signing | Notarization | Apple Developer Program | User experience |
|-------|---------|--------------|-------------------------|-----------------|
| **1 (current)** | ad-hoc (`codesign --sign -`) | none | not required | first-launch Gatekeeper warning; right-click → Open once |
| **2 (deferred)** | Developer ID Application | `xcrun notarytool` + `xcrun stapler` | $99/year required | double-click works cleanly |

Phase 2 is gated on Phase 1 manual QA. See `jrn_01KRH2M0CRXF9KW4RCG8TSCA2X` for the full split.

## Supported MCP clients (7)

| # | Client | Config | Format | Root key |
|---|--------|--------|--------|----------|
| 1 | Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` | JSON | `mcpServers` |
| 2 | Claude Code | `~/.claude.json` (or `claude mcp add` CLI) | JSON | `mcpServers` |
| 3 | Cursor | `~/.cursor/mcp.json` | JSON | `mcpServers` |
| 4 | VSCode-Copilot | `~/Library/Application Support/Code/User/mcp.json` | JSON | **`servers`** (not `mcpServers`) |
| 5 | Codex CLI | `~/.codex/config.toml` | **TOML** | `[mcp_servers.rka]` |
| 6 | Codex Mac App | `~/.codex/config.toml` (shares with CLI) | TOML | `[mcp_servers.rka]` |
| 7 | Antigravity | `~/.gemini/antigravity/mcp_config.json` | JSON | (verify at impl time) |

Per-client schema details + the "how to add a new client" pattern live in `packaging/tauri/src/mcp_clients/README.md`.

## Mission provenance

- Mission: `mis_01KQJGR4WZXYFSDP9DN2WEXTJJ`
- Motivating decision: `dec_01KQJF65TPXDETP28WY5MA7ZBB` (Path A: Tauri + Python sidecar, macOS-only release, platform-agnostic source, no telemetry, RKA.app name)
- Feasibility plan: `jrn_01KQJCQ9C79R38Q48KE5AJ2VK2`
- Apple distribution research: `jrn_01KRH2M0CRXF9KW4RCG8TSCA2X`
- Multi-client amendment: `jrn_01KRH6Z85PEXHG1JTH7MQQM0GH`
- Brain calibration: `jrn_01KR4GVDXYRVTT6RXTX7BP3JW6` (audit-symmetry + grep-gate discipline applied to D3/D7)
