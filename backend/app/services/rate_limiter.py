"""Owner/action sliding windows, shared across API processes; separate from the catalog."""
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config

Action = Literal["upload", "chat", "index-retry"]
PREFIX = "doctrace:ratelimit:v1"

# Redis time avoids API host clock skew. Rejections never add a member or renew TTL.
# Return 0 for admission, otherwise the ceiling of seconds until capacity is free.
SLIDING_WINDOW = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local window = tonumber(ARGV[1]) * 1000
local limit = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
local count = redis.call('ZCARD', KEYS[1])
if count >= limit then
    -- Also handle a configured limit being lowered while old admissions remain.
    local oldest = redis.call('ZRANGE', KEYS[1], count - limit, count - limit, 'WITHSCORES')
    return math.max(1, math.ceil((tonumber(oldest[2]) + window - now) / 1000))
end
redis.call('ZADD', KEYS[1], now, ARGV[3])
redis.call('PEXPIRE', KEYS[1], window)
return 0
"""


def rate_limit_key(user_id: str, action: Action) -> str:
    return f"{PREFIX}:user:{user_id}:{action}"


class RateLimiter:
    def __init__(self, config: AppConfig):
        self.config = config
        self.policies = {
            "upload": (config.rate_limit_upload_requests, config.rate_limit_upload_window_seconds),
            "chat": (config.rate_limit_chat_requests, config.rate_limit_chat_window_seconds),
            "index-retry": (config.rate_limit_index_retry_requests, config.rate_limit_index_retry_window_seconds),
        }

    async def check(self, user_id: str, *, action: Action) -> None:
        limit, window = self.policies[action]
        if not self.config.rate_limit_enabled:
            return

        def consume():
            # A lost EVAL reply may have consumed quota. Never retry or refund it.
            with Redis.from_url(self.config.redis_url, socket_connect_timeout=5, socket_timeout=5,
                                retry=Retry(NoBackoff(), 0)) as connection:
                return int(connection.eval(SLIDING_WINDOW, 1, rate_limit_key(user_id, action),
                                           window, limit, uuid4().hex))

        try:
            wait = await run_in_threadpool(consume)
        except RedisError as exc:
            raise HTTPException(503, "Không thể kiểm tra giới hạn yêu cầu. Vui lòng thử lại sau.") from exc
        if wait:
            raise HTTPException(429, f"Bạn gửi yêu cầu quá nhanh. Vui lòng thử lại sau {wait} giây.",
                                headers={"Retry-After": str(wait)})


def get_rate_limiter() -> RateLimiter:
    return RateLimiter(get_config())
