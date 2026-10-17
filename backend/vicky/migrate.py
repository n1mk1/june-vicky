"""Apply SQL migrations in order under a Postgres advisory lock (idempotent).

Run standalone with `uv run python -m vicky.migrate`; the API also calls `migrate()` at startup.
"""

import asyncio
import logging
from pathlib import Path

import asyncpg
import yaml

from vicky import BACKEND_DIR, DATA_DIR
from vicky.config import get_settings

log = logging.getLogger(__name__)
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
LOCK_KEY = 7_331_001


async def seed_sources(conn: asyncpg.Connection) -> int:
    path = DATA_DIR / "sources.yaml"
    if not path.exists():
        return 0
    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(entries, dict):
        entries = entries.get("sources", [])
    for e in entries:
        await conn.execute(
            """insert into sources (id, publisher, title, claim, url, as_of, business_model, stage, topic, verified)
               values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               on conflict (id) do update set publisher=excluded.publisher, title=excluded.title,
                 claim=excluded.claim, url=excluded.url, as_of=excluded.as_of,
                 business_model=excluded.business_model, stage=excluded.stage,
                 topic=excluded.topic, verified=excluded.verified""",
            e["id"], e.get("publisher", ""), e.get("title"), e.get("claim", ""), e.get("url"),
            str(e.get("as_of") or ""), list(e.get("business_model") or []), list(e.get("stage") or []),
            list(e.get("topic") or []), bool(e.get("verified", False)),
        )
    return len(entries)


async def migrate(dsn: str | None = None) -> list[str]:
    conn = await asyncpg.connect(dsn or get_settings().database_url)
    applied: list[str] = []
    try:
        await conn.execute("select pg_advisory_lock($1)", LOCK_KEY)
        await conn.execute(
            "create table if not exists schema_migrations (name text primary key, applied_at timestamptz default now())"
        )
        done = {r["name"] for r in await conn.fetch("select name from schema_migrations")}
        for path in sorted(Path(MIGRATIONS_DIR).glob("*.sql")):
            if path.name in done:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute("insert into schema_migrations (name) values ($1)", path.name)
            applied.append(path.name)
            log.info("applied migration %s", path.name)
        await seed_sources(conn)
    finally:
        await conn.execute("select pg_advisory_unlock($1)", LOCK_KEY)
        await conn.close()
    return applied


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(migrate()))
