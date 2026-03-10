"""Workspace bootstrap service — scan, classify, ingest research files."""

from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from rka.infra.ids import generate_id
from rka.models.workspace import (
    BootstrapReview,
    ContentHint,
    FileCategory,
    IngestResult,
    IngestionTarget,
    ReviewSuggestion,
    ScanCapabilities,
    ScanManifest,
    ScanSummary,
    ScannedFile,
    WorkspaceIngestRequest,
    WorkspaceIngestResponse,
)

if TYPE_CHECKING:
    from rka.infra.database import Database
    from rka.infra.llm import LLMClient
    from rka.services.academic import AcademicImportService
    from rka.services.literature import LiteratureService
    from rka.services.notes import NoteService

logger = logging.getLogger(__name__)

# ---- Extension mappings ----

_EXTENSION_CATEGORY: dict[str, FileCategory] = {
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

_CATEGORY_TARGET: dict[FileCategory, IngestionTarget] = {
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

_DEFAULT_IGNORES = {
    ".git", ".svn", ".hg",
    "node_modules", "__pycache__", ".venv", "venv", ".env",
    ".DS_Store", "Thumbs.db", ".idea", ".vscode",
    "*.pyc", "*.pyo", "*.egg-info", "dist", "build",
}

# ---- Content hint keywords (first 500 chars) ----

_MEETING_KEYWORDS = re.compile(
    r"(meeting\s+notes|minutes|attendees:|agenda:)", re.IGNORECASE,
)
_ACTION_KEYWORDS = re.compile(
    r"(TODO:|Action\s+Items:|Next\s+Steps:)", re.IGNORECASE,
)
_PAPER_SECTIONS = re.compile(
    r"\b(abstract|introduction|methodology|results|conclusion|references)\b", re.IGNORECASE,
)
_HEADING_PATTERN = re.compile(r"^#{2,3}\s+.+$", re.MULTILINE)
_CODE_FENCE = re.compile(r"^```", re.MULTILINE)
_BULLET_PATTERN = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)


class WorkspaceService:
    """Scan, classify, and ingest a workspace folder into the knowledge base.

    Designed for the RKA → Brain → Executor workflow:
    1. RKA (this service) does fast scan + ingest with regex + optional LLM classification
    2. Brain reviews the bootstrap via review() and reorganizes
    3. Executor is delegated deep analysis tasks
    """

    def __init__(
        self,
        db: "Database",
        academic_service: "AcademicImportService",
        note_service: "NoteService",
        literature_service: "LiteratureService",
        llm: "LLMClient | None" = None,
    ):
        self.db = db
        self.academic = academic_service
        self.notes = note_service
        self.lit = literature_service
        self.llm = llm

    # ================================================================
    # Public: Scan
    # ================================================================

    async def scan(
        self,
        folder_path: str,
        ignore_patterns: list[str] | None = None,
        include_preview: bool = True,
        max_file_size_mb: float = 50.0,
        use_llm: bool = True,
    ) -> ScanManifest:
        """Scan a folder and classify files for ingestion.

        Returns a ScanManifest (ephemeral, not stored in DB).
        """
        root = Path(folder_path).resolve()
        if not root.is_dir():
            raise ValueError(f"Not a directory: {folder_path}")

        scan_id = generate_id("scan")
        capabilities = self._detect_capabilities(use_llm)
        ignores = _DEFAULT_IGNORES | set(ignore_patterns or [])
        max_bytes = int(max_file_size_mb * 1024 * 1024)

        files: list[ScannedFile] = []
        warnings: list[str] = []
        total_found = 0

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            total_found += 1

            if self._should_ignore(path, root, ignores):
                continue

            if path.stat().st_size > max_bytes:
                warnings.append(f"Skipped (too large): {path.relative_to(root)}")
                continue

            try:
                scanned = await self._classify_file(
                    path, root, include_preview, capabilities,
                )
                files.append(scanned)
            except Exception as exc:
                warnings.append(f"Error scanning {path.relative_to(root)}: {exc}")

        # Check duplicates
        await self._check_duplicates(files)

        # Build summary
        summary = self._build_summary(files)

        return ScanManifest(
            scan_id=scan_id,
            root_path=str(root),
            total_files_found=total_found,
            total_files_scanned=len(files),
            files=files,
            summary=summary,
            warnings=warnings,
            capabilities=capabilities,
        )

    # ================================================================
    # Public: Ingest
    # ================================================================

    async def ingest(
        self, request: WorkspaceIngestRequest,
    ) -> WorkspaceIngestResponse:
        """Ingest files from a scan manifest into the knowledge base."""
        manifest = request.manifest
        skip_set = set(request.skip_files)
        results: list[IngestResult] = []
        total_created = 0
        total_skipped = 0
        total_errors = 0

        for scanned in manifest.files:
            # Skip duplicates and explicitly skipped files
            if scanned.relative_path in skip_set:
                total_skipped += 1
                continue
            if scanned.is_duplicate:
                total_skipped += 1
                results.append(IngestResult(
                    relative_path=scanned.relative_path,
                    category=scanned.category.value,
                    ingestion_target=scanned.ingestion_target.value,
                    success=True,
                    error="Duplicate — already ingested",
                ))
                continue
            if scanned.ingestion_target == IngestionTarget.skip:
                total_skipped += 1
                continue

            if request.dry_run:
                results.append(IngestResult(
                    relative_path=scanned.relative_path,
                    category=scanned.category.value,
                    ingestion_target=scanned.ingestion_target.value,
                    success=True,
                    entity_count=1,
                ))
                total_created += 1
                continue

            result = await self._ingest_single_file(
                scanned=scanned,
                root_path=manifest.root_path,
                phase=request.phase,
                override_tags=request.override_tags,
                source=request.source,
                scan_id=manifest.scan_id,
            )
            results.append(result)
            if result.success:
                total_created += result.entity_count
            else:
                total_errors += 1

        return WorkspaceIngestResponse(
            scan_id=manifest.scan_id,
            total_processed=len(results),
            total_created=total_created,
            total_skipped=total_skipped,
            total_errors=total_errors,
            results=results,
        )

    # ================================================================
    # Public: Review (for Brain handoff)
    # ================================================================

    async def review(self, scan_id: str) -> BootstrapReview:
        """Produce a bootstrap review for the Brain to start reorganization."""
        # Query bootstrap_log for all entities from this scan
        rows = await self.db.fetchall(
            "SELECT entity_type, entity_id, category FROM bootstrap_log WHERE scan_id = ?",
            [scan_id],
        )
        if not rows:
            return BootstrapReview(
                scan_id=scan_id,
                total_entries_created=0,
                suggestions=[ReviewSuggestion(
                    priority="high",
                    action="No entries found for this scan ID",
                    details="Run rka_bootstrap_workspace first to ingest files.",
                )],
            )

        entity_ids = [r["entity_id"] for r in rows]
        type_counter: Counter = Counter()
        cat_counter: Counter = Counter()
        all_tags_counter: Counter = Counter()
        needs_attention: list[str] = []

        for row in rows:
            cat_counter[row["category"]] += 1

        # Count by entry type + gather tags
        for eid in entity_ids:
            # Check journal entries
            jrow = await self.db.fetchone(
                "SELECT type FROM journal WHERE id = ?", [eid],
            )
            if jrow:
                type_counter[jrow["type"]] += 1

            # Check literature entries
            lrow = await self.db.fetchone(
                "SELECT abstract FROM literature WHERE id = ?", [eid],
            )
            if lrow is not None and not lrow["abstract"]:
                needs_attention.append(eid)

            # Gather tags
            tag_rows = await self.db.fetchall(
                "SELECT tag FROM tags WHERE entity_id = ?", [eid],
            )
            for tr in tag_rows:
                all_tags_counter[tr["tag"]] += 1

        all_tags = sorted(all_tags_counter.keys())
        singleton_tags = [t for t, c in all_tags_counter.items() if c == 1]

        # Build suggestions
        suggestions: list[ReviewSuggestion] = []

        if needs_attention:
            suggestions.append(ReviewSuggestion(
                priority="high",
                action=f"Enrich {len(needs_attention)} literature entries missing abstracts",
                details=(
                    f"IDs: {', '.join(needs_attention[:10])}"
                    f"{' (and more)' if len(needs_attention) > 10 else ''}"
                    f" — consider having Executor read these PDFs and summarize."
                ),
            ))

        if singleton_tags:
            suggestions.append(ReviewSuggestion(
                priority="medium",
                action=f"Review {len(singleton_tags)} singleton tags for consolidation",
                details=(
                    f"Tags used only once: {', '.join(singleton_tags[:15])}"
                    f" — merge similar tags or add them to related entries."
                ),
            ))

        if len(entity_ids) > 5:
            suggestions.append(ReviewSuggestion(
                priority="medium",
                action="Create cross-references between related entries",
                details="Scan for entries that share tags or topics and link them via related_decisions/related_literature.",
            ))

        suggestions.append(ReviewSuggestion(
            priority="low",
            action="Create decisions from recurring themes",
            details="Review entries for common themes that warrant formal decision records.",
        ))

        # Optional LLM narrative
        narrative: str | None = None
        if self.llm:
            try:
                # Build a concise summary of what was ingested
                summary_parts = [
                    f"Bootstrap ingested {len(entity_ids)} entries from scan {scan_id}.",
                    f"Types: {dict(type_counter)}",
                    f"Categories: {dict(cat_counter)}",
                    f"Tags ({len(all_tags)}): {', '.join(all_tags[:20])}",
                ]
                if needs_attention:
                    summary_parts.append(
                        f"{len(needs_attention)} entries need attention (missing abstracts)."
                    )
                from rka.infra.llm import NarrativeSummary
                result = await self.llm.extract(
                    NarrativeSummary,
                    messages=[{
                        "role": "user",
                        "content": (
                            "Produce a brief narrative overview of this research knowledge base bootstrap. "
                            "Highlight themes, gaps, and priorities for reorganization.\n\n"
                            + "\n".join(summary_parts)
                        ),
                    }],
                )
                if result:
                    narrative = result.narrative
            except Exception as exc:
                logger.debug("Review narrative generation failed: %s", exc)

        return BootstrapReview(
            scan_id=scan_id,
            total_entries_created=len(entity_ids),
            entries_by_type=dict(type_counter),
            entries_by_category=dict(cat_counter),
            all_tags=all_tags,
            singleton_tags=singleton_tags,
            needs_attention=needs_attention,
            suggestions=suggestions,
            narrative=narrative,
        )

    # ================================================================
    # Private: Classification
    # ================================================================

    async def _classify_file(
        self,
        path: Path,
        root: Path,
        include_preview: bool,
        capabilities: ScanCapabilities,
    ) -> ScannedFile:
        """Classify a single file."""
        ext = path.suffix.lower()
        category = _EXTENSION_CATEGORY.get(ext, FileCategory.unknown)
        target = _CATEGORY_TARGET.get(category, IngestionTarget.skip)
        file_hash = self._hash_file(path)
        size_bytes = path.stat().st_size

        content_hint = ContentHint.general
        preview: str | None = None
        proposed_type = "finding"
        proposed_tags: list[str] = []
        llm_classified = False
        title_suggestion: str | None = None

        # Text-readable files: extract preview and apply heuristics
        if category in (FileCategory.markdown, FileCategory.text, FileCategory.document):
            content = self._safe_read_text(path, capabilities)
            if content:
                preview = content[:500] if include_preview else None
                content_hint = self._detect_content_hint(content)
                proposed_type = self._hint_to_type(content_hint)

                # For text files without headings, use single journal entry
                if category == FileCategory.text and not _HEADING_PATTERN.search(content):
                    target = IngestionTarget.journal_entry

                # LLM-enhanced classification
                if capabilities.llm_available and self.llm:
                    try:
                        classification = await self.llm.classify_file(
                            path.name, content[:2000], ext,
                        )
                        if classification and classification.confidence > 0.7:
                            content_hint = ContentHint(classification.content_type)
                            proposed_type = classification.journal_type
                            proposed_tags = [t.lower() for t in classification.tags]
                            title_suggestion = classification.title_suggestion
                            llm_classified = True
                    except Exception as exc:
                        logger.debug("LLM classification failed for %s: %s", path.name, exc)

        elif category == FileCategory.code:
            content = self._safe_read_text(path)
            if content:
                docstring = self._extract_module_docstring(content)
                first_lines = "\n".join(content.splitlines()[:50])
                preview_text = f"{docstring}\n\n{first_lines}" if docstring else first_lines
                preview = preview_text[:500] if include_preview else None
                proposed_type = "methodology"
                content_hint = ContentHint.code_documentation

        elif category == FileCategory.pdf:
            pdf_preview = self._extract_pdf_preview(path, capabilities)
            if pdf_preview:
                preview = pdf_preview[:500] if include_preview else None
                title_suggestion = pdf_preview.split("\n")[0][:200]  # first line as title

                # LLM-enhanced PDF metadata
                if capabilities.llm_available and self.llm and pdf_preview:
                    try:
                        meta = await self.llm.extract_pdf_metadata(pdf_preview[:3000])
                        if meta:
                            title_suggestion = meta.title
                            llm_classified = True
                    except Exception as exc:
                        logger.debug("LLM PDF metadata failed for %s: %s", path.name, exc)

        elif category == FileCategory.data:
            proposed_type = "observation"
            preview = f"Data file: {path.name} ({size_bytes:,} bytes)" if include_preview else None

        return ScannedFile(
            path=str(path),
            relative_path=str(path.relative_to(root)),
            filename=path.name,
            extension=ext,
            size_bytes=size_bytes,
            category=category,
            content_hint=content_hint,
            ingestion_target=target,
            proposed_type=proposed_type,
            proposed_tags=proposed_tags,
            file_hash=file_hash,
            preview=preview,
            llm_classified=llm_classified,
            title_suggestion=title_suggestion,
        )

    @staticmethod
    def _detect_content_hint(content: str) -> ContentHint:
        """Apply regex heuristics in priority order to classify content."""
        first_500 = content[:500]

        # 1. Meeting notes
        if _MEETING_KEYWORDS.search(first_500):
            return ContentHint.meeting_notes

        # 2. Paper manuscript (3+ academic section keywords)
        section_matches = set(_PAPER_SECTIONS.findall(content.lower()))
        if len(section_matches) >= 3:
            return ContentHint.paper_manuscript

        # 3. Action items
        if _ACTION_KEYWORDS.search(first_500):
            return ContentHint.action_items

        # 4. Brainstorm (<30 lines, >50% bullets)
        lines = content.strip().splitlines()
        if len(lines) < 30 and lines:
            bullet_count = len(_BULLET_PATTERN.findall(content))
            if bullet_count > len(lines) * 0.5:
                return ContentHint.brainstorm

        # 5. Code documentation (headings + code fences)
        has_headings = bool(_HEADING_PATTERN.search(content))
        has_code = bool(_CODE_FENCE.search(content))
        if has_headings and has_code:
            return ContentHint.code_documentation

        # 6. Structured document (has headings)
        if has_headings:
            return ContentHint.structured_document

        # 7. General
        return ContentHint.general

    @staticmethod
    def _hint_to_type(hint: ContentHint) -> str:
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

    # ================================================================
    # Private: Ingestion
    # ================================================================

    async def _ingest_single_file(
        self,
        scanned: ScannedFile,
        root_path: str,
        phase: str | None,
        override_tags: list[str],
        source: str,
        scan_id: str,
    ) -> IngestResult:
        """Ingest a single file into the knowledge base."""
        full_path = Path(root_path) / scanned.relative_path
        tags = list(set(scanned.proposed_tags + override_tags))

        try:
            if scanned.ingestion_target == IngestionTarget.ingest_document:
                return await self._ingest_as_document(
                    full_path, scanned, phase, tags, source, scan_id,
                )
            elif scanned.ingestion_target == IngestionTarget.import_bibtex:
                return await self._ingest_as_bibtex(
                    full_path, scanned, scan_id,
                )
            elif scanned.ingestion_target == IngestionTarget.journal_entry:
                return await self._ingest_as_journal(
                    full_path, scanned, phase, tags, source, scan_id,
                )
            elif scanned.ingestion_target == IngestionTarget.literature_entry:
                return await self._ingest_as_literature(
                    full_path, scanned, tags, scan_id,
                )
            else:
                return IngestResult(
                    relative_path=scanned.relative_path,
                    category=scanned.category.value,
                    ingestion_target=scanned.ingestion_target.value,
                    success=False,
                    error=f"Unsupported ingestion target: {scanned.ingestion_target}",
                )
        except Exception as exc:
            return IngestResult(
                relative_path=scanned.relative_path,
                category=scanned.category.value,
                ingestion_target=scanned.ingestion_target.value,
                success=False,
                error=str(exc),
            )

    async def _ingest_as_document(
        self, path: Path, scanned: ScannedFile,
        phase: str | None, tags: list[str], source: str, scan_id: str,
    ) -> IngestResult:
        """Ingest a text-based file via academic.ingest_document()."""
        capabilities = self._detect_capabilities(False)
        content = self._safe_read_text(path, capabilities)
        if not content:
            return IngestResult(
                relative_path=scanned.relative_path,
                category=scanned.category.value,
                ingestion_target=scanned.ingestion_target.value,
                success=False,
                error="Could not read file content",
            )

        result = await self.academic.ingest_document(
            content=content,
            source=source,
            default_type=scanned.proposed_type,
            phase=phase,
            tags=tags,
        )

        entity_ids = [e["id"] for e in result.get("created", [])]

        # Log to bootstrap_log
        for eid in entity_ids:
            await self._log_bootstrap(
                scan_id, scanned.file_hash, scanned.relative_path,
                scanned.category.value, "journal", eid,
            )

        return IngestResult(
            relative_path=scanned.relative_path,
            category=scanned.category.value,
            ingestion_target=scanned.ingestion_target.value,
            success=True,
            entity_ids=entity_ids,
            entity_count=len(entity_ids),
        )

    async def _ingest_as_bibtex(
        self, path: Path, scanned: ScannedFile, scan_id: str,
    ) -> IngestResult:
        """Ingest a BibTeX file via academic.import_bibtex()."""
        content = self._safe_read_text(path)
        if not content:
            return IngestResult(
                relative_path=scanned.relative_path,
                category=scanned.category.value,
                ingestion_target=scanned.ingestion_target.value,
                success=False,
                error="Could not read BibTeX file",
            )

        result = await self.academic.import_bibtex(
            bibtex_content=content,
            added_by="import",
        )

        entity_ids = [e["id"] for e in result.get("imported", [])]

        for eid in entity_ids:
            await self._log_bootstrap(
                scan_id, scanned.file_hash, scanned.relative_path,
                scanned.category.value, "literature", eid,
            )

        return IngestResult(
            relative_path=scanned.relative_path,
            category=scanned.category.value,
            ingestion_target=scanned.ingestion_target.value,
            success=True,
            entity_ids=entity_ids,
            entity_count=len(entity_ids),
        )

    async def _ingest_as_journal(
        self, path: Path, scanned: ScannedFile,
        phase: str | None, tags: list[str], source: str, scan_id: str,
    ) -> IngestResult:
        """Ingest a single file as one journal entry."""
        from rka.models.journal import JournalEntryCreate

        if scanned.category == FileCategory.code:
            content = self._safe_read_text(path)
            if not content:
                return IngestResult(
                    relative_path=scanned.relative_path,
                    category=scanned.category.value,
                    ingestion_target=scanned.ingestion_target.value,
                    success=False,
                    error="Could not read code file",
                )
            docstring = self._extract_module_docstring(content)
            first_lines = "\n".join(content.splitlines()[:50])
            entry_content = (
                f"**Code: {scanned.filename}**\n\n"
                f"{f'Docstring: {docstring}' + chr(10) + chr(10) if docstring else ''}"
                f"```{scanned.extension.lstrip('.')}\n{first_lines}\n```"
            )
        elif scanned.category == FileCategory.data:
            entry_content = (
                f"**Data file: {scanned.filename}**\n\n"
                f"Size: {scanned.size_bytes:,} bytes\n"
                f"Format: {scanned.extension}"
            )
        else:
            content = self._safe_read_text(path)
            entry_content = content or f"File: {scanned.filename}"

        data = JournalEntryCreate(
            content=entry_content,
            type=scanned.proposed_type,
            source=source,
            phase=phase,
            tags=tags,
        )
        entry = await self.notes.create(data, actor=source)

        await self._log_bootstrap(
            scan_id, scanned.file_hash, scanned.relative_path,
            scanned.category.value, "journal", entry.id,
        )

        return IngestResult(
            relative_path=scanned.relative_path,
            category=scanned.category.value,
            ingestion_target=scanned.ingestion_target.value,
            success=True,
            entity_ids=[entry.id],
            entity_count=1,
        )

    async def _ingest_as_literature(
        self, path: Path, scanned: ScannedFile,
        tags: list[str], scan_id: str,
    ) -> IngestResult:
        """Ingest a PDF as a literature entry."""
        from rka.models.literature import LiteratureCreate

        # Try to extract title from the scan's title_suggestion or filename
        title = scanned.title_suggestion or path.stem.replace("-", " ").replace("_", " ")

        # Try extracting metadata from PDF
        capabilities = self._detect_capabilities(False)
        abstract: str | None = None
        authors: list[str] | None = None
        year: int | None = None

        if capabilities.pymupdf_available:
            meta = self._extract_pdf_metadata_raw(path)
            if meta:
                if meta.get("title"):
                    title = meta["title"]
                abstract = meta.get("abstract")
                authors = meta.get("authors")
                year = meta.get("year")

        data = LiteratureCreate(
            title=title,
            authors=authors,
            year=year,
            abstract=abstract,
            pdf_path=str(path),
            status="to_read",
            added_by="import",
            tags=tags,
        )
        lit = await self.lit.create(data, actor="import")

        await self._log_bootstrap(
            scan_id, scanned.file_hash, scanned.relative_path,
            scanned.category.value, "literature", lit.id,
        )

        return IngestResult(
            relative_path=scanned.relative_path,
            category=scanned.category.value,
            ingestion_target=scanned.ingestion_target.value,
            success=True,
            entity_ids=[lit.id],
            entity_count=1,
        )

    # ================================================================
    # Private: Helpers
    # ================================================================

    async def _log_bootstrap(
        self, scan_id: str, file_hash: str, file_path: str,
        category: str, entity_type: str, entity_id: str,
    ) -> None:
        """Record a successful ingestion in the bootstrap_log table."""
        await self.db.execute(
            """INSERT INTO bootstrap_log
               (scan_id, file_hash, file_path, category, entity_type, entity_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [scan_id, file_hash, file_path, category, entity_type, entity_id],
        )
        await self.db.commit()

    async def _check_duplicates(self, files: list[ScannedFile]) -> None:
        """Mark files that have already been ingested (by hash)."""
        for f in files:
            row = await self.db.fetchone(
                "SELECT 1 FROM bootstrap_log WHERE file_hash = ?", [f.file_hash],
            )
            if row:
                f.is_duplicate = True

    @staticmethod
    def _build_summary(files: list[ScannedFile]) -> ScanSummary:
        """Build summary statistics from scanned files."""
        cat_counter: Counter = Counter()
        target_counter: Counter = Counter()
        hint_counter: Counter = Counter()
        total_size = 0
        dup_count = 0
        llm_count = 0

        for f in files:
            cat_counter[f.category.value] += 1
            target_counter[f.ingestion_target.value] += 1
            hint_counter[f.content_hint.value] += 1
            total_size += f.size_bytes
            if f.is_duplicate:
                dup_count += 1
            if f.llm_classified:
                llm_count += 1

        return ScanSummary(
            by_category=dict(cat_counter),
            by_target=dict(target_counter),
            by_content_hint=dict(hint_counter),
            total_size_bytes=total_size,
            duplicate_count=dup_count,
            llm_classified_count=llm_count,
        )

    @staticmethod
    def _should_ignore(path: Path, root: Path, ignores: set[str]) -> bool:
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

    @staticmethod
    def _hash_file(path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _safe_read_text(
        path: Path,
        capabilities: ScanCapabilities | None = None,
    ) -> str | None:
        """Safely read file as text. Returns None on failure."""
        # Handle DOCX files
        if path.suffix.lower() == ".docx":
            if capabilities and capabilities.python_docx_available:
                try:
                    return WorkspaceService._extract_docx_text(path)
                except Exception:
                    return None
            return None

        # Standard text files
        for encoding in ("utf-8", "latin-1"):
            try:
                return path.read_text(encoding=encoding)
            except (UnicodeDecodeError, PermissionError):
                continue
        return None

    @staticmethod
    def _extract_module_docstring(content: str) -> str | None:
        """Extract the module-level docstring from Python/code files."""
        # Match triple-quoted strings at the start of the file
        match = re.match(
            r'^(?:\s*#[^\n]*\n)*\s*(?:"""(.*?)"""|\'\'\'(.*?)\'\'\')',
            content, re.DOTALL,
        )
        if match:
            return (match.group(1) or match.group(2) or "").strip()
        return None

    @staticmethod
    def _extract_pdf_preview(path: Path, capabilities: ScanCapabilities) -> str | None:
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

    @staticmethod
    def _extract_pdf_metadata_raw(path: Path) -> dict | None:
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

    @staticmethod
    def _extract_docx_text(path: Path) -> str | None:
        """Extract text from a DOCX file."""
        try:
            from docx import Document
            doc = Document(str(path))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs) if paragraphs else None
        except Exception:
            return None

    def _detect_capabilities(self, use_llm: bool = True) -> ScanCapabilities:
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

        llm_ok = use_llm and self.llm is not None

        return ScanCapabilities(
            pymupdf_available=pymupdf_ok,
            python_docx_available=docx_ok,
            llm_available=llm_ok,
        )
