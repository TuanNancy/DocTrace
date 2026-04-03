"""
Test retrieval with different queries; verify top-k results.
Usage: python scripts/test_retrieval.py <doc_id> "câu hỏi 1" "câu hỏi 2" ...
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.retrieval import build_context, search_chunks

logging.basicConfig(level=logging.INFO, format="%(message)s")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_retrieval.py <doc_id> \"query1\" \"query2\" ...")
        sys.exit(1)
    doc_id = sys.argv[1]
    queries = sys.argv[2:]
    for q in queries:
        print(f"\n--- Query: {q!r} ---")
        chunks = search_chunks(q, doc_id, top_k=5)
        for i, c in enumerate(chunks, 1):
            print(f"  [{i}] page={c.page} score={c.score:.4f} source={c.source!r}")
            print(f"      text: {c.text[:120]}...")
        if chunks:
            ctx = build_context(chunks, max_chars=500)
            print(f"  context preview: {len(ctx)} chars")
