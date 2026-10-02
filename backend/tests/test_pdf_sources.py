from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.processors.pdf import chunk_documents, load_pdf_pages


def test_actual_pdf_pages_use_original_filename_and_one_based_navigation(tmp_path):
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for number in (1, 2):
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 50 700 Td (Physical page {number}: original text for citation verification.) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    path = tmp_path / "random-private-temp-name.pdf"
    writer.write(path)
    pages, _ = load_pdf_pages(str(path), original_filename="Báo cáo.pdf")
    chunks = chunk_documents(pages)
    assert [page.metadata["page"] for page in pages] == [1, 2]
    assert {chunk["source"] for chunk in chunks} == {"Báo cáo.pdf"}
    assert [(chunk["page"], f"Physical page {chunk['page']}" in chunk["text"]) for chunk in chunks] == [(1, True), (2, True)]
