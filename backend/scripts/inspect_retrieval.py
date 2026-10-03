"""
Inspect owner-scoped retrieval with real embedding/vector services.
Usage: python scripts/inspect_retrieval.py <user_id> <doc_id> "câu hỏi 1" ...
"""
import asyncio
import argparse
import logging
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_config
from app.providers.embeddings import get_embedder
from app.storage.factory import create_connected_vector_store
from app.services.document_repository import DocumentRepository

logging.basicConfig(level=logging.INFO, format="%(message)s")


def build_context(chunks, max_chars=500):
    parts = []
    total = 0
    for c in chunks:
        block = f"[Trang {c.page}] (độ liên quan: {c.score:.2f})\n{c.text}"
        if total + len(block) > max_chars and parts:
            break
        parts.append(block)
        total += len(block)
    return "\n\n---\n\n".join(parts)


async def search_chunks(query: str, doc_id: str, user_id: str, *, config, top_k: int, min_score: float):
    document = await DocumentRepository(config).get(user_id, doc_id)
    if document["status"] != "ready" or not document.get("active_index_id"):
        raise ValueError("Document is not ready for retrieval.")
    embedder = get_embedder(config=config)
    vectors = embedder.embed_documents([query])
    if not vectors:
        return []

    vector_store = await create_connected_vector_store(config=config)
    try:
        return await vector_store.search_chunks(
            query_vector=vectors[0],
            doc_id=document["active_index_id"],
            top_k=top_k,
            min_score=min_score,
            user_id=user_id,
        )
    finally:
        await vector_store.disconnect()


def parse_args(argv=None, *, config=None):
    config = config if config is not None else get_config()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_id")
    parser.add_argument("doc_id")
    parser.add_argument("queries", nargs="+")
    parser.add_argument("--top-k", type=int, default=config.retrieval_top_k)
    parser.add_argument("--min-score", type=float, default=config.min_relevance_score)
    args = parser.parse_args(argv)
    if args.top_k <= 0:
        parser.error("--top-k must be positive")
    if not math.isfinite(args.min_score):
        parser.error("--min-score must be finite")
    return args


async def main():
    config = get_config()
    args = parse_args(config=config)
    print(f"Retrieval settings: top_k={args.top_k}, min_score={args.min_score}")
    for q in args.queries:
        print(f"\n--- Query: {q!r} ---")
        chunks = await search_chunks(q, args.doc_id, args.user_id, config=config,
                                     top_k=args.top_k, min_score=args.min_score)
        for i, c in enumerate(chunks, 1):
            print(f"  [{i}] page={c.page} score={c.score:.4f} source={c.source!r}")
            print(f"      text: {c.text[:120]}...")
        if chunks:
            ctx = build_context(chunks, max_chars=500)
            print(f"  context preview: {len(ctx)} chars")


if __name__ == "__main__":
    asyncio.run(main())
