"""Golden-set schema and validation. No provider or network access."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GoldenPage:
    page: int
    text: str


@dataclass(frozen=True)
class GoldenDocument:
    id: str
    title: str
    pages: tuple[GoldenPage, ...]

    def page(self, number: int) -> Optional[GoldenPage]:
        return next((page for page in self.pages if page.page == number), None)


@dataclass(frozen=True)
class Evidence:
    page: int
    text: str


@dataclass(frozen=True)
class GoldenCase:
    id: str
    doc: str
    query: str
    language: str
    category: str
    expected_refusal: bool
    must_include: tuple[str, ...]
    must_not_include: tuple[str, ...]
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class GoldenSet:
    version: int
    documents: tuple[GoldenDocument, ...]
    cases: tuple[GoldenCase, ...]

    def document(self, doc_id: str) -> GoldenDocument:
        return next(document for document in self.documents if document.id == doc_id)
