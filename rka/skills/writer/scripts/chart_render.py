#!/usr/bin/env python3
"""chart_render.py: Phase 1 chart rendering skeleton with venue presets.

Phase 1 scope: import-time verification that matplotlib + seaborn are
available; venue preset stub for CHI and EMNLP; actual chart logic raises
NotImplementedError because the PI fills it in per manuscript.

Phase 2 scope: standard chart styles per venue with tueplots and SciencePlots
preset bundles, dataset-to-plot helpers, and integration with the manuscript
manifest for figure-prompt jrn_ tracking per dec_01KS0BKJ5ZJKJ4R19GYAK3QN9D Q6
(Paper Banana prompts stored as figure-prompt-tagged jrn_ entries).

CLI:
    python chart_render.py --check          # report dependency status
    python chart_render.py --venue CHI ...  # Phase 1 stub: raises NotImplementedError

Exit codes:
    0: dependency check successful
    1: required dependencies missing
    2: not implemented (Phase 1 stub call)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


_REQUIRED_OK = True
_REQUIRED_MISSING: list[str] = []
_OPTIONAL_MISSING: list[str] = []

try:
    import matplotlib  # type: ignore
    import matplotlib.pyplot as plt  # type: ignore
except ImportError:
    _REQUIRED_OK = False
    _REQUIRED_MISSING.append("matplotlib")

try:
    import seaborn  # type: ignore
except ImportError:
    _REQUIRED_OK = False
    _REQUIRED_MISSING.append("seaborn")

try:
    from tueplots import bundles  # type: ignore  # noqa: F401
except ImportError:
    _OPTIONAL_MISSING.append("tueplots (optional venue preset; required for Phase 2)")

try:
    import scienceplots  # type: ignore  # noqa: F401
except ImportError:
    _OPTIONAL_MISSING.append("SciencePlots (optional venue preset; required for Phase 2)")


def venue_preset(venue: str) -> dict:
    """Return matplotlib rcParams for the given venue.

    Phase 1: minimal hard-coded presets for CHI and EMNLP. Phase 2 will
    pull from tueplots.bundles and scienceplots styles per venue config.
    """
    presets = {
        "CHI": {
            "figure.figsize": (3.5, 2.5),
            "font.size": 9,
            "axes.labelsize": 8,
            "axes.titlesize": 9,
            "legend.fontsize": 7,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
        },
        "EMNLP": {
            "figure.figsize": (3.0, 2.25),
            "font.size": 9,
            "axes.labelsize": 8,
            "axes.titlesize": 9,
            "legend.fontsize": 7,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
        },
    }
    return presets.get(venue, presets.get("CHI", {}))


def apply_preset(venue: str) -> None:
    """Apply a venue preset to matplotlib's rcParams. Phase 1 helper."""
    if not _REQUIRED_OK:
        raise RuntimeError(
            "chart_render: matplotlib unavailable; cannot apply preset. "
            f"Missing: {', '.join(_REQUIRED_MISSING)}"
        )
    preset = venue_preset(venue)
    matplotlib.rcParams.update(preset)


def render_chart(spec: dict, venue: str, output_path: Path) -> Path:
    """Render a chart per spec to output_path. PI fills in chart logic per manuscript.

    Phase 1: raises NotImplementedError. The PI authors per-manuscript chart
    code using matplotlib + seaborn + apply_preset(venue) as the scaffolding.
    The spec dict shape will be standardized in Phase 2 (e.g., spec carries
    chart_type, data_path, x, y, hue, palette, annotations).
    """
    raise NotImplementedError(
        "chart_render.render_chart is a Phase 1 skeleton. "
        "PI authors per-manuscript chart logic using matplotlib + seaborn "
        "and apply_preset(venue) as scaffolding. "
        "Phase 2 will standardize chart specs per venue. "
        "See references/architecture.md for the Phase 2 design."
    )


def check_dependencies() -> tuple[bool, list[str], list[str]]:
    """Return (required_ok, required_missing, optional_missing)."""
    return _REQUIRED_OK, list(_REQUIRED_MISSING), list(_OPTIONAL_MISSING)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Chart rendering skeleton.")
    parser.add_argument("--check", action="store_true",
                        help="Report dependency availability and exit.")
    parser.add_argument("--venue", default=None, help="Venue name (e.g., CHI, EMNLP).")
    parser.add_argument("--spec", default=None, help="Path to chart spec JSON (Phase 2).")
    parser.add_argument("--output", default=None, help="Output figure path (Phase 2).")
    args = parser.parse_args(argv)

    if args.check or (args.venue is None and args.spec is None):
        print(f"chart_render.py Phase 1 skeleton")
        print(f"  matplotlib + seaborn available: {_REQUIRED_OK}")
        if _REQUIRED_MISSING:
            print(f"  Required missing: {', '.join(_REQUIRED_MISSING)}")
        if _OPTIONAL_MISSING:
            print(f"  Optional missing: {', '.join(_OPTIONAL_MISSING)}")
        return 0 if _REQUIRED_OK else 1

    print(
        "chart_render.py Phase 1 stub: actual chart rendering is the PI's per-manuscript "
        "responsibility. Use apply_preset(venue) as scaffolding and author chart logic "
        "inline. Phase 2 will standardize. See references/architecture.md.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
