"""Apply SQL migrations in order under a Postgres advisory lock (idempotent).

Run standalone with `uv run python -m vicky.migrate`; the API also calls `migrate()` at startup.
After the migrations, `ensure_vectors` runs on every start: a database that gains pgvector after
0006_rag.sql was applied (an image switched to pgvector/pgvector, the extension enabled later) gets
its vector columns and indexes then, instead of searching on BM25 only for good.
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

# The vector part of 0006_rag.sql, kept identical (types, dimensions, index names and opclasses). Each
# step checks the catalog first, so a start where everything exists takes no table lock.
VECTORS_SQL = """
do $$ begin
  if not exists (select 1 from pg_extension where extname = 'vector') then
    create extension if not exists vector;
  end if;
exception when others then
  raise notice 'pgvector not available (%); knowledge-base search runs on BM25 only', sqlerrm;
end $$;

do $$ begin
  if exists (select 1 from pg_extension where extname = 'vector') then
    if to_regclass('kb_chunks') is not null and not exists (
        select 1 from information_schema.columns
        where table_schema = current_schema() and table_name = 'kb_chunks' and column_name = 'embedding') then
      alter table kb_chunks add column if not exists embedding halfvec(1024);
    end if;
    if to_regclass('kb_chunks') is not null and to_regclass('kb_chunks_embedding') is null then
      create index if not exists kb_chunks_embedding on kb_chunks using hnsw (embedding halfvec_cosine_ops);
    end if;
    if to_regclass('qa_cache') is not null and not exists (
        select 1 from information_schema.columns
        where table_schema = current_schema() and table_name = 'qa_cache' and column_name = 'embedding') then
      alter table qa_cache add column if not exists embedding halfvec(1024);
    end if;
    if to_regclass('qa_cache') is not null and to_regclass('qa_cache_embedding') is null then
      create index if not exists qa_cache_embedding on qa_cache using hnsw (embedding halfvec_cosine_ops);
    end if;
  end if;
end $$;
"""


async def ensure_vectors(conn: asyncpg.Connection) -> bool:
    """pgvector, and the vector columns and indexes of 0006_rag.sql, whenever the server has the
    extension. Returns whether vectors are available; says so in the log when they aren't."""
    await conn.execute(VECTORS_SQL)
    ok = bool(await conn.fetchval(
        """select exists (select 1 from information_schema.columns
                          where table_schema = current_schema() and table_name = 'kb_chunks'
                            and column_name = 'embedding')"""))
    if not ok:
        log.warning("pgvector is not available on this Postgres: knowledge-base search runs on BM25 only "
                    "(use the pgvector/pgvector:pg17 image, or enable the vector extension)")
    return ok


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
        await ensure_vectors(conn)
        await seed_sources(conn)
    finally:
        await conn.execute("select pg_advisory_unlock($1)", LOCK_KEY)
        await conn.close()
    return applied


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(migrate()))
