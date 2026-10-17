"""Redis/Valkey client for ephemeral state only (queue, pub/sub, caches, counters).

Losing everything here is harmless: Postgres holds the durable state.
"""

import json
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as aioredis

from vicky.config import get_settings

_client: aioredis.Redis | None = None


async def connect(url: str | None = None) -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(url or get_settings().redis_url, decode_responses=True)
    return _client


def client() -> aioredis.Redis:
    if _client is None:
        raise RuntimeError("redis is not initialised")
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def get_json(key: str) -> Any:
    raw = await client().get(key)
    return json.loads(raw) if raw else None


async def set_json(key: str, value: Any, ttl_s: int | None = None) -> None:
    await client().set(key, json.dumps(value, default=str), ex=ttl_s)


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


async def add_spend(usd: float) -> float:
    key = f"vicky:spend:{today()}"
    total = await client().incrbyfloat(key, usd)
    await client().expire(key, 48 * 3600)
    return float(total)


async def spend_today() -> float:
    raw = await client().get(f"vicky:spend:{today()}")
    return float(raw or 0.0)
