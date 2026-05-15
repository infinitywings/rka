# RKA Tauri Shell

Tauri 2.x shell wrapping the bundled `rka-serve` sidecar. Hosts the
onboarding panel (D3), Settings tab (D4), Logs panel (D5), and the
multi-client verification suite (D8).

## Layout

```
tauri/
├── Cargo.toml
├── tauri.conf.json
├── build.rs
├── capabilities/default.json     # Tauri 2.x permission model
├── binaries/                     # PyInstaller-built sidecars land here
│                                 #   externalBin in tauri.conf.json refers
│                                 #   to `binaries/rka-serve` and
│                                 #   `binaries/rka-mcp`. The build flow
│                                 #   copies + renames them with the
│                                 #   platform-triple suffix Tauri expects.
├── icons/                        # icon.icns + macOS asset variants
└── src/
    ├── main.rs                   # bin entry
    ├── lib.rs                    # builder + commands
    ├── sidecar.rs                # rka-serve lifecycle + health-check
    ├── launcher.rs               # ~/Library/.../bin/rka-mcp.sh writer
    └── mcp_clients/              # per-client registry (D3 fleshes out)
        ├── mod.rs
        └── README.md
```

UI lives under `../ui-src/` (sibling directory).

## Build

```bash
# If your repo lives on a volume without full xattr support (external
# drives, SMB/AFP mounts, OneDrive/Dropbox/iCloud sync folders), route
# cargo's target dir off that volume — otherwise Tauri's permissions-file
# scanner trips on `._*.toml` companion files. See packaging/README.md
# "AppleDouble notes". No-op on stock APFS boot drives.
export CARGO_TARGET_DIR="$HOME/.cache/rka-tauri-target"

# Pre-flight: clean AppleDouble files (macOS mints these on affected volumes)
find . -maxdepth 6 -name '._*' -not -path './.git/*' -delete

# Build the sidecar binaries first
../pyinstaller/build.sh

# Copy + rename for Tauri's externalBin convention
mkdir -p binaries
cp ../pyinstaller/dist/rka-serve  binaries/rka-serve-aarch64-apple-darwin
cp ../pyinstaller/dist/rka-mcp    binaries/rka-mcp-aarch64-apple-darwin
# Add x86_64 variants for a universal build, then `lipo` if both targets exist

# Re-enable externalBin in tauri.conf.json AFTER the binaries land — the scaffold
# leaves it commented out so `cargo check` works without PyInstaller built artifacts.
# Add this block under `bundle`:
#   "externalBin": ["binaries/rka-serve", "binaries/rka-mcp"]

# Build the Tauri app (ad-hoc signed dev DMG)
cargo tauri build

# Tauri's bundle_dmg.sh uses Finder via AppleScript to apply a window
# layout to the DMG. That step times out unless macOS has explicitly
# granted the running shell permission to control Finder
# (Privacy & Security → Automation). When it times out, the .app is
# still built and ad-hoc-signed correctly — just the DMG wrapper
# fails. Run the bypass script to produce a functional UDZO DMG via
# hdiutil instead:
../build-dmg.sh
```

The resulting DMG lands at `target/release/bundle/dmg/RKA_*.dmg` (~80–120 MB depending on which sidecar variants are bundled). The bypass DMG has no fancy window layout (no background image, no drag-to-Applications arrow) — Phase 2 distribution with paid Developer ID + notarization can layer those on later.

## Development

```bash
cargo tauri dev
```

Starts a Vite dev server for the UI (port 5173) and a Rust debug build
that spawns the sidecar pointing at it.

## Cross-platform compile-only verification

Per the platform-agnostic-source commitment:

```bash
cargo check --target x86_64-unknown-linux-gnu
cargo check --target x86_64-pc-windows-msvc
```

These verify the source compiles for non-macOS targets without
producing distribution artifacts.

## Tauri 2.x notes

- `tauri-plugin-single-instance` enforces one running instance.
- Sidecar binaries are declared in `tauri.conf.json` `bundle.externalBin`
  and resolved at runtime via `app.path().resource_dir()`.
- Permissions live in `capabilities/default.json`.
- The macOS bundle uses ad-hoc signing (`signingIdentity: "-"`) for
  Phase 1 distribution. Phase 2 swaps in the Developer ID Application
  identity per `jrn_01KRH2M0CRXF9KW4RCG8TSCA2X`.
