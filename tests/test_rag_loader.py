from types import SimpleNamespace

import pytest

from rag.loader import DocumentLoadError, load_document


def test_pdf_loader_preserves_one_based_page_numbers(monkeypatch, tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"test pdf fixture")

    class FakePdf:
        def __enter__(self):
            return iter([SimpleNamespace(get_text=lambda _kind: "first page"), SimpleNamespace(get_text=lambda _kind: "second page")])

        def __exit__(self, *_args):
            return False

    monkeypatch.setitem(__import__("sys").modules, "fitz", SimpleNamespace(open=lambda _path: FakePdf()))
    pages = load_document(pdf)
    assert [(page.page_number, page.text) for page in pages] == [(1, "first page"), (2, "second page")]
    assert [(page.page_number, page.text) for page in load_document(pdf, start_page=2, end_page=2)] == [
        (2, "second page")
    ]


def test_docx_loader_marks_page_unknown_and_reads_tables(monkeypatch, tmp_path):
    docx = tmp_path / "book.docx"
    docx.write_bytes(b"test docx fixture")
    fake_document = SimpleNamespace(
        paragraphs=[SimpleNamespace(text="First paragraph"), SimpleNamespace(text="")],
        tables=[
            SimpleNamespace(
                rows=[
                    SimpleNamespace(cells=[SimpleNamespace(text="Term"), SimpleNamespace(text="Meaning")])
                ]
            )
        ],
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "docx",
        SimpleNamespace(Document=lambda _path: fake_document),
    )

    pages = load_document(docx)
    assert len(pages) == 1
    assert pages[0].page_number is None
    assert "First paragraph" in pages[0].text
    assert "Term | Meaning" in pages[0].text


def test_loader_rejects_unsupported_and_empty_documents(tmp_path, monkeypatch):
    unsupported = tmp_path / "book.txt"
    unsupported.write_text("text", encoding="utf-8")
    with pytest.raises(DocumentLoadError, match="Only PDF and DOCX"):
        load_document(unsupported)

    pdf = tmp_path / "empty.pdf"
    pdf.write_bytes(b"empty fixture")

    class EmptyPdf:
        def __enter__(self):
            return iter([SimpleNamespace(get_text=lambda _kind: "  ")])

        def __exit__(self, *_args):
            return False

    monkeypatch.setitem(__import__("sys").modules, "fitz", SimpleNamespace(open=lambda _path: EmptyPdf()))
    with pytest.raises(DocumentLoadError, match="No readable text"):
        load_document(pdf)
