"""Verify the production limiter against disposable real Redis; no cloud calls.

From backend/: python scripts/verify_rate_limits.py
Requires Docker and requirements-dev.txt. Never connects to the application Redis.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
from threading import Barrier
import time
from uuid import uuid4

from fastapi import HTTPException
from redis import Redis
from redis.exceptions import RedisError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import AppConfig
from app.services.rate_limiter import RateLimiter, rate_limit_key

ROOT = Path(__file__).resolve().parents[1]


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], text=True, capture_output=True, timeout=120)
    if check and result.returncode:
        raise RuntimeError(f"Docker failed: {args}\n{result.stdout}\n{result.stderr}")
    return result.stdout.strip()


def admitted(limiter, owner, action="chat"):
    try:
        asyncio.run(limiter.check(owner, action=action))
        return True
    except HTTPException as exc:
        assert exc.status_code == 429, exc
        assert int(exc.headers["Retry-After"]) >= 1
        return False


def verify(config, connection):
    first, second = RateLimiter(config), RateLimiter(config)
    owner = uuid4().hex
    # Two independent clients/process-equivalent instances share one exact window.
    for i in range(10):
        assert admitted(first if i % 2 else second, owner)
    assert not admitted(first, owner)
    assert connection.zcard(rate_limit_key(owner, "chat")) == 10
    assert admitted(second, uuid4().hex)
    assert admitted(second, owner, "upload")
    assert admitted(second, owner, "index-retry")
    for action, limit in (("upload", 5), ("index-retry", 3)):
        for _ in range(limit - 1):
            assert admitted(first, owner, action)
        assert not admitted(second, owner, action)
    print("PASS: exact quota, independent users/actions, shared clients", flush=True)

    # Start a fresh Python process (no limiter state or .env inherited via get_config).
    child = """
import asyncio, sys
from fastapi import HTTPException
from app.core.config import AppConfig
from app.services.rate_limiter import RateLimiter
try:
    asyncio.run(RateLimiter(AppConfig(redis_url=sys.argv[1])).check(sys.argv[2], action='chat'))
except HTTPException as exc:
    assert exc.status_code == 429
else:
    raise AssertionError('A fresh process reset quota')
"""
    subprocess.run([sys.executable, "-c", child, config.redis_url, owner], cwd=ROOT, check=True, timeout=30)
    print("PASS: quota survives fresh API-side processes", flush=True)

    race_owner = uuid4().hex
    for _ in range(9):
        assert admitted(first, race_owner)
    barrier = Barrier(16)

    def contend(i):
        barrier.wait(timeout=15)
        return admitted(first if i % 2 else second, race_owner)

    with ThreadPoolExecutor(16) as pool:
        results = list(pool.map(contend, range(16)))
    assert sum(results) == 1, results
    assert connection.zcard(rate_limit_key(race_owner, "chat")) == 10
    print("PASS: 16 concurrent requests compete for one remaining slot", flush=True)

    # Seed known ages with Redis's own clock, without sleeping for a whole window.
    aged_owner = uuid4().hex
    key = rate_limit_key(aged_owner, "chat")
    connection.eval("""
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
for i = 1, 10 do redis.call('ZADD', KEYS[1], now - 30000, tostring(i)) end
redis.call('ZADD', KEYS[1], now - 60001, 'expired')
redis.call('PEXPIRE', KEYS[1], 30000)
""", 1, key)
    ttl = connection.pttl(key)
    try:
        asyncio.run(first.check(aged_owner, action="chat"))
    except HTTPException as exc:
        assert exc.status_code == 429
        assert 29 <= int(exc.headers["Retry-After"]) <= 30
    else:
        raise AssertionError("Expected quota rejection")
    assert connection.zcard(key) == 10
    assert 0 < connection.pttl(key) <= ttl

    # Expiring one of the accepted events releases exactly one slot.
    sec, micro = connection.time()
    connection.zadd(key, {"1": sec * 1000 + micro // 1000 - 60001})
    assert admitted(first, aged_owner)
    assert not admitted(second, aged_owner)
    assert connection.zcard(key) == 10
    print("PASS: sliding expiry, Retry-After, denied calls do not renew TTL", flush=True)

    # Lowering a limit must wait for enough events, not merely the oldest one.
    reduced = RateLimiter(AppConfig(redis_url=config.redis_url, rate_limit_chat_requests=1))
    try:
        asyncio.run(reduced.check(aged_owner, action="chat"))
    except HTTPException as exc:
        assert exc.status_code == 429
        assert 59 <= int(exc.headers["Retry-After"]) <= 60
    else:
        raise AssertionError("Lowered quota was not enforced")
    print("PASS: changed quota waits for enough prior admissions to expire", flush=True)

    short = RateLimiter(AppConfig(redis_url=config.redis_url, rate_limit_chat_requests=1,
                                  rate_limit_chat_window_seconds=1))
    short_owner = uuid4().hex
    assert admitted(short, short_owner)
    short_key = rate_limit_key(short_owner, "chat")
    assert 0 < connection.pttl(short_key) <= 1000
    deadline = time.monotonic() + 5
    while connection.exists(short_key) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not connection.exists(short_key)
    assert admitted(short, short_owner)
    print("PASS: idle key expires and quota becomes available again", flush=True)


def main():
    name = f"doctrace-limits-{uuid4().hex[:12]}"
    connection = None
    try:
        docker("run", "-d", "--name", name, "-p", "127.0.0.1::6379", "redis:7.4.8-alpine",
               "redis-server", "--save", "", "--appendonly", "no")
        port = docker("port", name, "6379").rsplit(":", 1)[1]
        config = AppConfig(redis_url=f"redis://127.0.0.1:{port}/0")
        connection = Redis.from_url(config.redis_url, socket_connect_timeout=1, socket_timeout=1)
        deadline = time.monotonic() + 15
        while True:
            try:
                connection.ping()
                break
            except RedisError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)
        verify(config, connection)
        docker("stop", name)
        try:
            asyncio.run(RateLimiter(config).check("outage", action="chat"))
        except HTTPException as exc:
            assert exc.status_code == 503
        else:
            raise AssertionError("Redis outage must fail closed")
        print("PASS: Redis outage is 503, not 429 or admission", flush=True)
    finally:
        if connection:
            connection.close()
        docker("rm", "-f", "-v", name, check=False)


if __name__ == "__main__":
    main()
