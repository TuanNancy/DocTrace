"""Offline retrieval fixtures for the RAG golden set.

The smoke evaluator deliberately does not use Milvus: it ranks the same
page-level chunks with BM25 so CI can detect prompt/context/citation
regressions without network access. The live evaluator uses the real embedder
and a small in-memory cosine store, keeping evaluation independent of the
production catalog and vector database.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import replace
from typing import Iterable, Protocol

from starlette.concurrency import run_in_threadpool

from app.ai.document_summary import is_document_overview
from app.core.config import AppConfig
from app.storage.base import InsertResult, RetrievedChunk, VectorStore
from evals.schema import GoldenDocument

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)
_STOPWORDS = frozenset("""
a an and are as at be been being but by can could did do does for from had has have
he her here hers him his how i if in into is it its itself just may me might more most
must my no nor not of on or our ours ourselves should so some such than that the their
theirs them themselves then these they this those through to too under until up
very was we were what when where which while who whom why will with would you your
yours yourself yourselves many much long often far old
bao nhiêu bao lâu các cho có của được gì khi không là một những phải ra rằng sao sự
thế thì này trong trên từ và vào về với để đến đâu đấy nào
""".split())
_EXPANSIONS = {
    "mfa": ("multi", "factor", "authentication"),
    "daily": ("day",),
    "yearly": ("year",),
    "annual": ("year",),
}
# "include" and "plan" are useful routing words but too generic to prove that a
# passage answers a question. They remain in BM25; they are excluded only from
# the extractive provider's coverage check.
_GENERIC_COVERAGE = frozenset({
    "include", "plan", "document", "pdf",
    "compare", "comparison", "contrast", "difference",
})


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def terms(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    raw = _TOKEN.findall(normalized)
    expanded: list[str] = []
    for token in raw:
        if token in _STOPWORDS or len(token) < 2:
            continue
        token = _stem(token)
        if token in _STOPWORDS:
            continue
        expanded.extend(_EXPANSIONS.get(token, (token,)))
    return expanded


def coverage_terms(text: str) -> set[str]:
    return set(terms(text)) - _GENERIC_COVERAGE


def page_chunks(document: GoldenDocument) -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=f"{document.id}:p{page.page}", doc_id=document.id,
            text=page.text, page=page.page, source=document.title, score=None,
        )
        for page in document.pages
    ]


class Retriever(Protocol):
    async def retrieve(self, query: str, doc_id: str, *, top_k: int) -> list[RetrievedChunk]: ...

    async def all_chunks(self, doc_id: str) -> list[RetrievedChunk]: ...


class LexicalRetriever:
    """Deterministic BM25 over page chunks, one independent index per document."""

    def __init__(self, documents: Iterable[GoldenDocument]):
        self._chunks: dict[str, list[RetrievedChunk]] = {}
        self._tokens: dict[str, list[list[str]]] = {}
        self._df: dict[str, Counter] = {}
        self._avg_length: dict[str, float] = {}
        for document in documents:
            chunks = page_chunks(document)
            tokens = [terms(chunk.text) for chunk in chunks]
            self._chunks[document.id] = chunks
            self._tokens[document.id] = tokens
            self._df[document.id] = Counter(token for row in tokens for token in set(row))
            self._avg_length[document.id] = (
                sum(map(len, tokens)) / len(tokens) if tokens else 0.0
            )

    async def all_chunks(self, doc_id: str) -> list[RetrievedChunk]:
        return list(self._chunks[doc_id])

    def _bm25(self, doc_id: str, index: int, query_terms: set[str]) -> float:
        row = self._tokens[doc_id][index]
        counts = Counter(row)
        total = len(self._chunks[doc_id])
        length = len(row)
        average = self._avg_length[doc_id] or 1.0
        score = 0.0
        for term in query_terms:
            frequency = counts.get(term, 0)
            if not frequency:
                continue
            document_frequency = self._df[doc_id].get(term, 0)
            inverse = math.log(1 + (total - document_frequency + 0.5) / (document_frequency + 0.5))
            score += inverse * frequency * 2.5 / (
                frequency + 1.5 * (1 - 0.75 + 0.75 * length / average)
            )
        return score

    async def retrieve(self, query: str, doc_id: str, *, top_k: int) -> list[RetrievedChunk]:
        chunks = self._chunks[doc_id]
        if is_document_overview(query):
            return list(chunks)
        query_terms = set(terms(query))
        scores = [self._bm25(doc_id, index, query_terms) for index in range(len(chunks))]
        ranked = sorted(range(len(chunks)), key=lambda index: (-scores[index], chunks[index].page))
        return [
            replace(chunks[index], score=scores[index])
            for index in ranked[:max(1, top_k)]
        ]


class InMemoryVectorStore(VectorStore):
    """Owner-scoped cosine store used only for live evaluation."""

    def __init__(self, config: AppConfig):
        super().__init__(config)
        self._chunks: dict[str, list[tuple[RetrievedChunk, list[float]]]] = {}

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def is_connected(self) -> bool:
        return self._connected

    async def ensure_collection(self, vector_dim: int) -> None:
        return None

    async def recreate_collection(self, vector_dim: int) -> None:
        self._chunks.clear()

    async def insert_chunks(
        self, doc_id: str, chunks: list[dict], vectors: list[list[float]],
        batch_size: int = 64, *, user_id: str,
    ) -> InsertResult:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        rows = self._chunks.setdefault(doc_id, [])
        for chunk, vector in zip(chunks, vectors):
            rows.append((
                RetrievedChunk(
                    chunk_id=chunk["chunk_id"], doc_id=doc_id, text=chunk["text"],
                    page=int(chunk["page"]), source=chunk.get("source", doc_id),
                    score=None,
                ),
                vector,
            ))
        return InsertResult(doc_id=doc_id, chunks_inserted=len(chunks))

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            raise ValueError("Vector dimensions differ")
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    async def search_chunks(
        self, query_vector: list[float], doc_id: str | None = None, *,
        top_k: int, min_score: float | None, user_id: str,
    ) -> list[RetrievedChunk]:
        scored = []
        for current_doc, rows in self._chunks.items():
            if doc_id is not None and current_doc != doc_id:
                continue
            for chunk, vector in rows:
                score = self._cosine(query_vector, vector)
                if min_score is None or score >= min_score:
                    scored.append((score, chunk))
        scored.sort(key=lambda item: (-item[0], item[1].page, item[1].chunk_id))
        return [
            RetrievedChunk(**{**chunk.__dict__, "score": round(score, 6)})
            for score, chunk in scored[:max(1, top_k)]
        ]

    async def get_document_chunks(self, doc_id: str, *, user_id: str) -> list[RetrievedChunk]:
        return [
            RetrievedChunk(**{**chunk.__dict__, "score": None})
            for chunk, _ in sorted(self._chunks.get(doc_id, []),
                                   key=lambda item: (item[0].page, item[0].chunk_id))
        ]

    async def get_chunk(self, doc_id: str, chunk_id: str, *, user_id: str) -> RetrievedChunk | None:
        for chunk, _ in self._chunks.get(doc_id, []):
            if chunk.chunk_id == chunk_id:
                return RetrievedChunk(**{**chunk.__dict__, "score": None})
        return None

    async def delete_document(self, doc_id: str, *, user_id: str) -> None:
        self._chunks.pop(doc_id, None)


async def build_vector_index(
    store: InMemoryVectorStore, documents: Iterable[GoldenDocument], embedder,
    usage,
) -> int:
    """Embed every page chunk once. Each document is one metered call."""
    total = 0
    for document in documents:
        chunks = page_chunks(document)
        call = usage.start("index_embedding", getattr(embedder, "_model", "unknown"))
        vectors = await run_in_threadpool(
            embedder.embed_documents, [chunk.text for chunk in chunks], usage=call,
        )
        await store.insert_chunks(
            document.id,
            [{"chunk_id": chunk.chunk_id, "text": chunk.text, "page": chunk.page,
              "source": chunk.source} for chunk in chunks],
            vectors, user_id="eval",
        )
        total += len(chunks)
    return total
