"""Redis/Valkey client for ephemeral state only (queue, pub/sub, caches, counters).

Losing everything here is harmless: Postgres holds the durable state (the daily LLM spend is kept in both;
see `add_spend`).
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


# The daily LLM spend is the one counter that must survive Redis: the budget guard reads it before every
# live call. Redis keeps the fast counter; the Postgres `spend` table keeps the same total and is read when
# Redis can't be. Raises only when neither store can be written (or read).

async def _db_add_spend(usd: float) -> float | None:
    from vicky import db

    try:
        return float(await db.pool().fetchval(
            """insert into spend (date, usd, calls) values ($1, $2, 1)
               on conflict (date) do update set usd = spend.usd + excluded.usd, calls = spend.calls + 1
               returning usd""", datetime.now(UTC).date(), usd))
    except Exception:
        return None


async def add_spend(usd: float) -> float:
    durable = await _db_add_spend(usd)
    key = f"vicky:spend:{today()}"
    try:
        total = await client().incrbyfloat(key, usd)
        await client().expire(key, 48 * 3600)
    except Exception:
        if durable is None:
            raise
        return durable
    return float(total)


async def spend_today() -> float:
    try:
        raw = await client().get(f"vicky:spend:{today()}")
        return float(raw or 0.0)
    except Exception:  # Redis down: the durable total
        from vicky import db

        usd = await db.pool().fetchval("select usd from spend where date = $1", datetime.now(UTC).date())
        return float(usd or 0.0)
