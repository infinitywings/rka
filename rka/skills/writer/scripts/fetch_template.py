#!/usr/bin/env python3
"""fetch_template.py: LaTeX template registry lookup (Phase 1 stub).

Phase 1 implements registry lookup only. Reads references/template_registry.md
and returns the YAML entry for a given venue. Actual archive fetching, SHA-256
verification, and installation into manuscripts/<project>/<venue>/styles/ land
in Phase 2.

CLI:
    python fetch_template.py --venue CHI                 # show registry entry
    python fetch_template.py --venue EMNLP               # show registry entry
    python fetch_template.py --venue CHI --target styles # Phase 2: NotImplementedError

Exit codes:
    0: lookup succeeded
    1: venue not in registry
    2: registry file not found or unreadable
    3: NotImplementedError (Phase 2 fetch requested)
    4: usage error

See references/template_registry.md for the registry schema and license matrix.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional


# The registry file lives at rka/skills/writer/references/template_registry.md.
DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "references" / "template_registry.md"

PHASE_2_FETCH_NOTE = (
    "Phase 2 deliverable. fetch_template.py Phase 1 implements registry lookup "
    "only. PI fetches templates manually using the install_command listed per "
    "registry entry. See references/template_registry.md for the full lifecycle."
)


def load_registry_yaml(registry_path: Path) -> str:
    """Extract the YAML block from references/template_registry.md.

    The registry markdown contains a single fenced YAML block.
    Returns the YAML text (without fence markers).
    """
    if not registry_path.exists():
        raise FileNotFoundError(f"registry not found: {registry_path}")
    text = registry_path.read_text(encoding="utf-8")
    match = re.search(r"```yaml\n(.*?)\n```", text, re.DOTALL)
    if not match:
        raise ValueError("no fenced YAML block found in registry")
    return match.group(1)


def lookup_template(venue: str, registry_path: Path = DEFAULT_REGISTRY) -> dict:
    """Look up a venue's registry entry.

    Returns a dict with keys like venue_examples, source, license,
    pinned_version, archive_url, sha256, notes. Raises KeyError if the
    venue is not present.
    """
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "fetch_template requires PyYAML for registry parsing. "
            "Install with: pip install pyyaml"
        ) from exc

    yaml_text = load_registry_yaml(registry_path)
    registry = yaml.safe_load(yaml_text) or {}

    # Search by exact key (e.g., "acmart"), or by venue_examples membership.
    if venue in registry:
        return registry[venue]
    for key, entry in registry.items():
        if isinstance(entry, dict):
            examples = entry.get("venue_examples", [])
            if venue in examples:
                return entry
    raise KeyError(f"venue {venue!r} not in registry")


def fetch(venue: str, target_dir: Path) -> None:
    """Fetch a template archive, verify SHA-256, and install to target_dir.

    Phase 1: raises NotImplementedError. Phase 2 will:
      1. Look up the registry entry.
      2. Download archive_url to a temp file.
      3. Compute SHA-256 and compare to the pinned sha256.
      4. Refuse on mismatch; install on match.
    """
    raise NotImplementedError(
        f"fetch_template.fetch({venue!r}) Phase 1 stub. " + PHASE_2_FETCH_NOTE
    )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="LaTeX template registry lookup (Phase 1 stub)."
    )
    parser.add_argument("--venue", required=True,
                        help="Venue or registry key (e.g., CHI, EMNLP, acmart)")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY,
                        help="Path to template_registry.md")
    parser.add_argument("--target", type=Path, default=None,
                        help="Target install directory (triggers Phase 2 fetch; NotImplementedError)")
    args = parser.parse_args(argv)

    try:
        entry = lookup_template(args.venue, registry_path=args.registry)
    except FileNotFoundError as exc:
        print(f"fetch_template: {exc}", file=sys.stderr)
        return 2
    except KeyError as exc:
        print(f"fetch_template: {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError) as exc:
        print(f"fetch_template: {exc}", file=sys.stderr)
        return 2

    if args.target is not None:
        try:
            fetch(args.venue, args.target)
        except NotImplementedError as exc:
            print(f"fetch_template: {exc}", file=sys.stderr)
            return 3

    import json
    print(json.dumps(entry, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
