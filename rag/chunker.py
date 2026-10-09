"""Split cleaned page text into bounded, overlapping retrieval chunks."""

from __future__ import annotations

from rag.models import DocumentPage, TextChunk


def _chunk_page(page: DocumentPage, chunk_size: int, overlap: int) -> list[str]:
    text = page.text.strip()
    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + 1, end + 1)
            if boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break

        next_start = max(start + 1, end - overlap)
        while next_start < end and text[next_start].isspace():
            next_start += 1
        start = next_start

    return chunks


def chunk_pages(
    pages: list[DocumentPage],
    chunk_size: int = 900,
    overlap: int = 120,
) -> list[TextChunk]:
    """Create character-bounded chunks per page with stable IDs and page references."""
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
        raise ValueError("chunk_size must be a positive integer.")
    if isinstance(overlap, bool) or not isinstance(overlap, int) or overlap < 0:
        raise ValueError("overlap must be a non-negative integer.")
    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size.")

    result: list[TextChunk] = []
    for page in pages:
        for page_chunk_number, text in enumerate(_chunk_page(page, chunk_size, overlap), start=1):
            page_part = str(page.page_number) if page.page_number is not None else "na"
            chunk_id = f"{page.source}:p{page_part}:c{page_chunk_number}"
            result.append(
                TextChunk(
                    chunk_id=chunk_id,
                    source=page.source,
                    page_number=page.page_number,
                    text=text,
                )
            )
    return result
