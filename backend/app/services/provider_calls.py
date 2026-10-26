"""Collect, reconcile and persist provider usage on the Postgres control plane.

Usage recording is best effort: a database or reconciliation failure must never
fail a chat or indexing request. Attribution IDs are accepted only when valid
UUIDs so malformed request headers cannot poison the audit trail.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config
from app.db import session_scope
from app.providers.usage import ProviderCall

logger = logging.getLogger(__name__)


def _uuid_or_none(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class UsageAttribution:
    """Internal ownership for every provider call in one logical request/job."""

    workspace_id: str | None = None
    user_id: str | None = None
    doc_id: str | None = None
    job_id: str | None = None
    request_id: str | None = None


_INSERT_CALL = text(
    """
    INSERT INTO doctrace.provider_calls
        (id, request_id, workspace_id, user_id, doc_id, job_id, kind, provider,
         model, generation_id, prompt_tokens, completion_tokens, cached_tokens,
         reasoning_tokens, cost_micros, cost_status, latency_ms, status,
         error_code, raw_usage)
    VALUES
        (CAST(:id AS uuid), CAST(:request_id AS uuid), CAST(:workspace_id AS uuid),
         CAST(:user_id AS uuid), CAST(:doc_id AS uuid), :job_id, :kind, :provider,
         :model, :generation_id, :prompt_tokens, :completion_tokens, :cached_tokens,
         :reasoning_tokens, :cost_micros, :cost_status, :latency_ms, :status,
         :error_code, CAST(:raw_usage AS jsonb))
    ON CONFLICT (generation_id) WHERE generation_id IS NOT NULL
    DO UPDATE SET
        prompt_tokens = EXCLUDED.prompt_tokens,
        completion_tokens = EXCLUDED.completion_tokens,
        cached_tokens = EXCLUDED.cached_tokens,
        reasoning_tokens = EXCLUDED.reasoning_tokens,
        cost_micros = EXCLUDED.cost_micros,
        cost_status = EXCLUDED.cost_status,
        latency_ms = COALESCE(EXCLUDED.latency_ms, provider_calls.latency_ms),
        status = EXCLUDED.status,
        error_code = EXCLUDED.error_code,
        raw_usage = COALESCE(EXCLUDED.raw_usage, provider_calls.raw_usage)
    """
)


class UsageCollector:
    """One collector per chat/index request; each metered call gets its own row."""

    def __init__(
        self,
        attribution: UsageAttribution,
        config: Optional[AppConfig] = None,
    ):
        self.config = config or get_config()
        self.attribution = attribution
        self.calls: list[ProviderCall] = []
        self._flushed = False

    @property
    def enabled(self) -> bool:
        return bool(self.config.database_url)

    def start(self, kind: str, model: str) -> ProviderCall | None:
        """Start a call; returns None when cost tracking is disabled."""
        if not self.enabled:
            return None
        call = ProviderCall(kind=kind, model=model or "unknown")
        self.calls.append(call)
        return call

    async def flush(self) -> None:
        """Reconcile missing costs, then persist. Safe to call from a finally."""
        if not self.enabled or self._flushed or not self.calls:
            return
        self._flushed = True
        try:
            await self._reconcile_missing()
        except Exception:
            logger.warning("Provider usage reconciliation failed", exc_info=True)
        try:
            await run_in_threadpool(self._store)
        except Exception:
            logger.warning("Provider usage persistence failed", exc_info=True)

    async def _reconcile_missing(self) -> None:
        missing = [call for call in self.calls
                   if call.generation_id and call.cost_usd is None]
        if not missing or not self.config.openrouter_api_key:
            return
        from app.providers.openrouter import fetch_generation

        # Bound total reconciliation latency: every lookup runs concurrently,
        # so N summary calls cannot serialize N network timeouts after the
        # user-visible stream has already finished.
        results = await asyncio.gather(
            *(
                fetch_generation(self.config, call.generation_id or "")
                for call in missing
            ),
            return_exceptions=True,
        )
        for call, result in zip(missing, results):
            if isinstance(result, BaseException):
                logger.warning(
                    "Provider cost reconciliation errored generation=%s",
                    call.generation_id, exc_info=result,
                )
            elif result:
                call.apply_generation(result)

    def _store(self) -> int:
        if not self.calls:
            return 0
        attribution = self.attribution
        rows = [{
            "id": call.id,
            "request_id": _uuid_or_none(attribution.request_id),
            "workspace_id": _uuid_or_none(attribution.workspace_id),
            "user_id": _uuid_or_none(attribution.user_id),
            "doc_id": _uuid_or_none(attribution.doc_id),
            "job_id": attribution.job_id,
            "kind": call.kind,
            "provider": call.provider,
            "model": call.model,
            "generation_id": call.generation_id,
            "prompt_tokens": max(0, call.prompt_tokens),
            "completion_tokens": max(0, call.completion_tokens),
            "cached_tokens": max(0, call.cached_tokens),
            "reasoning_tokens": max(0, call.reasoning_tokens),
            "cost_micros": call.cost_micros,
            "cost_status": call.cost_status,
            "latency_ms": call.latency_ms,
            "status": call.status,
            "error_code": call.error_code,
            "raw_usage": (
                json.dumps(call.raw_usage, ensure_ascii=False, separators=(",", ":"))
                if call.raw_usage is not None else None
            ),
        } for call in self.calls]
        with session_scope(self.config) as session:
            session.execute(_INSERT_CALL, rows)
        return len(rows)
