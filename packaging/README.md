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
2. Run AppleDouble cleanup (macOS mints `._*` AppleDouble files on volumes without full xattr support — external drives, SMB/AFP network mounts, OneDrive/Dropbox/iCloud sync folders, some case-insensitive filesystems — and these break builds):
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

## AppleDouble notes (volumes without full xattr support)

If your working tree lives on a volume without full xattr support — external drives, SMB/AFP network mounts, OneDrive/Dropbox/iCloud sync folders, certain case-insensitive filesystems — macOS mints AppleDouble (`._*`) companion files for every file written. This breaks both PyInstaller and Tauri's build scripts (which scan directories for `.toml` / data files and choke on the companion files). Stock APFS on the boot drive doesn't have this quirk; you can ignore this whole section if you cloned the repo into `~/Documents` or similar.

Two mitigations, used together:

1. **Pre-build AppleDouble purge** — `find . -maxdepth 6 -name '._*' -not -path './.git/*' -delete`. The `packaging/pyinstaller/build.sh` wrapper runs this automatically.
2. **Route cargo's target directory off the affected volume** — `export CARGO_TARGET_DIR="$HOME/.cache/rka-tauri-target"` before any `cargo check` / `cargo tauri build` / `cargo tauri dev`. `$HOME` lives on the stock APFS boot drive so AppleDouble files don't appear there. Otherwise Tauri's permissions-file scanner trips over `._default.toml` companion files under `target/debug/build/tauri-*/out/permissions/`.

Both mitigations are no-ops on stock APFS volumes.

## Phase 1 vs Phase 2 distribution

| Phase | Signing | Notarization | Apple Developer Program | User experience |
|-------|---------|--------------|-------------------------|-----------------|
| **1 (current)** | ad-hoc (`codesign --sign -`) | none | not required | first-launch Gatekeeper warning; right-click → Open once |
| **2 (deferred)** | Developer ID Application | `xcrun notarytool` + `xcrun stapler` | $99/year required | double-click works cleanly |

Phase 2 is gated on Phase 1 manual QA. See `jrn_01KRH2M0CRXF9KW4RCG8TSCA2X` for the full split.

### Phase 1 installer experience for end users

The DMG produced by `cargo tauri build` ships ad-hoc-signed. macOS's
Gatekeeper does not trust ad-hoc signatures by default, so the first
launch surfaces:

> "RKA" cannot be opened because it is from an unidentified developer.

To install:

1. Drag `RKA.app` from the mounted DMG into `/Applications/`.
2. **Right-click (or Control-click)** `RKA.app` in `/Applications/`.
3. Choose **Open** from the menu.
4. macOS shows a confirmation dialog naming the unidentified developer.
   Click **Open** to launch. The OS records this choice; future
   double-clicks work normally.

If macOS 15 Sequoia hides the right-click bypass, open
**System Settings → Privacy & Security**, scroll to the "Security"
section, and click **Open Anyway** next to the RKA.app reference that
appeared after the first blocked launch. Same effect, different
location.

Phase 2 (paid Developer ID + notarization) removes this step entirely.

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
