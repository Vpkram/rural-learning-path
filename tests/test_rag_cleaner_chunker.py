import pytest

from rag.chunker import chunk_pages
from rag.cleaner import clean_pages, clean_text
from rag.models import DocumentPage


def test_clean_text_normalizes_unicode_controls_and_whitespace():
    assert clean_text("Ａ  B\r\n\r\nC\u00ad\x00") == "A B\n\nC"


def test_clean_pages_preserves_metadata_and_drops_empty_text():
    pages = [
        DocumentPage("book.pdf", 4, "  cleaned   page "),
        DocumentPage("book.pdf", 5, " \n "),
    ]
    assert clean_pages(pages) == [DocumentPage("book.pdf", 4, "cleaned page")]


def test_chunker_preserves_page_and_has_overlapping_content():
    page = DocumentPage("book.pdf", 2, "one two three four five six seven eight nine ten")
    chunks = chunk_pages([page], chunk_size=18, overlap=5)
    assert len(chunks) > 1
    assert all(chunk.page_number == 2 for chunk in chunks)
    assert all(chunk.source == "book.pdf" for chunk in chunks)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)
    assert chunks[0].text.split()[-1] in chunks[1].text


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (10, -1), (10, 10), (True, 0)],
)
def test_chunker_rejects_invalid_size_or_overlap(chunk_size, overlap):
    with pytest.raises(ValueError):
        chunk_pages([DocumentPage("book.pdf", 1, "text")], chunk_size, overlap)
