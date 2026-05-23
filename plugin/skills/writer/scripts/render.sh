#!/usr/bin/env bash
# render.sh: Wrap latexmk for Writer skill local PDF builds.
#
# Engine selection via LATEX_ENGINE env var (default pdflatex). Runs from the
# manuscript working directory with .latexmkrc setting TEXINPUTS=./styles//:
# so vendored venue templates resolve correctly.
#
# Usage:
#     ./scripts/render.sh                      # builds main.tex
#     ./scripts/render.sh other.tex            # builds other.tex
#     LATEX_ENGINE=lualatex ./scripts/render.sh
#     LATEX_ENGINE=xelatex ./scripts/render.sh
#
# Exit codes:
#     0: render succeeded
#     1: latexmk reported errors
#     2: unsupported LATEX_ENGINE value
#     3: latexmk not on PATH

set -euo pipefail

ENGINE="${LATEX_ENGINE:-pdflatex}"
TARGET="${1:-main.tex}"

if ! command -v latexmk >/dev/null 2>&1; then
    echo "render.sh: latexmk not on PATH; install TeX Live (texlive-full or equivalent)." >&2
    exit 3
fi

case "$ENGINE" in
    pdflatex)
        ENGINE_FLAGS=("-pdf")
        ;;
    lualatex)
        ENGINE_FLAGS=("-pdflua")
        ;;
    xelatex)
        ENGINE_FLAGS=("-pdfxe")
        ;;
    *)
        echo "render.sh: unsupported LATEX_ENGINE: $ENGINE" >&2
        echo "  Supported: pdflatex (default), lualatex, xelatex" >&2
        exit 2
        ;;
esac

echo "render.sh: building $TARGET with $ENGINE"
exec latexmk \
    "${ENGINE_FLAGS[@]}" \
    -interaction=nonstopmode \
    -file-line-error \
    -synctex=1 \
    "$TARGET"
