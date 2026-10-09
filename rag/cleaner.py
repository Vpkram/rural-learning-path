"""Normalize extracted text without discarding its source or page metadata."""

from __future__ import annotations

import re
import unicodedata

from rag.models import DocumentPage


_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HORIZONTAL_SPACE = re.compile(r"[^\S\n]+")
_EXCESS_NEWLINES = re.compile(r"\n{3,}")


def clean_text(text: str) -> str:
    """Normalize Unicode and whitespace while keeping paragraph boundaries."""
    if not isinstance(text, str):
        raise TypeError("text must be a string.")
    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00ad", "")
    normalized = _CONTROL_CHARACTERS.sub("", normalized)
    lines = [_HORIZONTAL_SPACE.sub(" ", line).strip() for line in normalized.split("\n")]
    cleaned = "\n".join(lines)
    return _EXCESS_NEWLINES.sub("\n\n", cleaned).strip()


def clean_pages(pages: list[DocumentPage]) -> list[DocumentPage]:
    """Clean each page independently so page boundaries remain intact."""
    cleaned_pages: list[DocumentPage] = []
    for page in pages:
        cleaned = clean_text(page.text)
        if cleaned:
            cleaned_pages.append(
                DocumentPage(source=page.source, page_number=page.page_number, text=cleaned)
            )
    return cleaned_pages
