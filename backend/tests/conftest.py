"""Shared fixtures. API tests run against a throwaway database (`<db>_test`) on the Postgres and
Redis from `docker compose up db kv` (or CI service containers); they skip when neither is up.
"""

import os
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
    os.environ["REDIS_URL"] = urlunparse(redis._replace(path="/15"))  # own Redis DB: rate limits start clean
    get_settings.cache_clear()
    from vicky import kv
    from vicky.api import app

    async with app.router.lifespan_context(app):
        try:
            await kv.client().flushdb()
        except Exception as e:
            pytest.skip(f"Redis not reachable ({e})")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=60) as client:
            yield client
