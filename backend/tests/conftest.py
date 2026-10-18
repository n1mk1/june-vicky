"""Shared fixtures. API tests run against a throwaway database (`<db>_test`) on the Postgres and
Redis from `docker compose up db kv` (or CI service containers); they skip when neither is up.
"""

import os
import zlib
from urllib.parse import urlparse, urlunparse

import asyncpg
import httpx
import pytest

from vicky.config import get_settings


def _test_dsn() -> tuple[str, str, str]:
    base = os.environ.get("DATABASE_URL", get_settings().database_url)
    u = urlparse(base)
    name = (u.path or "/vicky").lstrip("/") or "vicky"
    test_name = f"{name}_test"
    admin = urlunparse(u._replace(path="/postgres"))
    return admin, urlunparse(u._replace(path=f"/{test_name}")), test_name


@pytest.fixture
def live_llm(monkeypatch):
    """Switch the app to the LLM path with a recorded transport (no network, no real key).

    `live_llm.install(responder)` returns the `Recorder`; spend goes to `live_llm.spend` instead of Redis.
    """
    from types import SimpleNamespace

    from tests.llm_fakes import Recorder, make_llm
    from vicky import kv
    from vicky.llm import client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODE", "auto")
    get_settings.cache_clear()
    state = SimpleNamespace(spend=0.0, recorder=None)

    async def add_spend(usd: float, calls: int = 1) -> float:
        state.spend += usd
        return state.spend

    async def spend_today() -> float:
        return state.spend

    monkeypatch.setattr(kv, "add_spend", add_spend)
    monkeypatch.setattr(kv, "spend_today", spend_today)

    def install(responder):
        state.recorder = Recorder(responder)
        client.set_llm(make_llm(state.recorder))
        return state.recorder

    state.install = install
    yield state
    client.set_llm(None)
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture(scope="session")
async def api_client():
    admin, dsn, name = _test_dsn()
    try:
        conn = await asyncpg.connect(admin, timeout=3)
    except Exception as e:  # no database: skip the API tests, keep the pure ones
        pytest.skip(f"Postgres not reachable ({e}); run `docker compose up -d db kv`")
    await conn.execute(f'drop database if exists "{name}" with (force)')
    await conn.execute(f'create database "{name}"')
    await conn.close()

    os.environ["DATABASE_URL"] = dsn
    os.environ["LLM_MODE"] = "offline"
    redis = urlparse(os.environ.get("REDIS_URL", get_settings().redis_url))
    # Own Redis DB, so rate limits start clean; one per test database, so test runs from different checkouts
    # or sessions (DATABASE_URL=…/vicky_<name>) don't share rate limits, caches or offers.
    rdb = 15 if name == "vicky_test" else 2 + zlib.crc32(name.encode()) % 12
    os.environ["REDIS_URL"] = urlunparse(redis._replace(path=f"/{rdb}"))
    # The whole suite makes more requests a minute than the per-IP limit allows a real client.
    os.environ.setdefault("RATE_LIMIT_PER_MIN", "100000")
    get_settings.cache_clear()
    from vicky import kv
    from vicky.api import app

    async with app.router.lifespan_context(app):
        try:
            await kv.client().flushdb()
        except Exception as e:
            pytest.skip(f"Redis not reachable ({e})")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test/api/v1", timeout=60
        ) as client:
            yield client
