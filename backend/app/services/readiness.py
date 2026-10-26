"""Dependency readiness probes for /ready; liveness stays at /health."""
from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Optional

from redis import Redis
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config
from app.db import check_database

logger = logging.getLogger(__name__)


def _ping_redis(config: AppConfig) -> None:
    with Redis.from_url(
        config.redis_url, socket_connect_timeout=2, socket_timeout=2,
    ) as connection:
        connection.ping()


async def check_redis(config: Optional[AppConfig] = None) -> dict:
    config = config or get_config()
    started = perf_counter()
    try:
        await run_in_threadpool(_ping_redis, config)
    except Exception:
        logger.warning("Redis readiness probe failed", exc_info=True)
        return {
            "status": "error",
            "latency_ms": round((perf_counter() - started) * 1000),
            "error_code": "redis_unavailable",
        }
    return {"status": "ok", "latency_ms": round((perf_counter() - started) * 1000)}


async def readiness(config: Optional[AppConfig] = None) -> tuple[str, dict]:
    """Return (status, checks). A configured but unreachable dependency fails."""
    config = config or get_config()
    redis_check, database_check = await asyncio.gather(
        check_redis(config), check_database(config),
    )
    checks = {"redis": redis_check, "database": database_check}
    degraded = any(check.get("status") == "error" for check in checks.values())
    return ("degraded" if degraded else "ok"), checks
