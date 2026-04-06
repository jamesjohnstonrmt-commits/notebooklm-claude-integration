"""
Content generation using the Anthropic (Claude) API.

This module takes notebook content from NotebookLM and asks Claude to
produce structured presentation material:
- A presentation title
- Per-slide: title, bullet points, speaker notes
- A workbook introduction paragraph
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic

logger = logging.getLogger(__name__)


class SlideContent:
    """Holds the generated content for a single slide."""

    def __init__(
        self,
        title: str,
        bullets: list[str],
        speaker_notes: str,
    ) -> None:
        self.title = title
        self.bullets = bullets
        self.speaker_notes = speaker_notes

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SlideContent title={self.title!r} bullets={len(self.bullets)}>"


class PresentationContent:
    """Full presentation content returned by :class:`ClaudeGenerator`."""

    def __init__(
        self,
        title: str,
        slides: list[SlideContent],
        workbook_intro: str,
    ) -> None:
        self.title = title
        self.slides = slides
        self.workbook_intro = workbook_intro

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PresentationContent title={self.title!r} slides={len(self.slides)}>"


_SYSTEM_PROMPT = """You are an expert presentation designer and educator.
Your job is to transform research notes into clear, engaging presentation slides.
Always respond with valid JSON in exactly the schema requested."""

_PRESENTATION_PROMPT_TEMPLATE = """
You will receive content from a NotebookLM notebook and must produce structured
presentation material in JSON format.

=== NOTEBOOK CONTENT ===
{notebook_text}
========================

Create a presentation with {num_slides} slides.

Respond with ONLY valid JSON matching this exact schema (no markdown, no prose):

{{
  "title": "<overall presentation title>",
  "workbook_intro": "<2-3 sentence paragraph introducing the workbook>",
  "slides": [
    {{
      "title": "<slide title>",
      "bullets": ["<bullet 1>", "<bullet 2>", "<bullet 3>"],
      "speaker_notes": "<paragraph of speaker notes for this slide>"
    }}
  ]
}}

Guidelines:
- Keep slide titles concise (5 words or fewer where possible).
- Each slide should have 3-5 bullet points.
- Bullet points should be 10 words or fewer.
- Speaker notes should expand on the bullets with 2-4 sentences.
- The workbook intro should frame the topic for a learner.
"""


class ClaudeGenerator:
    """
    Generates presentation content by sending notebook data to Claude.

    Parameters
    ----------
    api_key:
        Anthropic API key.
    model:
        Claude model identifier (default: claude-opus-4-5).
    """

    def __init__(self, api_key: str, model: str = "claude-opus-4-5") -> None:
        if not api_key or api_key == "your-claude-api-key-here":
            raise ValueError(
                "A valid Claude API key is required. "
                "Set CLAUDE_API_KEY in your .env file or environment."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_presentation(
        self,
        notebook_text: str,
        num_slides: int = 8,
    ) -> PresentationContent:
        """
        Send *notebook_text* to Claude and return a
        :class:`PresentationContent` instance.

        Parameters
        ----------
        notebook_text:
            The raw text from :meth:`NotebookData.to_text`.
        num_slides:
            How many slides to generate (default: 8).
        """
        prompt = _PRESENTATION_PROMPT_TEMPLATE.format(
            notebook_text=notebook_text,
            num_slides=num_slides,
        )

        logger.info("Sending notebook content to Claude (%s)…", self.model)
        response = self._client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text.strip()
        return self._parse_response(raw_text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_response(raw_text: str) -> PresentationContent:
        """Parse Claude's JSON response into a :class:`PresentationContent`."""
        # Strip potential markdown fences
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()

        try:
            data: dict[str, Any] = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            logger.error("Claude returned invalid JSON: %s\n---\n%s", exc, raw_text)
            raise ValueError(
                f"Claude returned content that could not be parsed as JSON: {exc}"
            ) from exc

        title = data.get("title", "Untitled Presentation")
        workbook_intro = data.get("workbook_intro", "")

        slides: list[SlideContent] = []
        for raw_slide in data.get("slides", []):
            slides.append(
                SlideContent(
                    title=raw_slide.get("title", ""),
                    bullets=raw_slide.get("bullets", []),
                    speaker_notes=raw_slide.get("speaker_notes", ""),
                )
            )

        return PresentationContent(
            title=title,
            slides=slides,
            workbook_intro=workbook_intro,
        )
