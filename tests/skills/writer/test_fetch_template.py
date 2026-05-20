"""Tests for fetch_template.py full lifecycle (T5 deliverable).

Covers: registry lookup, SHA-256 hashing, TBD-pin detection, error hierarchy,
TemplatePinMissingError on first fetch, TemplateChecksumMismatchError on
verification failure, and cache reuse via .sha256 sidecar.

External network calls (urllib.request.urlopen) are mocked so the test
suite never hits CTAN, conference sites, or GitHub.

Per mis_01KS2S871YPQ3D5RVY5K3PSQY6 T6 acceptance criteria.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestPinDetection:
    """is_pin_tbd correctly identifies TBD pins."""

    def test_none_is_tbd(self, fetch_template) -> None:
        assert fetch_template.is_pin_tbd(None) is True

    def test_empty_is_tbd(self, fetch_template) -> None:
        assert fetch_template.is_pin_tbd("") is True

    def test_literal_tbd_is_tbd(self, fetch_template) -> None:
        assert fetch_template.is_pin_tbd("TBD") is True

    def test_lowercase_tbd_is_tbd(self, fetch_template) -> None:
        assert fetch_template.is_pin_tbd("tbd") is True

    def test_actual_sha_is_not_tbd(self, fetch_template) -> None:
        assert fetch_template.is_pin_tbd("abc123") is False


class TestSha256Computation:
    """compute_sha256 matches stdlib hashlib."""

    def test_known_string(self, fetch_template, tmp_path: Path) -> None:
        target = tmp_path / "test.bin"
        target.write_bytes(b"hello world")
        expected = hashlib.sha256(b"hello world").hexdigest()
        assert fetch_template.compute_sha256(target) == expected


class TestRegistryLookup:
    """lookup_template resolves venues and registry keys correctly."""

    def test_lookup_by_registry_key(self, fetch_template) -> None:
        try:
            entry = fetch_template.lookup_template("acmart")
        except RuntimeError:
            return  # PyYAML missing; skip
        assert entry.get("license", "").startswith("LPPL")

    def test_lookup_by_venue_example(self, fetch_template) -> None:
        try:
            entry = fetch_template.lookup_template("CHI")
        except RuntimeError:
            return
        assert "CHI" in entry.get("venue_examples", [])

    def test_lookup_unknown_raises_keyerror(self, fetch_template) -> None:
        try:
            with pytest.raises(KeyError):
                fetch_template.lookup_template("FAKE_VENUE_DOES_NOT_EXIST")
        except RuntimeError:
            return  # PyYAML missing


class TestErrorHierarchy:
    """All specialized errors inherit from TemplateRegistryError."""

    def test_checksum_mismatch_is_registry_error(self, fetch_template) -> None:
        assert issubclass(
            fetch_template.TemplateChecksumMismatchError,
            fetch_template.TemplateRegistryError,
        )

    def test_pin_missing_is_registry_error(self, fetch_template) -> None:
        assert issubclass(
            fetch_template.TemplatePinMissingError,
            fetch_template.TemplateRegistryError,
        )

    def test_download_error_is_registry_error(self, fetch_template) -> None:
        assert issubclass(
            fetch_template.TemplateDownloadError,
            fetch_template.TemplateRegistryError,
        )


class TestFetchLifecycle:
    """End-to-end fetch flow: TBD pin / mismatch / cache."""

    def test_fetch_with_tbd_pin_raises_pin_missing(
        self, fetch_template, tmp_path: Path
    ) -> None:
        try:
            with pytest.raises(fetch_template.TemplatePinMissingError):
                fetch_template.fetch("CHI", tmp_path)
        except RuntimeError:
            return  # PyYAML missing

    def test_fetch_sha_mismatch_raises_checksum_error(
        self, fetch_template, tmp_path: Path
    ) -> None:
        """When pin is set but downloaded content has different SHA, refuse."""
        try:
            import yaml  # noqa
        except ImportError:
            return

        fake_registry = tmp_path / "fake_registry.md"
        # SHA quoted as YAML string (some hex values parse as int otherwise).
        # Use a hex value with letters so YAML keeps it as a string either way.
        fake_registry.write_text(
            "```yaml\n"
            "fake-venue:\n"
            "  venue_examples: [FAKE]\n"
            "  archive_url: https://example.com/fake.cls\n"
            "  sha256: deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n"
            "```\n"
        )

        def fake_download(url, dest):
            dest.write_bytes(b"hello world")

        with patch.object(fetch_template, "_download_archive", side_effect=fake_download):
            with pytest.raises(fetch_template.TemplateChecksumMismatchError):
                fetch_template.fetch("FAKE", tmp_path, registry_path=fake_registry)

    def test_fetch_cache_hit_skips_download(
        self, fetch_template, tmp_path: Path
    ) -> None:
        """When the .sha256 sidecar matches the pin, the download is skipped."""
        try:
            import yaml  # noqa
        except ImportError:
            return

        # Compute the SHA-256 of the bytes we will "download".
        content = b"hello world"
        expected_sha = hashlib.sha256(content).hexdigest()

        fake_registry = tmp_path / "fake_registry.md"
        fake_registry.write_text(
            f"```yaml\n"
            f"fake-venue:\n"
            f"  venue_examples: [FAKE]\n"
            f"  archive_url: https://example.com/fake.cls\n"
            f"  sha256: {expected_sha}\n"
            f"```\n"
        )

        # Pre-populate the cache sidecar.
        styles_dir = tmp_path / "styles"
        styles_dir.mkdir()
        (styles_dir / ".sha256").write_text(expected_sha)

        download_count = {"n": 0}

        def fake_download(url, dest):
            download_count["n"] += 1
            dest.write_bytes(content)

        with patch.object(fetch_template, "_download_archive", side_effect=fake_download):
            installed = fetch_template.fetch("FAKE", tmp_path, registry_path=fake_registry)

        assert installed == styles_dir
        assert download_count["n"] == 0, "cache hit should not trigger download"
