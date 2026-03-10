"""File storage for PDFs and attachments (Phase 2+)."""

from __future__ import annotations

from pathlib import Path


class FileStorage:
    """Manages local file storage for research artifacts."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.pdfs_dir = base_dir / "pdfs"
        self.attachments_dir = base_dir / "attachments"

    def ensure_dirs(self) -> None:
        """Create storage directories if they don't exist."""
        self.pdfs_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)

    def get_pdf_path(self, filename: str) -> Path:
        return self.pdfs_dir / filename

    def get_attachment_path(self, filename: str) -> Path:
        return self.attachments_dir / filename
