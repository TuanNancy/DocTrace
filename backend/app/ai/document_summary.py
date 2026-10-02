"""Recognize document-level requests and pack their context without dropping text."""
import re
import unicodedata
from typing import Iterable


def is_document_overview(query: str) -> bool:
    normalized = unicodedata.normalize("NFD", query.lower().replace("đ", "d"))
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    normalized = " ".join(normalized.split()).strip(" .?!")
    if normalized in {"noi dung chinh", "y chinh", "tong quan", "summary", "summarize", "overview"}:
        return True
    document = r"(?:file(?: pdf)?|pdf|tai lieu|van ban|bao cao)"
    patterns = (
        r"\b(?:tom tat|summari[sz]e)\b",
        r"\b(?:summary|overview)\s+(?:of|for)\b",
        rf"\b(?:noi dung chinh|y chinh|chu de chinh|tong quan)(?:\s+(?:cua|trong|ve))?\s+{document}\b",
        rf"\b{document}(?:\s+nay)?\s+(?:(?:viet|noi|de cap)\s+ve|la)\s+(?:cai |dieu |van de )?gi\b",
        r"\bwhat(?: is|'s)\s+(?:(?:this|the)\s+)?(?:pdf|file|document|report|paper)\s+about\b",
    )
    return any(re.search(pattern, normalized) for pattern in patterns)


def pack_contexts(sections: Iterable[str], max_chars: int) -> list[str]:
    """Pack all sections into bounded requests, splitting oversized sections as needed."""
    if max_chars <= 0:
        raise ValueError("Context character limit must be positive.")
    contexts = []
    current = ""
    for section in sections:
        for start in range(0, len(section), max_chars):
            part = section[start:start + max_chars]
            if current and len(current) + len(part) + 2 > max_chars:
                contexts.append(current)
                current = ""
            current = f"{current}\n\n{part}" if current else part
    if current:
        contexts.append(current)
    return contexts
