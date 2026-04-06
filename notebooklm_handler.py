"""
NotebookLM integration using the notebooklm-py community SDK.

This module handles:
- Authentication with your Google account (used by NotebookLM)
- Listing available notebooks
- Exporting notebook content (notes, sources, summaries)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class NotebookData:
    """Lightweight container for data exported from a single notebook."""

    def __init__(
        self,
        notebook_id: str,
        title: str,
        sources: list[dict[str, Any]],
        notes: list[dict[str, Any]],
    ) -> None:
        self.notebook_id = notebook_id
        self.title = title
        self.sources = sources  # list of {"title": ..., "content": ...}
        self.notes = notes      # list of {"title": ..., "content": ...}

    def to_text(self) -> str:
        """Return a single text blob suitable for sending to Claude."""
        parts: list[str] = [f"Notebook: {self.title}\n"]

        if self.sources:
            parts.append("=== Sources ===")
            for src in self.sources:
                parts.append(f"[{src.get('title', 'Untitled')}]\n{src.get('content', '')}")

        if self.notes:
            parts.append("=== Notes ===")
            for note in self.notes:
                parts.append(f"[{note.get('title', 'Note')}]\n{note.get('content', '')}")

        return "\n\n".join(parts)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<NotebookData id={self.notebook_id!r} title={self.title!r}>"


class NotebookLMHandler:
    """
    Wraps the notebooklm-py SDK.

    The notebooklm-py package (``pip install notebooklm``) is an *unofficial*
    community library that drives the NotebookLM web interface.  Because it
    relies on browser-level Google authentication, first-time use may require
    interactive sign-in steps.

    If the package is not installed, or if authentication fails, this handler
    falls back gracefully so the rest of the workflow can still be exercised
    with manually-provided notebook content.
    """

    def __init__(self, email: str = "", password: str = "") -> None:
        self.email = email
        # Keep the password only as a local reference; it is passed directly
        # to the SDK and then discarded – not stored as a persistent attribute.
        self._password = password
        self._client: Any = None
        self._available = False
        self._notebooks_cache: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # SDK initialisation
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        Try to authenticate with NotebookLM.

        Returns True on success, False if the SDK is unavailable or
        authentication fails.
        """
        try:
            import notebooklm  # type: ignore[import]
        except ImportError:
            logger.warning(
                "notebooklm package not found. "
                "Install it with: pip install notebooklm\n"
                "Continuing in manual-input mode."
            )
            return False

        try:
            self._client = notebooklm.NotebookLM(
                email=self.email,
                password=self._password,
            )
            # Clear password from memory after authentication
            self._password = ""
            self._available = True
            logger.info("Connected to NotebookLM successfully.")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("NotebookLM authentication failed: %s", exc)
            logger.warning("Continuing in manual-input mode.")
            return False

    # ------------------------------------------------------------------
    # Notebook discovery
    # ------------------------------------------------------------------

    def list_notebooks(self) -> list[dict[str, Any]]:
        """
        Return a list of notebooks, each as::

            {"id": "...", "title": "..."}

        Returns an empty list when the SDK is unavailable.
        """
        if not self._available or self._client is None:
            return []

        try:
            raw = self._client.get_notebooks()
            notebooks = []
            for item in raw:
                notebooks.append(
                    {
                        "id": getattr(item, "id", str(item)),
                        "title": getattr(item, "title", "Untitled"),
                    }
                )
            self._notebooks_cache = notebooks
            return notebooks
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to list notebooks: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Notebook export
    # ------------------------------------------------------------------

    def get_notebook_data(self, notebook_id: str) -> NotebookData | None:
        """
        Export content from the notebook identified by *notebook_id*.

        Returns a :class:`NotebookData` instance, or ``None`` on failure.
        """
        if not self._available or self._client is None:
            logger.warning(
                "NotebookLM SDK not connected. Cannot fetch notebook %r.",
                notebook_id,
            )
            return None

        try:
            nb = self._client.get_notebook(notebook_id)
            title = getattr(nb, "title", "Untitled Notebook")

            # Extract sources -----------------------------------------------
            sources: list[dict[str, Any]] = []
            raw_sources = getattr(nb, "sources", []) or []
            for src in raw_sources:
                sources.append(
                    {
                        "title": getattr(src, "title", "Source"),
                        "content": getattr(src, "content", ""),
                    }
                )

            # Extract notes / summary ---------------------------------------
            notes: list[dict[str, Any]] = []
            raw_notes = getattr(nb, "notes", []) or []
            for note in raw_notes:
                notes.append(
                    {
                        "title": getattr(note, "title", "Note"),
                        "content": getattr(note, "content", ""),
                    }
                )

            return NotebookData(
                notebook_id=notebook_id,
                title=title,
                sources=sources,
                notes=notes,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to export notebook %r: %s", notebook_id, exc)
            return None

    # ------------------------------------------------------------------
    # Convenience: build a NotebookData from raw text (manual fallback)
    # ------------------------------------------------------------------

    @staticmethod
    def from_text(title: str, text: str) -> NotebookData:
        """
        Wrap arbitrary text as a :class:`NotebookData` so the rest of the
        pipeline can work without a live NotebookLM connection.

        Useful for testing or when the SDK is unavailable.
        """
        return NotebookData(
            notebook_id="manual",
            title=title,
            sources=[{"title": "Pasted content", "content": text}],
            notes=[],
        )
