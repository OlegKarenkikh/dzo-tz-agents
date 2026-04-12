"""
shared/file_storage.py
File storage for tender document collection.

Provides:
- Folder structure creation for tender participants
- Document saving to local filesystem or network share
- Async wrappers for I/O operations

Env vars:
  STORAGE_BASE_PATH — root directory for saved documents (default: ./storage)
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from shared.logger import setup_logger  # noqa: F401

logger = logging.getLogger("file_storage")

_STORAGE_BASE = os.getenv("STORAGE_BASE_PATH", "./storage")


class FileStorage:
    """Manages file storage for tender document collection.

    Supports local filesystem and network share paths (SMB/CIFS via OS mount).
    """

    def __init__(self, base_path: str | None = None):
        self.base_path = Path(base_path or _STORAGE_BASE)

    async def create_folder_structure(
        self,
        tender_id: str,
        participants: list[dict],
    ) -> dict[str, str]:
        """Create folder structure for tender participants.

        Returns:
            dict mapping participant name to created folder path.
        """
        return await asyncio.to_thread(
            self._create_folder_structure_sync,
            tender_id,
            participants,
        )

    def _create_folder_structure_sync(
        self,
        tender_id: str,
        participants: list[dict],
    ) -> dict[str, str]:
        """Synchronous folder creation."""
        result: dict[str, str] = {}
        for idx, p in enumerate(participants, start=1):
            name = p.get("name", f"Участник {idx}")
            safe_name = self._safe_filename(name)
            folder = (
                self.base_path
                / f"ТО {tender_id}"
                / "Предложения"
                / f"Участник {idx} – {safe_name}"
                / "Документы участника ТО"
            )
            folder.mkdir(parents=True, exist_ok=True)
            result[name] = str(folder)
            logger.debug("Created folder: %s", folder)
        return result

    async def save_document(
        self,
        folder_path: str,
        filename: str,
        content: bytes,
    ) -> str:
        """Save a document to the specified folder.

        Returns:
            Full path to the saved file.
        """
        return await asyncio.to_thread(
            self._save_document_sync,
            folder_path,
            filename,
            content,
        )

    def _save_document_sync(
        self,
        folder_path: str,
        filename: str,
        content: bytes,
    ) -> str:
        """Synchronous file save."""
        folder = Path(folder_path)
        folder.mkdir(parents=True, exist_ok=True)
        safe_name = self._safe_filename(filename)
        file_path = folder / safe_name
        file_path.write_bytes(content)
        logger.info("Saved document: %s (%d bytes)", file_path, len(content))
        return str(file_path)

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Sanitize a filename for filesystem safety."""
        # Replace problematic characters
        for ch in ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]:
            name = name.replace(ch, "_")
        return name.strip().strip(".")
