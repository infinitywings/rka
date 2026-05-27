"""Pure classification + file-utility functions.

No DB, no LLM, no network. Shared by the Docker-side WorkspaceService
and the host-side MCP scan tool.
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from rka.models.workspace import (
    ContentHint,
    FileCategory,
    IngestionTarget,
    ScanCapabilities,
)

logger = logging.getLogger(__name__)

# ---- Extension mappings ----

EXTENSION_CATEGORY: dict[str, FileCategory] = {
    ".md": FileCategory.markdown,
    ".markdown": FileCategory.markdown,
    ".txt": FileCategory.text,
    ".bib": FileCategory.bibtex,
    ".bibtex": FileCategory.bibtex,
    ".pdf": FileCategory.pdf,
    ".py": FileCategory.code,
    ".r": FileCategory.code,
    ".do": FileCategory.code,
    ".js": FileCategory.code,
    ".ts": FileCategory.code,
    ".jl": FileCategory.code,
    ".docx": FileCategory.document,
    ".csv": FileCategory.data,
    ".xlsx": FileCategory.data,
}

CATEGORY_TARGET: dict[FileCategory, IngestionTarget] = {
    FileCategory.markdown: IngestionTarget.ingest_document,
    FileCategory.text: IngestionTarget.ingest_document,
    FileCategory.bibtex: IngestionTarget.import_bibtex,
    FileCategory.pdf: IngestionTarget.literature_entry,
    FileCategory.code: IngestionTarget.journal_entry,
    FileCategory.document: IngestionTarget.ingest_document,
    FileCategory.data: IngestionTarget.journal_entry,
    FileCategory.unknown: IngestionTarget.skip,
}

# ---- Default ignore patterns ----

DEFAULT_IGNORES: set[str] = {
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".venv", "venv", ".env",
    ".DS_Store", "Thumbs.db", ".idea", ".vscode",
    "*.pyc", "*.pyo", "*.egg-info", "dist", "build",
}

# ---- Content hint keywords (first 500 chars) ----

MEETING_KEYWORDS = re.compile(
    r"(meeting\s+notes|minutes|attendees:|agenda:)", re.IGNORECASE,
)
ACTION_KEYWORDS = re.compile(
    r"(TODO:|Action\s+Items:|Next\s+Steps:)", re.IGNORECASE,
)
PAPER_SECTIONS = re.compile(
    r"\b(abstract|introduction|methodology|results|conclusion|references)\b", re.IGNORECASE,
)
HEADING_PATTERN = re.compile(r"^#{2,3}\s+.+$", re.MULTILINE)
CODE_FENCE = re.compile(r"^```", re.MULTILINE)
BULLET_PATTERN = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)


# ---- Pure classification functions ----


def classify_extension(ext: str) -> FileCategory:
    """Look up the FileCategory for a file extension, defaulting to ``unknown``."""
    return EXTENSION_CATEGORY.get(ext.lower(), FileCategory.unknown)


def extension_to_target(ext: str) -> IngestionTarget:
    """Map a file extension to an IngestionTarget via the category chain."""
    category = classify_extension(ext)
    return CATEGORY_TARGET.get(category, IngestionTarget.skip)


def detect_content_hint(content: str) -> ContentHint:
    """Apply regex heuristics in priority order to classify content."""
    first_500 = content[:500]

    # 1. Meeting notes
    if MEETING_KEYWORDS.search(first_500):
        return ContentHint.meeting_notes

    # 2. Paper manuscript (3+ academic section keywords)
    section_matches = set(PAPER_SECTIONS.findall(content.lower()))
    if len(section_matches) >= 3:
        return ContentHint.paper_manuscript

    # 3. Action items
    if ACTION_KEYWORDS.search(first_500):
        return ContentHint.action_items

    # 4. Brainstorm (<30 lines, >50% bullets)
    lines = content.strip().splitlines()
    if len(lines) < 30 and lines:
        bullet_count = len(BULLET_PATTERN.findall(content))
        if bullet_count > len(lines) * 0.5:
            return ContentHint.brainstorm

    # 5. Code documentation (headings + code fences)
    has_headings = bool(HEADING_PATTERN.search(content))
    has_code = bool(CODE_FENCE.search(content))
    if has_headings and has_code:
        return ContentHint.code_documentation

    # 6. Structured document (has headings)
    if has_headings:
        return ContentHint.structured_document

    # 7. General
    return ContentHint.general


def hint_to_type(hint: ContentHint) -> str:
    """Map ContentHint to a default journal entry type."""
    mapping = {
        ContentHint.meeting_notes: "summary",
        ContentHint.paper_manuscript: "finding",
        ContentHint.brainstorm: "idea",
        ContentHint.action_items: "pi_instruction",
        ContentHint.code_documentation: "methodology",
        ContentHint.structured_document: "finding",
        ContentHint.literature_review: "finding",
        ContentHint.experimental_results: "observation",
        ContentHint.general: "finding",
    }
    return mapping.get(hint, "finding")


def hash_file(path: Path, full_hash_limit: int = 10 * 1024 * 1024) -> str:
    """Compute SHA-256 hash of a file.

    For files larger than *full_hash_limit* (default 10 MB), use a fast
    composite hash: size + first 64 KB + last 64 KB.  This avoids reading
    multi-GB data files byte-by-byte while still detecting duplicates with
    high confidence.
    """
    size = path.stat().st_size
    if size <= full_hash_limit:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # Fast composite hash for large files
    CHUNK = 64 * 1024
    h = hashlib.sha256()
    h.update(f"size:{size}".encode())
    with open(path, "rb") as f:
        h.update(f.read(CHUNK))            # first 64 KB
        if size > CHUNK:
            f.seek(max(0, size - CHUNK))
            h.update(f.read(CHUNK))        # last 64 KB
    return h.hexdigest()


def safe_read_text(
    path: Path,
    capabilities: ScanCapabilities | None = None,
    max_chars: int = 200_000,
) -> str | None:
    """Safely read file as text, capped at *max_chars* characters.

    For files larger than *max_chars* the returned string is truncated
    and a trailing ``\\n[...truncated]`` marker is appended.  This prevents
    multi-hundred-MB text/CSV files from being loaded entirely into memory.
    """
    # Handle DOCX files
    if path.suffix.lower() == ".docx":
        if capabilities and capabilities.python_docx_available:
            try:
                return extract_docx_text(path)
            except Exception:
                return None
        return None

    # Standard text files — read with cap
    for encoding in ("utf-8", "latin-1"):
        try:
            size = path.stat().st_size
            if size <= max_chars:
                return path.read_text(encoding=encoding)
            # Large file: stream-read only what we need
            with open(path, encoding=encoding, errors="replace") as f:
                text = f.read(max_chars)
            return text + "\n[…truncated]"
        except (UnicodeDecodeError, PermissionError):
            continue
    return None


def extract_module_docstring(content: str) -> str | None:
    """Extract the module-level docstring from Python/code files."""
    match = re.match(
        r'^(?:\s*#[^\n]*\n)*\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')',
        content, re.DOTALL,
    )
    if match:
        return (match.group(1) or match.group(2) or "").strip()
    return None


def extract_pdf_preview(path: Path, capabilities: ScanCapabilities) -> str | None:
    """Extract text from the first page of a PDF."""
    if not capabilities.pymupdf_available:
        return None
    try:
        import pymupdf  # noqa: F811
        doc = pymupdf.open(str(path))
        if doc.page_count > 0:
            text = doc[0].get_text()
            doc.close()
            return text.strip() if text else None
        doc.close()
    except Exception as exc:
        logger.debug("PDF preview extraction failed for %s: %s", path.name, exc)
    return None


def extract_pdf_metadata_raw(path: Path) -> dict | None:
    """Extract metadata from PDF using pymupdf."""
    try:
        import pymupdf
        doc = pymupdf.open(str(path))
        meta = doc.metadata or {}
        result: dict = {}

        title = meta.get("title", "").strip()
        if title:
            result["title"] = title

        author = meta.get("author", "").strip()
        if author:
            result["authors"] = [a.strip() for a in author.split(",") if a.strip()]

        # Try extracting abstract from first page text
        if doc.page_count > 0:
            first_page = doc[0].get_text()
            abstract_match = re.search(
                r"(?:abstract|summary)\s*[:\-—]?\s*(.+?)(?=\n\s*\n|\n\s*(?:introduction|keywords|1\.))",
                first_page, re.IGNORECASE | re.DOTALL,
            )
            if abstract_match:
                result["abstract"] = abstract_match.group(1).strip()[:2000]

        doc.close()
        return result if result else None
    except Exception:
        return None


def extract_docx_text(path: Path) -> str | None:
    """Extract text from a DOCX file."""
    try:
        from docx import Document
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs) if paragraphs else None
    except Exception:
        return None


def detect_capabilities(*, has_llm: bool = False) -> ScanCapabilities:
    """Check which optional features are available."""
    pymupdf_ok = False
    try:
        import pymupdf  # noqa: F401
        pymupdf_ok = True
    except ImportError:
        pass

    docx_ok = False
    try:
        from docx import Document  # noqa: F401
        docx_ok = True
    except ImportError:
        pass

    return ScanCapabilities(
        pymupdf_available=pymupdf_ok,
        python_docx_available=docx_ok,
        llm_available=has_llm,
    )


def is_ignored(path: Path, root: Path, ignores: set[str]) -> bool:
    """Check if a file path matches any ignore pattern."""
    rel = path.relative_to(root)
    parts = rel.parts

    for part in parts:
        if part in ignores:
            return True
        # Check glob-style patterns (e.g., "*.pyc")
        for pattern in ignores:
            if pattern.startswith("*") and part.endswith(pattern[1:]):
                return True

    return False
