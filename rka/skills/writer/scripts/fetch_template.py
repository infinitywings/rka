#!/usr/bin/env python3
"""fetch_template.py: LaTeX template registry + Phase 2 full fetch lifecycle.

Phase 2 (mis_01KS2S871YPQ3D5RVY5K3PSQY6 T5) upgrades the Phase 1 lookup-only
stub to a full fetch lifecycle:

  1. lookup_template(venue): read references/template_registry.md, return entry.
  2. fetch(venue, target_dir): download archive_url to a temp file, compute
     SHA-256, compare to registry pin, refuse on mismatch, otherwise extract
     into target_dir/styles/ and write a .sha256 sidecar for cache reuse.
  3. Cache reuse: subsequent calls verify the sidecar against the registry
     pin; matching pin skips the download.
  4. PI pin ratification: when the registry pin is `TBD` (first fetch on a
     workstation), download + compute SHA-256, write to a `.sha256.pending`
     sidecar, and exit with TemplatePinMissingError so the PI can ratify
     and update the registry.

LPPL Component-1 discipline: vendor templates verbatim under
manuscripts/<project>/<venue>/styles/. Never modify a class file in place;
project-specific commands go in a wrapper class authored by the PI.

CLI:
    python fetch_template.py --venue CHI                       # registry lookup
    python fetch_template.py --venue CHI --target styles       # fetch + verify
    python fetch_template.py --venue CHI --target styles --force  # ignore cache

Exit codes:
    0: lookup or fetch succeeded
    1: venue not in registry
    2: registry file not found or unreadable
    3: PI pin missing (TBD); .sha256.pending written for PI to ratify
    4: usage error
    5: TemplateChecksumMismatchError (SHA-256 verification refused)
    6: download network error

See references/template_registry.md for the registry schema and license matrix.
See dec_01KS2S22VV5P5SWWXNBXQDHMGX for the Phase 2 scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "references" / "template_registry.md"

# Standard request timeout (seconds) for upstream archive downloads.
DOWNLOAD_TIMEOUT_SECONDS = 60

# User-Agent header for politeness; some CTAN and conference sites rate-limit
# anonymous urllib requests.
DEFAULT_USER_AGENT = "rka-writer-tools/2.0 (https://github.com/infinitywings/rka)"


class TemplateRegistryError(Exception):
    """Base class for fetch_template errors."""


class TemplateChecksumMismatchError(TemplateRegistryError):
    """SHA-256 of downloaded archive does not match the registry pin."""

    def __init__(self, venue: str, expected: str, actual: str):
        super().__init__(
            f"SHA-256 mismatch for {venue}: expected {expected}, got {actual}. "
            "Refusing to install. Either the upstream has changed (rotate the "
            "registry pin via Brain ratification per LPPL discipline) or the "
            "download was corrupted."
        )
        self.venue = venue
        self.expected = expected
        self.actual = actual


class TemplatePinMissingError(TemplateRegistryError):
    """Registry entry has pinned_version=TBD or sha256=TBD; needs PI ratification."""

    def __init__(self, venue: str, computed_sha: str, archive_url: str):
        super().__init__(
            f"Registry pin for {venue} is TBD. Computed SHA-256: {computed_sha}. "
            f"Archive URL: {archive_url}. Ratify the pin in the registry, then "
            "re-run fetch."
        )
        self.venue = venue
        self.computed_sha = computed_sha
        self.archive_url = archive_url


class TemplateDownloadError(TemplateRegistryError):
    """Failed to download the archive (network or HTTP error)."""


# ---- Registry lookup -----------------------------------------------------


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

    if venue in registry:
        return registry[venue]
    for key, entry in registry.items():
        if isinstance(entry, dict):
            examples = entry.get("venue_examples", [])
            if venue in examples:
                return entry
    raise KeyError(f"venue {venue!r} not in registry")


# ---- Fetch lifecycle (Phase 2) -------------------------------------------


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 of a file's contents and return the hex digest."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_pin_tbd(value) -> bool:
    """Return True if a registry pin field is unset or placeholder 'TBD'.

    Defensive against non-string values (e.g., YAML parsing a numeric-only
    SHA-256 hex string as int). Treats numeric 0, empty/None, and the
    literal string 'TBD' (case-insensitive) as TBD; any other non-empty
    value is treated as set.
    """
    if not value:
        return True
    if not isinstance(value, str):
        return False
    return value.strip().upper() == "TBD"


def _cache_valid(styles_dir: Path, expected_sha: str) -> bool:
    """Return True if the cache sidecar matches the expected SHA-256."""
    sidecar = styles_dir / ".sha256"
    if not sidecar.exists():
        return False
    try:
        return sidecar.read_text(encoding="utf-8").strip() == expected_sha.strip()
    except OSError:
        return False


def _download_archive(archive_url: str, dest: Path) -> None:
    """Download archive_url to dest. Raises TemplateDownloadError on failure."""
    req = urllib.request.Request(
        archive_url,
        headers={"User-Agent": DEFAULT_USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            with dest.open("wb") as out:
                shutil.copyfileobj(response, out)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        raise TemplateDownloadError(
            f"failed to download {archive_url}: {exc}"
        ) from exc


def _extract_archive(archive_path: Path, dest_dir: Path) -> list[str]:
    """Extract archive_path into dest_dir. Returns list of installed file names.

    Supports .zip, .tar / .tar.gz / .tgz, and single-file .cls / .sty / .bst
    (copied verbatim). Returns names relative to dest_dir.
    """
    import tarfile
    import zipfile

    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = "".join(archive_path.suffixes).lower()

    if suffix.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(dest_dir)
            return zf.namelist()
    if suffix.endswith(".tar.gz") or suffix.endswith(".tgz"):
        with tarfile.open(archive_path, "r:gz") as tf:
            tf.extractall(dest_dir)
            return [m.name for m in tf.getmembers()]
    if suffix.endswith(".tar"):
        with tarfile.open(archive_path, "r:") as tf:
            tf.extractall(dest_dir)
            return [m.name for m in tf.getmembers()]
    # Single-file template (class or style file)
    if any(suffix.endswith(ext) for ext in (".cls", ".sty", ".bst")):
        target = dest_dir / archive_path.name
        shutil.copy(archive_path, target)
        return [archive_path.name]
    # Fallback: treat as opaque single file
    target = dest_dir / archive_path.name
    shutil.copy(archive_path, target)
    return [archive_path.name]


def fetch(
    venue: str,
    target_dir: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    force: bool = False,
) -> Path:
    """Fetch + verify + cache a venue template archive.

    Process:
      1. Resolve registry entry for venue.
      2. Read archive_url and expected sha256 pins.
      3. If either pin is 'TBD': download to a tmp file, compute SHA-256,
         write .sha256.pending sidecar, raise TemplatePinMissingError.
      4. Otherwise check the styles_dir/.sha256 sidecar against the expected
         pin; if match and not force, return cache path.
      5. Otherwise download, compute SHA-256, compare against the pin; on
         mismatch raise TemplateChecksumMismatchError; on match extract into
         styles_dir and write the .sha256 sidecar.

    Args:
        venue: Venue name or registry key (CHI, EMNLP, USENIX-Security, etc.).
        target_dir: Manuscript working directory. The function writes to
            target_dir / "styles".
        registry_path: Override the default registry location (for tests).
        force: When True, re-download even if the cache sidecar matches.

    Returns:
        The styles directory path where the template was installed.

    Raises:
        TemplatePinMissingError: archive_url or sha256 is 'TBD'.
        TemplateChecksumMismatchError: SHA-256 verification failed.
        TemplateDownloadError: network or HTTP error.
        KeyError: venue not in registry.
    """
    entry = lookup_template(venue, registry_path=registry_path)
    archive_url = entry.get("archive_url")
    expected_sha = entry.get("sha256")

    if is_pin_tbd(archive_url):
        raise TemplatePinMissingError(
            venue, computed_sha="(no_url_to_download)", archive_url="(TBD)"
        )

    styles_dir = target_dir / "styles"
    styles_dir.mkdir(parents=True, exist_ok=True)

    if not is_pin_tbd(expected_sha):
        if _cache_valid(styles_dir, expected_sha) and not force:
            return styles_dir

    # Download to a temp file (we keep the original filename hint).
    archive_name = archive_url.rsplit("/", 1)[-1] or f"{venue}_template"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / archive_name
        _download_archive(archive_url, tmp_path)
        computed_sha = compute_sha256(tmp_path)

        if is_pin_tbd(expected_sha):
            pending_sidecar = styles_dir / ".sha256.pending"
            pending_sidecar.write_text(computed_sha, encoding="utf-8")
            raise TemplatePinMissingError(
                venue, computed_sha=computed_sha, archive_url=archive_url
            )

        if computed_sha != expected_sha:
            raise TemplateChecksumMismatchError(
                venue, expected=expected_sha, actual=computed_sha
            )

        # SHA matches and pin is set: extract, write sidecar.
        _extract_archive(tmp_path, styles_dir)
        (styles_dir / ".sha256").write_text(computed_sha, encoding="utf-8")

    return styles_dir


# ---- CLI -----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LaTeX template registry lookup + Phase 2 fetch lifecycle."
    )
    parser.add_argument("--venue", required=True,
                        help="Venue or registry key (e.g., CHI, EMNLP, USENIX-Security)")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY,
                        help="Path to template_registry.md")
    parser.add_argument("--target", type=Path, default=None,
                        help="Manuscript working directory; triggers Phase 2 fetch into target/styles/")
    parser.add_argument("--force", action="store_true",
                        help="Re-download even if SHA-256 cache sidecar matches")
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
            installed_dir = fetch(
                args.venue,
                args.target,
                registry_path=args.registry,
                force=args.force,
            )
        except TemplatePinMissingError as exc:
            print(f"fetch_template: {exc}", file=sys.stderr)
            return 3
        except TemplateChecksumMismatchError as exc:
            print(f"fetch_template: {exc}", file=sys.stderr)
            return 5
        except TemplateDownloadError as exc:
            print(f"fetch_template: {exc}", file=sys.stderr)
            return 6
        except KeyError as exc:
            print(f"fetch_template: {exc}", file=sys.stderr)
            return 1
        print(f"installed at: {installed_dir}", file=sys.stderr)

    print(json.dumps(entry, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
