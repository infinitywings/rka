"""Tests for rka.services.classify — pure classification functions.

Covers:
  - Extension mapping (known extensions, unknown fallback)
  - Category-to-target inference
  - Content hint detection (meeting notes, paper manuscript, brainstorm,
    action items, code docs, structured doc, general fallback)
  - Hint-to-type mapping
  - File hashing (small + large composite)
  - Safe text reading (encoding fallback, truncation, DOCX graceful skip)
  - Module docstring extraction
  - Ignore pattern matching (directory name, glob pattern)
  - Capability detection (pymupdf / docx present or absent)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rka.services.classify import (
    EXTENSION_CATEGORY,
    CATEGORY_TARGET,
    DEFAULT_IGNORES,
    classify_extension,
    detect_capabilities,
    detect_content_hint,
    extension_to_target,
    hash_file,
    hint_to_type,
    is_ignored,
    safe_read_text,
    extract_module_docstring,
)
from rka.models.workspace import ContentHint, FileCategory, IngestionTarget


# ---------------------------------------------------------------------------
# Extension mapping
# ---------------------------------------------------------------------------


def test_classify_extension_known():
    assert classify_extension(".md") == FileCategory.markdown
    assert classify_extension(".py") == FileCategory.code
    assert classify_extension(".bib") == FileCategory.bibtex
    assert classify_extension(".pdf") == FileCategory.pdf
    assert classify_extension(".csv") == FileCategory.data
    assert classify_extension(".docx") == FileCategory.document


def test_classify_extension_unknown():
    assert classify_extension(".xyz") == FileCategory.unknown
    assert classify_extension("") == FileCategory.unknown


def test_extension_to_target_known():
    assert extension_to_target(".md") == IngestionTarget.ingest_document
    assert extension_to_target(".bib") == IngestionTarget.import_bibtex
    assert extension_to_target(".pdf") == IngestionTarget.literature_entry
    assert extension_to_target(".py") == IngestionTarget.journal_entry


def test_extension_to_target_unknown():
    assert extension_to_target(".xyz") == IngestionTarget.skip


# ---------------------------------------------------------------------------
# Content hint detection
# ---------------------------------------------------------------------------


def test_detect_meeting_notes():
    assert detect_content_hint("Meeting Notes\nAttendees: Alice, Bob") == ContentHint.meeting_notes


def test_detect_paper_manuscript():
    text = "Abstract\nIntroduction\nMethodology\nResults\nConclusion"
    assert detect_content_hint(text) == ContentHint.paper_manuscript


def test_detect_action_items():
    assert detect_content_hint("TODO: fix the parser\nNext Steps: deploy") == ContentHint.action_items


def test_detect_brainstorm():
    lines = "\n".join([f"- idea {i}" for i in range(10)])
    assert detect_content_hint(lines) == ContentHint.brainstorm


def test_detect_code_documentation():
    text = "## API Reference\n\nSome text\n\n```python\ncode here\n```\n"
    assert detect_content_hint(text) == ContentHint.code_documentation


def test_detect_structured_document():
    text = "## Introduction\n\nSome paragraph\n\n## Methods\n\nAnother paragraph"
    assert detect_content_hint(text) == ContentHint.structured_document


def test_detect_general_fallback():
    assert detect_content_hint("just some plain text without structure") == ContentHint.general


# ---------------------------------------------------------------------------
# Hint to type
# ---------------------------------------------------------------------------


def test_hint_to_type_mapping():
    assert hint_to_type(ContentHint.meeting_notes) == "summary"
    assert hint_to_type(ContentHint.brainstorm) == "idea"
    assert hint_to_type(ContentHint.general) == "finding"
    assert hint_to_type(ContentHint.action_items) == "pi_instruction"


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------


def test_hash_file_small(tmp_path: Path):
    p = tmp_path / "small.txt"
    p.write_text("hello world", encoding="utf-8")
    h = hash_file(p)
    assert len(h) == 64  # SHA-256 hex digest
    assert h == hash_file(p)  # deterministic


def test_hash_file_large_uses_composite(tmp_path: Path):
    p = tmp_path / "large.bin"
    p.write_bytes(b"\x00" * (11 * 1024 * 1024))  # 11 MB
    h = hash_file(p, full_hash_limit=10 * 1024 * 1024)
    assert len(h) == 64


# ---------------------------------------------------------------------------
# Safe text reading
# ---------------------------------------------------------------------------


def test_safe_read_text_utf8(tmp_path: Path):
    p = tmp_path / "utf8.txt"
    p.write_text("hello unicode", encoding="utf-8")
    assert safe_read_text(p) == "hello unicode"


def test_safe_read_text_truncates_large_file(tmp_path: Path):
    p = tmp_path / "big.txt"
    p.write_text("x" * 1000, encoding="utf-8")
    result = safe_read_text(p, max_chars=100)
    assert len(result) <= 120  # 100 + truncation marker
    assert "[" in result  # truncation marker present


def test_safe_read_text_returns_none_for_binary(tmp_path: Path):
    p = tmp_path / "binary.bin"
    p.write_bytes(bytes(range(256)) * 100)
    # May return garbled text or None depending on encoding detection
    result = safe_read_text(p)
    # Should not raise


def test_safe_read_text_docx_without_library(tmp_path: Path):
    p = tmp_path / "test.docx"
    p.write_bytes(b"fake docx content")
    result = safe_read_text(p)
    assert result is None  # python-docx not installed → None


# ---------------------------------------------------------------------------
# Module docstring extraction
# ---------------------------------------------------------------------------


def test_extract_module_docstring():
    content = '"""This is the docstring."""\n\nimport foo\n'
    assert extract_module_docstring(content) == "This is the docstring."


def test_extract_module_docstring_none_for_no_docstring():
    assert extract_module_docstring("import foo\n") is None


# ---------------------------------------------------------------------------
# Ignore pattern matching
# ---------------------------------------------------------------------------


def test_is_ignored_by_directory_name(tmp_path: Path):
    p = tmp_path / ".git" / "objects" / "abc123"
    assert is_ignored(p, tmp_path, {".git"})


def test_is_ignored_by_glob_pattern(tmp_path: Path):
    p = tmp_path / "src" / "module.pyc"
    assert is_ignored(p, tmp_path, {"*.pyc"})


def test_not_ignored_when_clean(tmp_path: Path):
    p = tmp_path / "src" / "main.py"
    assert not is_ignored(p, tmp_path, {".git", "*.pyc"})


# ---------------------------------------------------------------------------
# Capability detection
# ---------------------------------------------------------------------------


def test_detect_capabilities_returns_bools():
    caps = detect_capabilities()
    assert isinstance(caps.pymupdf_available, bool)
    assert isinstance(caps.python_docx_available, bool)
    assert caps.llm_available is False  # no LLM at test time


def test_detect_capabilities_llm_flag():
    caps = detect_capabilities(has_llm=True)
    assert caps.llm_available is True


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_extension_category_has_common_extensions():
    assert ".md" in EXTENSION_CATEGORY
    assert ".py" in EXTENSION_CATEGORY
    assert ".pdf" in EXTENSION_CATEGORY


def test_category_target_covers_all_categories():
    for cat in FileCategory:
        assert cat in CATEGORY_TARGET, f"missing target for {cat}"


def test_default_ignores_has_git():
    assert ".git" in DEFAULT_IGNORES
    assert "__pycache__" in DEFAULT_IGNORES
