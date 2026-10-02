"""Document summaries must cover long inputs without weakening ordinary retrieval."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.document_summary import is_document_overview
from app.ai.rag_pipeline import RAGPipeline
from app.storage.base import RetrievedChunk


@pytest.mark.parametrize("query", [
    "Nội dung chính sách nghỉ phép là gì?", "What is the summary table's revenue?",
    "How many days of annual leave?", "Hợp đồng hết hạn ngày nào?",
])
def test_specific_questions_keep_vector_retrieval(query):
    assert not is_document_overview(query)


async def test_recursive_summary_keeps_last_section_and_respects_context_budget():
    provider = AsyncMock()
    inputs = []

    async def summarize(**kwargs):
        context = kwargs["context"]
        inputs.append(context)
        assert len(context) <= 600
        assert kwargs["temperature"] == 0
        marker = "FINAL-FACT (trang 7)" if "FINAL-FACT" in context else "Other facts"
        return marker + " notes" * 25

    provider.generate_with_context.side_effect = summarize
    pipeline = RAGPipeline(chat_provider=provider, config=SimpleNamespace(context_max_chars=600, max_tokens=2048))
    chunks = [RetrievedChunk("id", "doc", "text " * 1000 + "FINAL-FACT", 7, "long.pdf", None)]
    context = await pipeline._build_summary_context(chunks, "Summarize this PDF", "en")
    assert "FINAL-FACT" in context
    assert len(context) <= 600
    assert len(inputs) > 9  # Original sections plus a second reduction pass.
    assert all("[Trang 7]" in section for section in inputs[:9])


@pytest.mark.parametrize("response", ["", "x" * 1200])
async def test_failed_compression_stops_instead_of_looping_or_silently_dropping_text(response):
    provider = AsyncMock()
    provider.generate_with_context.return_value = response
    pipeline = RAGPipeline(chat_provider=provider, config=SimpleNamespace(context_max_chars=600, max_tokens=2048))
    chunks = [RetrievedChunk("id", "doc", "x" * 1200, 1, "long.pdf", None)]
    with pytest.raises(RuntimeError):
        await pipeline._build_summary_context(chunks, "Summarize", "en")
    assert provider.generate_with_context.await_count <= 3
