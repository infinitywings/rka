"""Tests for scripts/sanitize_knowledge_pack.py.

The sanitizer's job is to make an exported knowledge pack safe to publish. Two
failure modes matter and they pull in opposite directions: leaving something
private in, and mangling the research prose that is the whole point of the
sample. Every test here pins one or the other, and several encode a specific
mistake made while the rules were being written.
"""

from __future__ import annotations

import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "sanitize_knowledge_pack.py"
_spec = importlib.util.spec_from_file_location("pack_sanitizer", _SCRIPT)
assert _spec and _spec.loader
sanitizer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sanitizer)


SELF = sanitizer.SELF_PROJECT_ID
CROCKFORD = set(sanitizer._CROCKFORD)


def make_manifest(*entries: str) -> dict:
    return {
        "exported_at": "2026-08-24T00:00:00Z",
        "project": {"id": SELF, "name": "rka_development"},
        "tables": {
            "journal": [
                {"id": f"jrn_{i}", "project_id": SELF, "content": text}
                for i, text in enumerate(entries)
            ]
        },
    }


def sanitized_contents(*entries: str) -> list[str]:
    manifest = make_manifest(*entries)
    sanitizer.sanitize(manifest)
    return [row["content"] for row in manifest["tables"]["journal"]]


class TestRedaction:
    def test_home_directory_is_replaced(self):
        (out,) = sanitized_contents("logs are at /Users/someone/Desktop/run.log")
        assert "/Users/someone" not in out
        assert out == "logs are at /Users/researcher/Desktop/run.log"

    def test_workspace_volume_is_replaced(self):
        (out,) = sanitized_contents("checked out to /Volumes/FuSpace/Projects/rka")
        assert out == "checked out to /Volumes/Workspace/Projects/rka"

    def test_unrelated_volume_is_left_alone(self):
        """A mounted DMG carries no identity; only the workspace volume does."""
        (out,) = sanitized_contents("`/Volumes/RKA/RKA.app` passes codesign")
        assert out == "`/Volumes/RKA/RKA.app` passes codesign"

    def test_private_addresses_map_into_test_net(self):
        (out,) = sanitized_contents("backend at 192.168.86.21 and 10.0.0.5")
        assert "192.168." not in out and "10.0.0.5" not in out
        assert "192.0.2." in out

    def test_same_address_maps_consistently(self):
        out = sanitized_contents("host 192.168.86.21", "same host 192.168.86.21")
        first = out[0].split()[-1]
        assert out[1].endswith(first)

    def test_sibling_project_name_is_aliased(self):
        (out,) = sanitized_contents("data landed under Projects/Invarllm/data")
        assert "Invarllm" not in out
        assert "project-B" in out

    def test_own_project_id_is_never_rewritten(self):
        (out,) = sanitized_contents(f"concentrated in {SELF} (48 refs)")
        assert SELF in out

    def test_sibling_project_id_is_aliased(self):
        (out,) = sanitized_contents("1 ref in prj_01KN51HD73DSY9ZR9C56JYRNYZ")
        assert "prj_01KN51HD73DSY9ZR9C56JYRNYZ" not in out
        assert "prj_0000000000000000000000" in out

    def test_unmapped_project_id_still_gets_aliased(self):
        """A hand-maintained id list goes stale; an unmapped id must not leak."""
        (out,) = sanitized_contents("see prj_01ZZZZZZZZZZZZZZZZZZZZZZZZ for context")
        assert "prj_01ZZZZZZZZZZZZZZZZZZZZZZZZ" not in out
        assert "prj_0000000000000000000000" in out

    def test_third_party_names_are_removed(self):
        (out,) = sanitized_contents("Sunshine can recruit educators; NCSSM connection")
        assert "Sunshine" not in out and "NCSSM" not in out

    def test_course_identifiers_are_removed(self):
        (out,) = sanitized_contents("ITIS 3200 map from Canvas (course ID 235475)")
        assert "ITIS 3200" not in out and "235475" not in out

    def test_grant_fit_assessment_is_cut(self):
        entry = (
            "## NSF FINDERS FOUNDRY (nsf26-507) Solicitation Analysis\n\n"
            "### Program Overview\n- public terms\n\n"
            "### Key Fit Assessment\n\nInternal strategy naming a collaborator.\n"
        )
        (out,) = sanitized_contents(entry)
        assert "Internal strategy" not in out
        assert "Redacted for publication" in out
        # the public half is what makes the sample worth publishing
        assert "### Program Overview" in out and "public terms" in out


class TestOverReach:
    """Rules that fire on the wrong text are as damaging as rules that miss."""

    def test_nsf_career_program_is_not_aliased(self):
        """`CAREER` here is the NSF award program, not the sibling project.

        An earlier rule rewrote this to "NSF PAPPG/project-G support".
        """
        text = "58 venue profiles plus NSF PAPPG/CAREER support (#28)"
        (out,) = sanitized_contents(text)
        assert out == text

    def test_detectability_as_a_common_noun_survives(self):
        text = "the detectability of the attack drops at 50ms"
        (out,) = sanitized_contents(text)
        assert out == text

    def test_canvas_as_a_ui_surface_survives(self):
        text = "cluster review deserves the full canvas, not a sheet"
        (out,) = sanitized_contents(text)
        assert out == text

    def test_trace_vocabulary_survives(self):
        """`trace` is provenance vocabulary far more often than a codename."""
        text = "tags: source-trace, code-trace, trace-provenance"
        (out,) = sanitized_contents(text)
        assert out == text


class TestPlaceholderIds:
    @pytest.mark.parametrize("alias", sorted(set(sanitizer.PROJECT_ALIASES.values())))
    def test_placeholder_ids_are_valid_crockford_base32(self, alias):
        """ULID omits I, L, O and U — an alias letter cannot be the suffix.

        `project-L` once produced `prj_00…0L`, which import validation rejects.
        """
        pid = sanitizer._alias_id(alias)
        assert pid.startswith("prj_")
        assert len(pid) == 30
        assert set(pid[4:]) <= CROCKFORD

    def test_placeholder_ids_are_unique_across_aliases(self):
        aliases = set(sanitizer.PROJECT_ALIASES.values())
        assert len({sanitizer._alias_id(a) for a in aliases}) == len(aliases)

    def test_placeholder_ids_are_stable(self):
        assert sanitizer._alias_id("project-B") == sanitizer._alias_id("project-B")


class TestVerification:
    def test_verifier_flags_an_unsanitized_manifest(self):
        manifest = make_manifest(
            "path /Users/someone/x, host 192.168.1.1, ref prj_01KN51HD73DSY9ZR9C56JYRNYZ"
        )
        findings = sanitizer.verify(manifest)
        assert {"home_path", "private_ip", "foreign_project_id"} <= set(findings)

    def test_verifier_passes_after_sanitizing(self):
        manifest = make_manifest(
            "path /Users/someone/x, host 192.168.1.1, ref prj_01KN51HD73DSY9ZR9C56JYRNYZ, "
            "sibling Invarllm, Sunshine helped, ITIS 3200"
        )
        sanitizer.sanitize(manifest)
        assert sanitizer.verify(manifest) == {}

    def test_sanitizing_is_idempotent(self):
        manifest = make_manifest("/Users/a/x 192.168.1.1 Invarllm")
        sanitizer.sanitize(manifest)
        once = json.dumps(manifest, sort_keys=True)
        sanitizer.sanitize(manifest)
        assert json.dumps(manifest, sort_keys=True) == once


class TestStructure:
    def test_row_counts_are_preserved(self):
        manifest = make_manifest("a /Users/x/y", "b Invarllm", "c clean")
        before = len(manifest["tables"]["journal"])
        sanitizer.sanitize(manifest)
        assert len(manifest["tables"]["journal"]) == before

    def test_roundtrips_through_a_zip(self, tmp_path: Path):
        src, dst = tmp_path / "in.zip", tmp_path / "out.zip"
        manifest = make_manifest("path /Users/someone/x")
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("manifest.json", json.dumps(manifest))
        assert sanitizer.main([str(src), str(dst)]) == 0
        with zipfile.ZipFile(dst) as zf:
            out = json.load(zf.open("manifest.json"))
        assert "/Users/someone" not in out["tables"]["journal"][0]["content"]

    def test_check_mode_exits_nonzero_on_a_dirty_pack(self, tmp_path: Path):
        src = tmp_path / "in.zip"
        with zipfile.ZipFile(src, "w") as zf:
            zf.writestr("manifest.json", json.dumps(make_manifest("/Users/someone/x")))
        assert sanitizer.main([str(src), "--check"]) == 1
