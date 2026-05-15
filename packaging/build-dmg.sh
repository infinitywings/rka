#!/usr/bin/env bash
#
# Package the already-built RKA.app into an ad-hoc-signed UDZO DMG.
#
# This wraps `cargo tauri build`'s output. Tauri 2.x runs its
# `bundle_dmg.sh` which uses Finder via AppleScript to set the DMG
# window layout — that step fails on macOS instances where
# System Settings → Privacy & Security → Automation hasn't granted
# Terminal (or whatever shell ran the build) permission to control
# Finder, surfacing as:
#
#   Finder got an error: AppleEvent timed out. (-1712)
#
# Phase 1 distribution doesn't need the fancy DMG window layout (no
# notarization, users get a Gatekeeper warning anyway). This script
# drives `hdiutil` directly to produce a functional DMG with the same
# ad-hoc-signed .app inside.
#
# Usage:
#   ./packaging/build-dmg.sh
#
# Prerequisites:
#   - `cargo tauri build` already run (RKA.app present under the
#     Tauri target directory).
#   - CARGO_TARGET_DIR set if you're routing target/ off a volume
#     where macOS mints AppleDouble (`._*`) companion files (external
#     drives, SMB/AFP mounts, sync folders, etc).

set -euo pipefail

TARGET_DIR="${CARGO_TARGET_DIR:-$HOME/.cache/rka-tauri-target}"
APP="${TARGET_DIR}/release/bundle/macos/RKA.app"
DMG_DIR="${TARGET_DIR}/release/bundle/dmg"
DMG_OUT="${DMG_DIR}/RKA_0.1.0_aarch64.dmg"

if [[ ! -d "${APP}" ]]; then
    echo "error: RKA.app not found at ${APP}" >&2
    echo "       run \`cargo tauri build\` first" >&2
    exit 1
fi

mkdir -p "${DMG_DIR}"
rm -f "${DMG_OUT}" "${DMG_DIR}"/rw.*.dmg

SCRATCH="$(mktemp -d)"
trap 'rm -rf "${SCRATCH}"' EXIT
cp -R "${APP}" "${SCRATCH}/"

echo ">>> creating UDZO DMG at ${DMG_OUT}"
hdiutil create \
    -volname RKA \
    -srcfolder "${SCRATCH}" \
    -format UDZO \
    -fs HFS+ \
    "${DMG_OUT}"

echo
echo ">>> verifying"
echo "    size: $(du -h "${DMG_OUT}" | cut -f1)"
echo "    path: ${DMG_OUT}"
echo "    ad-hoc signature on the bundled .app:"
SCRATCH_MOUNT="$(hdiutil attach -nobrowse -noverify "${DMG_OUT}" | tail -1 | awk '{print $NF}')"
codesign -dv --verbose=2 "${SCRATCH_MOUNT}/RKA.app" 2>&1 | grep -E '(Identifier|Signature|Format|Runtime Version)'
hdiutil detach "${SCRATCH_MOUNT}" > /dev/null

echo
echo "done."
