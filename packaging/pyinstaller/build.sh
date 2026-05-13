#!/usr/bin/env bash
#
# Build the bundled rka-serve + rka-mcp sidecar binaries for the macOS .app.
#
# Pre-conditions:
#   - macOS Command Line Tools installed (xcode-select --install).
#   - uv (or pip + python 3.11+) on PATH.
#
# Side effects:
#   - Creates / refreshes the packaging-only virtualenv at packaging/.venv.
#   - Strips AppleDouble (._*) files before each spec build (FuSpace volumes
#     mint resource forks that break PyInstaller; see CLAUDE.md d2a9388).
#   - Writes binaries to packaging/pyinstaller/dist/{rka-serve,rka-mcp}.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGING_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${PACKAGING_DIR}/.." && pwd)"
VENV_DIR="${PACKAGING_DIR}/.venv"
DIST_DIR="${SCRIPT_DIR}/dist"
WORK_DIR="${SCRIPT_DIR}/build"

cleanup_apple_double() {
    local target="${1:-$PROJECT_ROOT}"
    find "${target}" -maxdepth 6 -name '._*' -not -path '*/.git/*' -delete 2>/dev/null || true
}

ensure_venv() {
    if [[ ! -d "${VENV_DIR}" ]]; then
        echo ">>> Creating packaging virtualenv at ${VENV_DIR}"
        if command -v uv >/dev/null 2>&1; then
            uv venv --python 3.11 "${VENV_DIR}"
        else
            python3 -m venv "${VENV_DIR}"
        fi
    fi

    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"

    echo ">>> Installing project + LLM extras + pyinstaller into packaging venv"
    if command -v uv >/dev/null 2>&1; then
        uv pip install --upgrade pip
        uv pip install -e "${PROJECT_ROOT}[llm]"
        uv pip install "pyinstaller>=6.10"
    else
        pip install --upgrade pip
        pip install -e "${PROJECT_ROOT}[llm]"
        pip install "pyinstaller>=6.10"
    fi
}

build_spec() {
    local spec="$1"
    local name
    name="$(basename "${spec}" .spec)"
    echo ">>> Building ${name}"
    cleanup_apple_double "${PROJECT_ROOT}"
    cleanup_apple_double "${SCRIPT_DIR}"

    pyinstaller \
        --noconfirm \
        --clean \
        --distpath "${DIST_DIR}" \
        --workpath "${WORK_DIR}" \
        "${spec}"

    # Strip any quarantine / resource-fork xattrs the build may have inherited.
    xattr -cr "${DIST_DIR}/${name}" 2>/dev/null || true
}

main() {
    cd "${PROJECT_ROOT}"
    ensure_venv
    rm -rf "${DIST_DIR}" "${WORK_DIR}"
    mkdir -p "${DIST_DIR}"

    build_spec "${SCRIPT_DIR}/rka-serve.spec"
    build_spec "${SCRIPT_DIR}/rka-mcp.spec"

    echo
    echo ">>> Bundled sidecar binaries:"
    ls -la "${DIST_DIR}/"
    echo
    echo "Sizes:"
    du -sh "${DIST_DIR}/"*
}

main "$@"
