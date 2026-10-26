"""Per-call provider usage accounting.

OpenRouter reports token usage and cost on both regular and streaming chat
responses. A ``ProviderCall`` is one logical metered call: an answer, one
summary pass, or one embedding batch request. Callers own attribution; the
provider only fills usage fields, so request state never leaks between calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

COST_STATUSES = ("reported", "reconciled", "estimated", "unknown")
CALL_KINDS = ("query_embedding", "index_embedding", "summary", "answer", "embedding_probe")
_MICROS = Decimal("1000000")


def _jsonable(value: Any) -> Any:
    """Keep raw provider usage JSON-safe without changing scalar values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    if hasattr(value, "__dict__"):
        return _jsonable(vars(value))
    return str(value)


def _token_count(data: dict, *keys: str) -> int:
    for key in keys:
        value = data.get(key)
        if value is not None:
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                return 0
    return 0


def _details(data: dict, key: str) -> dict:
    value = data.get(key)
    return value if isinstance(value, dict) else {}


@dataclass
class ProviderCall:
    """One metered provider call. ``cost_usd`` stays ``None`` when unreported."""

    kind: str
    model: str
    id: str = field(default_factory=lambda: str(uuid4()))
    provider: str = "openrouter"
    generation_id: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: Decimal | None = None
    cost_status: str = "unknown"
    latency_ms: int | None = None
    status: str = "ok"
    error_code: str | None = None
    raw_usage: dict | None = None
    # True once any accumulated usage object omitted cost; the aggregate is
    # then incomplete and must stay ``unknown`` rather than under-report.
    _cost_incomplete: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.kind not in CALL_KINDS:
            raise ValueError(f"Unknown provider call kind: {self.kind}")

    @property
    def cost_micros(self) -> int | None:
        """Integer micro-USD; never a float and never a fake zero."""
        if self.cost_usd is None or not self.cost_usd.is_finite() or self.cost_usd < 0:
            return None
        try:
            return int((self.cost_usd * _MICROS).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except InvalidOperation:
            return None

    def apply_usage(self, usage: Any, *, accumulate: bool = True) -> None:
        """Apply a response ``usage`` object.

        ``accumulate`` adds batch totals for embeddings. Chat calls replace
        their usage because a stream's final chunk is already cumulative.
        """
        raw = _jsonable(usage)
        if not isinstance(raw, dict) or not raw:
            return
        prompt = _token_count(raw, "prompt_tokens")
        completion = _token_count(raw, "completion_tokens")
        cached = _token_count(
            raw, "cached_tokens", "cache_read_input_tokens",
        ) or _token_count(_details(raw, "prompt_tokens_details"), "cached_tokens")
        reasoning = _token_count(
            raw, "reasoning_tokens",
        ) or _token_count(_details(raw, "completion_tokens_details"), "reasoning_tokens")
        if accumulate:
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.cached_tokens += cached
            self.reasoning_tokens += reasoning
        else:
            self.prompt_tokens = prompt
            self.completion_tokens = completion
            self.cached_tokens = cached
            self.reasoning_tokens = reasoning
        cost = raw.get("cost")
        if cost is None:
            cost = getattr(usage, "cost", None)
        value = None
        if cost is not None:
            try:
                candidate = Decimal(str(cost))
            except (TypeError, ValueError, InvalidOperation):
                candidate = None
            if candidate is not None and candidate.is_finite() and candidate >= 0:
                value = candidate
        if value is not None:
            if accumulate:
                if self._cost_incomplete:
                    self.cost_usd = None
                    self.cost_status = "unknown"
                else:
                    self.cost_usd = (
                        self.cost_usd + value
                        if self.cost_usd is not None
                        else value
                    )
                    self.cost_status = "reported"
            else:
                self.cost_usd = value
                self.cost_status = "reported"
        elif accumulate:
            # An embedding batch omitted cost: the summed total would be
            # understated, so mark the whole logical call unknown.
            self._cost_incomplete = True
            self.cost_usd = None
            self.cost_status = "unknown"
        else:
            # This usage object replaces earlier ones; never keep stale cost.
            self.cost_usd = None
            self.cost_status = "unknown"
        self.raw_usage = raw

    def apply_generation(self, data: dict) -> None:
        """Apply ``GET /generation`` data, replacing estimates with exact cost."""
        if not isinstance(data, dict):
            return
        if data.get("id") and not self.generation_id:
            self.generation_id = str(data["id"])
        self.prompt_tokens = _token_count(
            data, "tokens_prompt", "native_tokens_prompt",
        ) or self.prompt_tokens
        self.completion_tokens = _token_count(
            data, "tokens_completion", "native_tokens_completion",
        ) or self.completion_tokens
        self.cached_tokens = _token_count(
            data, "native_tokens_cached", "tokens_cached", "cached_tokens",
        ) or self.cached_tokens
        self.reasoning_tokens = _token_count(
            data, "native_tokens_reasoning", "tokens_reasoning", "reasoning_tokens",
        ) or self.reasoning_tokens
        total_cost = data.get("total_cost")
        if total_cost is not None:
            try:
                value = Decimal(str(total_cost))
            except (TypeError, ValueError, InvalidOperation):
                value = None
            if value is not None and value.is_finite() and value >= 0:
                self.cost_usd = value
                self.cost_status = "reconciled"
        generation = _jsonable(data)
        if isinstance(generation, dict):
            raw = dict(self.raw_usage or {})
            raw["generation"] = generation
            self.raw_usage = raw

    def mark_error(self, error_code: str = "provider_error") -> None:
        self.status = "error"
        self.error_code = error_code

    def mark_missing_usage(self) -> None:
        """A batch omitted usage entirely; the aggregate cannot be exact."""
        self._cost_incomplete = True
        self.cost_usd = None
        self.cost_status = "unknown"


def update_from_response(call: ProviderCall | None, response: Any, latency_ms: int | None) -> None:
    """Capture id and usage from a non-streaming chat completion response."""
    if call is None:
        return
    call.latency_ms = latency_ms
    response_id = getattr(response, "id", None)
    if response_id:
        call.generation_id = str(response_id)
    call.apply_usage(getattr(response, "usage", None), accumulate=False)


def update_from_chunk(call: ProviderCall | None, chunk: Any) -> None:
    """Capture the id early and the final usage chunk even with empty choices."""
    if call is None:
        return
    chunk_id = getattr(chunk, "id", None)
    if chunk_id and not call.generation_id:
        call.generation_id = str(chunk_id)
    call.apply_usage(getattr(chunk, "usage", None), accumulate=False)
