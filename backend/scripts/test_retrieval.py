"""
Test retrieval with different queries; verify top-k results.
Usage: python scripts/test_retrieval.py <doc_id> "câu hỏi 1" "câu hỏi 2" ...
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_config
from app.providers.embeddings import get_embedder
from app.storage.factory import create_and_connect_storage

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


async def search_chunks(query: str, doc_id: str, top_k: int = 5):
    embedder = get_embedder()
    vectors = embedder.embed_documents([query])
    if not vectors:
        return []

    storage = await create_and_connect_storage()
    try:
        return await storage.search_chunks(
            query_vector=vectors[0],
            doc_id=doc_id,
            top_k=top_k,
            min_score=0.32,
        )
    finally:
        await storage.disconnect()


async def main():
    if len(sys.argv) < 3:
        print('Usage: python scripts/test_retrieval.py <doc_id> "query1" "query2" ...')
        sys.exit(1)

    doc_id = sys.argv[1]
    queries = sys.argv[2:]

    for q in queries:
        print(f"\n--- Query: {q!r} ---")
        chunks = await search_chunks(q, doc_id, top_k=5)
        for i, c in enumerate(chunks, 1):
            print(f"  [{i}] page={c.page} score={c.score:.4f} source={c.source!r}")
            print(f"      text: {c.text[:120]}...")
        if chunks:
            ctx = build_context(chunks, max_chars=500)
            print(f"  context preview: {len(ctx)} chars")


if __name__ == "__main__":
    asyncio.run(main())
