"""Artifact & figure extraction service."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from rka.infra.database import Database
from rka.infra.ids import generate_id
from rka.services.base import BaseService, _now

logger = logging.getLogger(__name__)


class ArtifactService(BaseService):
    """Manages file artifacts and figure extraction pipeline."""

    async def register(
        self,
        filepath: str,
        filename: str | None = None,
        filetype: str | None = None,
        mime: str | None = None,
        created_by: str = "system",
        metadata: dict | None = None,
    ) -> dict:
        """Register a file artifact in the database.

        Does not extract figures — call extract_figures() separately.
        Returns the artifact record.
        """
        created_by = self._validate_actor(created_by)
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        fname = filename or path.name
        ftype = filetype or path.suffix.lstrip(".")
        file_size = path.stat().st_size

        # Compute content hash for dedup
        content_hash = self._hash_file(path)

        # Check for duplicate
        existing = await self.db.fetchone(
            "SELECT id FROM artifacts WHERE content_hash = ? AND project_id = ?",
            [content_hash, self.project_id],
        )
        if existing:
            return {"id": existing["id"], "duplicate": True}

        artifact_id = generate_id("artifact")
        await self.db.execute(
            """INSERT INTO artifacts
               (id, filename, filepath, filetype, file_size, mime, content_hash,
                extraction_status, created_by, metadata, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
            [artifact_id, fname, str(path.resolve()), ftype, file_size, mime,
             content_hash, created_by, json.dumps(metadata) if metadata else None, self.project_id],
        )
        await self.db.commit()
        await self.audit("create", "artifact", artifact_id, created_by)

        return {"id": artifact_id, "duplicate": False}

    async def get(self, artifact_id: str) -> dict | None:
        """Get an artifact by ID."""
        row = await self.db.fetchone(
            "SELECT * FROM artifacts WHERE id = ? AND project_id = ?",
            [artifact_id, self.project_id],
        )
        return dict(row) if row else None

    async def list_artifacts(
        self,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """List artifacts with optional status filter."""
        if status:
            rows = await self.db.fetchall(
                "SELECT * FROM artifacts WHERE project_id = ? AND extraction_status = ? ORDER BY created_at DESC LIMIT ?",
                [self.project_id, status, limit],
            )
        else:
            rows = await self.db.fetchall(
                "SELECT * FROM artifacts WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                [self.project_id, limit],
            )
        return [dict(r) for r in rows]

    async def extract_figures(self, artifact_id: str) -> list[dict]:
        """Extract figures/tables from an artifact using the LLM.

        For PDFs: extracts text per page and sends to LLM for figure extraction.
        For images: sends the image context to LLM directly.
        Returns list of created figure records.
        """
        artifact = await self.get(artifact_id)
        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        # Mark as processing
        await self.db.execute(
            "UPDATE artifacts SET extraction_status = 'processing' WHERE id = ? AND project_id = ?",
            [artifact_id, self.project_id],
        )
        await self.db.commit()

        figures: list[dict] = []
        try:
            ftype = artifact.get("filetype", "").lower()
            filepath = artifact["filepath"]

            if ftype == "pdf":
                figures = await self._extract_from_pdf(artifact_id, filepath)
            elif ftype in ("png", "jpg", "jpeg", "gif", "webp", "svg"):
                figures = await self._extract_from_image(artifact_id, filepath)
            else:
                logger.info("No figure extraction for filetype: %s", ftype)

            # Mark as complete
            await self.db.execute(
                "UPDATE artifacts SET extraction_status = 'complete' WHERE id = ? AND project_id = ?",
                [artifact_id, self.project_id],
            )
            await self.db.commit()

        except Exception as exc:
            logger.error("Figure extraction failed for %s: %s", artifact_id, exc)
            await self.db.execute(
                "UPDATE artifacts SET extraction_status = 'failed' WHERE id = ? AND project_id = ?",
                [artifact_id, self.project_id],
            )
            await self.db.commit()

        return figures

    async def get_figures(self, artifact_id: str) -> list[dict]:
        """Get all figures for an artifact."""
        rows = await self.db.fetchall(
            "SELECT * FROM figures WHERE artifact_id = ? AND project_id = ? ORDER BY page",
            [artifact_id, self.project_id],
        )
        return [dict(r) for r in rows]

    async def get_figure(self, figure_id: str) -> dict | None:
        """Get a single figure by ID."""
        row = await self.db.fetchone(
            "SELECT * FROM figures WHERE id = ? AND project_id = ?",
            [figure_id, self.project_id],
        )
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Internal extraction methods
    # ------------------------------------------------------------------

    async def _extract_from_pdf(self, artifact_id: str, filepath: str) -> list[dict]:
        """Extract figures from a PDF using pymupdf + LLM."""
        figures = []
        try:
            import pymupdf
        except ImportError:
            logger.warning("pymupdf not installed — skipping PDF figure extraction")
            return figures

        doc = pymupdf.open(filepath)
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            if not text.strip():
                continue

            # Use LLM to extract figure data from page text
            if self.llm:
                result = await self.llm.extract_figure(
                    context_text=text,
                    page=page_num + 1,
                    artifact_id=artifact_id,
                )
                if result and (result.summary or result.claims):
                    fig = await self._store_figure(
                        artifact_id=artifact_id,
                        page=page_num + 1,
                        caption=result.caption,
                        caption_confidence=result.caption_confidence,
                        summary=result.summary,
                        claims=[c.model_dump() for c in result.claims],
                    )
                    figures.append(fig)

                # Also check for tables
                table_result = await self.llm.extract_table(
                    table_text=text[:3000],
                    context_text=f"Page {page_num + 1} of {filepath}",
                )
                if table_result and table_result.rows:
                    fig = await self._store_figure(
                        artifact_id=artifact_id,
                        page=page_num + 1,
                        caption=table_result.title,
                        caption_confidence=0.8,
                        summary=table_result.summary,
                        claims=[c.model_dump() for c in table_result.claims],
                    )
                    figures.append(fig)

        doc.close()
        return figures

    async def _extract_from_image(self, artifact_id: str, filepath: str) -> list[dict]:
        """Extract figure data from an image file."""
        from rka.infra.llm import LLMUnavailableError
        figures = []
        if not self.llm:
            raise LLMUnavailableError("ArtifactService figure extraction requires a configured LLM.")

        # Read basic info
        path = Path(filepath)
        context = f"Image file: {path.name} ({path.stat().st_size} bytes)"

        result = await self.llm.extract_figure(
            context_text=context,
            artifact_id=artifact_id,
        )
        if result:
            fig = await self._store_figure(
                artifact_id=artifact_id,
                page=None,
                caption=result.caption,
                caption_confidence=result.caption_confidence,
                summary=result.summary,
                claims=[c.model_dump() for c in result.claims],
            )
            figures.append(fig)

        return figures

    async def _store_figure(
        self,
        artifact_id: str,
        page: int | None,
        caption: str | None,
        caption_confidence: float,
        summary: str,
        claims: list[dict],
    ) -> dict:
        """Store a figure record in the database."""
        figure_id = generate_id("figure")
        await self.db.execute(
            """INSERT INTO figures
               (id, artifact_id, page, caption, caption_confidence, summary, claims, project_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [figure_id, artifact_id, page, caption, caption_confidence,
             summary, json.dumps(claims), self.project_id],
        )
        await self.db.commit()

        # Create entity_link from artifact to figure
        await self.add_link("artifact", artifact_id, "produced", "figure", figure_id, created_by="system")

        return {
            "id": figure_id,
            "artifact_id": artifact_id,
            "page": page,
            "caption": caption,
            "summary": summary,
            "claims_count": len(claims),
        }

    @staticmethod
    def _hash_file(path: Path, chunk_size: int = 65536) -> str:
        """Compute SHA-256 hash of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
