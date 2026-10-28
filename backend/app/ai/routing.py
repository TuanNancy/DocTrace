"""Deterministic model routing; no silent downgrade after a provider error.

Routing is opt-in. Pro requests keep the configured quality model except for
clearly complex/overview work, where the intentionally stronger default model is
used. Free requests use the cheap model when configured. The route reason is
logged and bound into the exact-cache policy key.
"""
from dataclasses import dataclass
import re
import unicodedata

from app.core.config import AppConfig

COMPLEX_MARKERS = frozenset({
    "analyze", "analysis", "compare", "comparison", "contrast", "tradeoff",
    "trade-offs", "why", "evaluate", "summarize", "summary",
    "so", "sánh", "phân", "tích", "đánh", "giá", "tại", "sao", "tóm", "tắt",
})


@dataclass(frozen=True)
class RouteDecision:
    model: str
    reason: str
    input_micros_per_mtok: int
    output_micros_per_mtok: int


def _tokens(value: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFKC", value).casefold())


def is_complex_query(query: str, *, word_limit: int) -> bool:
    words = _tokens(query)
    if len(words) > word_limit:
        return True
    markers = COMPLEX_MARKERS & set(words)
    # "so sánh" and similar Vietnamese markers use separate tokens.
    return bool(markers)


def choose_route(config: AppConfig, *, plan: str, query: str, overview: bool) -> RouteDecision:
    default = getattr(config, "model", "")
    default_rates = (
        getattr(config, "model_input_micros_per_mtok", 0),
        getattr(config, "model_output_micros_per_mtok", 0),
    )
    if not getattr(config, "model_routing_enabled", False):
        return RouteDecision(default, "routing_off", *default_rates)
    cheap = getattr(config, "cheap_model", None)
    if not cheap:
        return RouteDecision(default, "routing_unconfigured", *default_rates)
    cheap_rates = (
        getattr(config, "cheap_input_micros_per_mtok", 0),
        getattr(config, "cheap_output_micros_per_mtok", 0),
    )
    if plan == "free":
        return RouteDecision(cheap, "free_plan_cheap", *cheap_rates)
    complex_query = overview or is_complex_query(
        query, word_limit=getattr(config, "complex_query_words", 30),
    )
    if complex_query:
        return RouteDecision(default, "pro_complex_strong", *default_rates)
    return RouteDecision(default, "pro_standard_strong", *default_rates)
