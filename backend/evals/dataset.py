"""Load and validate the checked-in YAML golden set."""
from pathlib import Path
import hashlib
import json

import yaml

from evals.schema import Evidence, GoldenCase, GoldenDocument, GoldenPage, GoldenSet

DEFAULT_PATH = Path(__file__).resolve().parent / "golden" / "rag.yaml"


class GoldenSetError(ValueError):
    pass


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoldenSetError(f"{field} must be a non-empty string")
    return value.strip()


def _page(value, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise GoldenSetError(f"{field} must be a positive integer")
    return value


def load(path: Path | str = DEFAULT_PATH) -> GoldenSet:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GoldenSetError(f"Cannot read golden set: {path}") from exc
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise GoldenSetError("Golden set must be a mapping with version: 1")
    documents_raw = raw.get("documents")
    cases_raw = raw.get("cases")
    if not isinstance(documents_raw, list) or not documents_raw:
        raise GoldenSetError("documents must be a non-empty list")
    if not isinstance(cases_raw, list) or not cases_raw:
        raise GoldenSetError("cases must be a non-empty list")

    documents, doc_ids = [], set()
    for index, item in enumerate(documents_raw):
        if not isinstance(item, dict):
            raise GoldenSetError(f"documents[{index}] must be a mapping")
        doc_id = _text(item.get("id"), f"documents[{index}].id")
        if doc_id in doc_ids:
            raise GoldenSetError(f"duplicate document id: {doc_id}")
        doc_ids.add(doc_id)
        title = _text(item.get("title"), f"documents[{index}].title")
        pages_raw = item.get("pages")
        if not isinstance(pages_raw, list) or not pages_raw:
            raise GoldenSetError(f"documents[{index}].pages must be non-empty")
        pages, page_numbers = [], set()
        for page_index, page in enumerate(pages_raw):
            if not isinstance(page, dict):
                raise GoldenSetError(f"documents[{index}].pages[{page_index}] must be a mapping")
            number = _page(page.get("page"), f"documents[{index}].pages[{page_index}].page")
            if number in page_numbers:
                raise GoldenSetError(f"duplicate page {number} in {doc_id}")
            page_numbers.add(number)
            pages.append(GoldenPage(number, _text(page.get("text"), f"documents[{index}].pages[{page_index}].text")))
        documents.append(GoldenDocument(doc_id, title, tuple(sorted(pages, key=lambda page: page.page))))

    cases, case_ids = [], set()
    for index, item in enumerate(cases_raw):
        if not isinstance(item, dict):
            raise GoldenSetError(f"cases[{index}] must be a mapping")
        case_id = _text(item.get("id"), f"cases[{index}].id")
        if case_id in case_ids:
            raise GoldenSetError(f"duplicate case id: {case_id}")
        case_ids.add(case_id)
        doc_id = _text(item.get("doc"), f"cases[{index}].doc")
        if doc_id not in doc_ids:
            raise GoldenSetError(f"cases[{index}] references unknown document: {doc_id}")
        language = _text(item.get("language"), f"cases[{index}].language")
        if language not in ("vi", "en"):
            raise GoldenSetError(f"cases[{index}].language must be vi or en")
        category = _text(item.get("category"), f"cases[{index}].category")
        expected_refusal = item.get("expected_refusal", False)
        if not isinstance(expected_refusal, bool):
            raise GoldenSetError(f"cases[{index}].expected_refusal must be a boolean")
        must_include = item.get("must_include", [])
        must_not_include = item.get("must_not_include", [])
        for name, values in (("must_include", must_include), ("must_not_include", must_not_include)):
            if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
                raise GoldenSetError(f"cases[{index}].{name} must be a list of non-empty strings")
        evidence_raw = item.get("evidence", [])
        if not isinstance(evidence_raw, list):
            raise GoldenSetError(f"cases[{index}].evidence must be a list")
        if expected_refusal and evidence_raw:
            raise GoldenSetError(f"cases[{index}] is a refusal case and cannot carry evidence")
        if not expected_refusal and not evidence_raw:
            raise GoldenSetError(f"cases[{index}] needs evidence")
        document = next(document for document in documents if document.id == doc_id)
        evidence = []
        for evidence_index, entry in enumerate(evidence_raw):
            if not isinstance(entry, dict):
                raise GoldenSetError(f"cases[{index}].evidence[{evidence_index}] must be a mapping")
            number = _page(entry.get("page"), f"cases[{index}].evidence[{evidence_index}].page")
            page = document.page(number)
            if page is None:
                raise GoldenSetError(f"cases[{index}] references missing page {number} in {doc_id}")
            text = _text(entry.get("text"), f"cases[{index}].evidence[{evidence_index}].text")
            if _normalize(text) not in _normalize(page.text):
                raise GoldenSetError(f"cases[{index}] evidence is not present on page {number}: {text}")
            evidence.append(Evidence(number, text))
        cases.append(GoldenCase(
            id=case_id, doc=doc_id, query=_text(item.get("query"), f"cases[{index}].query"),
            language=language, category=category, expected_refusal=expected_refusal,
            must_include=tuple(value.strip() for value in must_include),
            must_not_include=tuple(value.strip() for value in must_not_include),
            evidence=tuple(evidence),
        ))
    return GoldenSet(1, tuple(documents), tuple(cases))


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def dataset_sha256(dataset: GoldenSet) -> str:
    canonical = {
        "version": dataset.version,
        "documents": [
            {"id": doc.id, "title": doc.title,
             "pages": [{"page": page.page, "text": page.text} for page in doc.pages]}
            for doc in dataset.documents
        ],
        "cases": [
            {"id": case.id, "doc": case.doc, "query": case.query, "language": case.language,
             "category": case.category, "expected_refusal": case.expected_refusal,
             "must_include": list(case.must_include), "must_not_include": list(case.must_not_include),
             "evidence": [{"page": item.page, "text": item.text} for item in case.evidence]}
            for case in dataset.cases
        ],
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
