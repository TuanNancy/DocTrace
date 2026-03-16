"""
Retrieval: embed query → Milvus ANN search (metric_type=COSINE, expr filter by doc_id).
Also includes context builder and Vietnamese system prompt used for RAG answers.
"""
import logging
from dataclasses import dataclass

from pymilvus import Collection

from app.providers.embeddings import get_embedder
from app.providers.milvus import (
    COLLECTION_NAME,
    DOC_ID_FIELD,
    PAGE_FIELD,
    SOURCE_FIELD,
    TEXT_FIELD,
    VECTOR_FIELD,
)

logger = logging.getLogger(__name__)

# Search params
SEARCH_METRIC = "COSINE"
DEFAULT_TOP_K = 8
IVF_NPROBE = 32


@dataclass
class RetrievedChunk:
    """Single chunk from ANN search with metadata and score."""

    text: str
    page: int
    source: str
    score: float


def search_chunks(
    query: str,
    doc_id: str,
    top_k: int = DEFAULT_TOP_K,
) -> list[RetrievedChunk]:
    """
    Embed query, search Milvus with metric_type=COSINE and expr filter doc_id.
    Returns list of RetrievedChunk (text, page, source, score).
    """
    if not query or not doc_id:
        return []

    embedder = get_embedder()
    query_vector = embedder.embed_documents([query])
    if not query_vector:
        return []
    query_vector = query_vector[0]

    try:
        collection = Collection(COLLECTION_NAME)
    except Exception as e:
        logger.warning("Collection not available: %s", e)
        return []

    # Filter by doc_id (VARCHAR: use quoted string in expr)
    expr = f'{DOC_ID_FIELD} == "{doc_id}"'
    search_param = {
        "metric_type": SEARCH_METRIC,
        "params": {"nprobe": IVF_NPROBE},
    }
    output_fields = [TEXT_FIELD, PAGE_FIELD, SOURCE_FIELD]

    results = collection.search(
        data=[query_vector],
        anns_field=VECTOR_FIELD,
        param=search_param,
        limit=top_k,
        expr=expr,
        output_fields=output_fields,
    )

    out: list[RetrievedChunk] = []
    if not results or len(results) == 0:
        return out

    for hit in results[0]:
        entity = hit.get("entity", hit) if isinstance(hit, dict) else getattr(hit, "entity", hit)
        if isinstance(entity, dict):
            text = entity.get(TEXT_FIELD) or ""
            page = entity.get(PAGE_FIELD, 0) or 0
            source = entity.get(SOURCE_FIELD) or ""
        else:
            text = getattr(entity, TEXT_FIELD, "") or ""
            page = getattr(entity, PAGE_FIELD, 0) or 0
            source = getattr(entity, SOURCE_FIELD, "") or ""
        score = float(hit.get("distance", hit.score if hasattr(hit, "score") else 0) or 0.0)
        out.append(
            RetrievedChunk(text=str(text), page=int(page), source=str(source), score=score)
        )

    logger.info("Retrieval: query=%r doc_id=%s top_k=%s -> %s hits", query[:50], doc_id, top_k, len(out))
    return out


# ---- Context builder & system prompt ----

SYSTEM_PROMPT_VI = """Bạn là trợ lý trả lời câu hỏi dựa trên nội dung tài liệu PDF được cung cấp.
Hãy trả lời ngắn gọn, chính xác và chỉ dựa vào ngữ cảnh bên dưới.
Khi trích dẫn thông tin, luôn ghi rõ số trang nguồn (ví dụ: (trang 3), (trang 5-6)).
Nếu ngữ cảnh không chứa thông tin để trả lời, hãy nói rõ và không bịa đặt."""


def build_context(chunks: list[RetrievedChunk], max_chars: int = 6000) -> str:
    """
    Ghép các chunk với số trang và relevance score thành một đoạn ngữ cảnh.
    Mỗi đoạn dạng: [Trang X] (độ liên quan: Y) \\n nội dung
    Giới hạn tổng ký tự bằng max_chars.
    """
    parts: list[str] = []
    total = 0
    for c in chunks:
        block = f"[Trang {c.page}] (độ liên quan: {c.score:.2f})\n{c.text}"
        if total + len(block) > max_chars and parts:
            break
        parts.append(block)
        total += len(block)
    return "\n\n---\n\n".join(parts) if parts else ""

