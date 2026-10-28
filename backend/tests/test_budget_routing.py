"""Routing policy and worst-case monetary request budgets."""
import pytest

from app.ai.budget import BudgetExceededError, RequestBudget, budget_for
from app.ai.routing import choose_route, is_complex_query
from app.core.config import AppConfig


def test_routing_is_off_by_default_and_requires_a_cheap_model():
    config = AppConfig.from_env({"RAG_MODEL": "strong"})
    assert choose_route(config, plan="free", query="leave days?", overview=False) == (
        choose_route(config, plan="pro", query="leave days?", overview=False)
    )
    assert choose_route(config, plan="free", query="q", overview=False).model == "strong"
    assert choose_route(config, plan="free", query="q", overview=False).reason == "routing_off"
    with pytest.raises(ValueError, match="CHEAP_MODEL"):
        AppConfig.from_env({"MODEL_ROUTING_ENABLED": "true"})


def test_free_plan_uses_cheap_rates_and_pro_complex_keeps_the_quality_model():
    config = AppConfig.from_env({
        "RAG_MODEL": "strong", "CHEAP_MODEL": "cheap", "MODEL_ROUTING_ENABLED": "true",
        "MODEL_INPUT_MICROS_PER_MTOK": "1000", "MODEL_OUTPUT_MICROS_PER_MTOK": "2000",
        "CHEAP_INPUT_MICROS_PER_MTOK": "100", "CHEAP_OUTPUT_MICROS_PER_MTOK": "200",
    })
    free = choose_route(config, plan="free", query="How much leave?", overview=False)
    assert (free.model, free.reason) == ("cheap", "free_plan_cheap")
    assert (free.input_micros_per_mtok, free.output_micros_per_mtok) == (100, 200)

    standard = choose_route(config, plan="pro", query="How much leave?", overview=False)
    assert (standard.model, standard.reason) == ("strong", "pro_standard_strong")
    complex_query = choose_route(config, plan="pro", query="Compare leave and remote policy", overview=False)
    assert (complex_query.model, complex_query.reason) == ("strong", "pro_complex_strong")
    overview = choose_route(config, plan="pro", query="Summarize this PDF", overview=True)
    assert (overview.model, overview.reason) == ("strong", "pro_complex_strong")


def test_complexity_detection_is_bounded_and_bilingual():
    assert is_complex_query("Compare these policies", word_limit=30)
    assert is_complex_query("So sánh chính sách nghỉ phép", word_limit=30)
    assert not is_complex_query("How much annual leave?", word_limit=30)
    assert is_complex_query("word " * 31, word_limit=30)


def test_budget_reduces_output_tokens_and_rejects_an_impossible_call():
    budget = RequestBudget(cap_micros=1000, input_micros_per_mtok=150000,
                           output_micros_per_mtok=600000)
    allowed = budget.reserve_output(300, 2048)
    assert 0 < allowed < 2048
    assert budget.reserved_micros <= 1000

    tiny = RequestBudget(cap_micros=5, input_micros_per_mtok=150000,
                         output_micros_per_mtok=600000)
    with pytest.raises(BudgetExceededError):
        tiny.reserve_output(300, 2048)


def test_budget_disabled_returns_requested_tokens_and_multiple_calls_share_a_cap():
    disabled = RequestBudget(cap_micros=0, input_micros_per_mtok=0, output_micros_per_mtok=0)
    assert disabled.reserve_output(10_000, 2048) == 2048
    assert disabled.reserved_micros == 0

    budget = RequestBudget(cap_micros=5, input_micros_per_mtok=1000,
                           output_micros_per_mtok=1000)
    first = budget.reserve_output(30, 100)
    second = budget.reserve_output(30, 100)
    assert first == second == 100
    with pytest.raises(BudgetExceededError):
        budget.reserve_output(3000, 100)


def test_budget_for_uses_the_routed_model_prices():
    config = AppConfig.from_env({
        "REQUEST_COST_CAP_MICROS": "500", "MODEL_INPUT_MICROS_PER_MTOK": "10",
        "MODEL_OUTPUT_MICROS_PER_MTOK": "20",
    })
    route = choose_route(config, plan="free", query="q", overview=False)
    budget = budget_for(config, route)
    assert budget is not None
    assert (budget.cap_micros, budget.input_micros_per_mtok, budget.output_micros_per_mtok) == (500, 10, 20)
    assert budget_for(config, route.__class__(route.model, route.reason, 0, 20)) is None


async def test_pipeline_passes_the_reserved_output_limit_to_the_provider():
    from types import SimpleNamespace
    from app.ai.rag_pipeline import RAGPipeline
    from app.storage.base import RetrievedChunk

    class Provider:
        model = "strong"

        def __init__(self):
            self.kwargs = None

        async def stream_with_context(self, **kwargs):
            self.kwargs = kwargs
            yield "ok"

    provider = Provider()
    config = SimpleNamespace(
        model="strong", temperature=0, max_tokens=2048, summary_max_calls=8,
        context_max_chars=12000, retrieval_top_k=8, min_relevance_score=0.32,
    )
    budget = RequestBudget(cap_micros=200, input_micros_per_mtok=150000,
                           output_micros_per_mtok=600000)
    pipeline = RAGPipeline(chat_provider=provider, config=config, budget=budget)
    chunks = [RetrievedChunk("c1", "doc", "Evidence text.", 1, "doc.pdf", 0.9)]

    answer = "".join([part async for part in pipeline.stream_answer(
        "Question?", "doc", "en", user_id="user", retrieved_chunks_override=chunks,
    )])

    assert answer == "ok"
    assert 0 < provider.kwargs["max_tokens"] < 2048
    assert budget.reserved_micros <= 200
