"""Rebuild the knowledge-base search index without pressing Fill dashboard (docs/08-RAG.md §Indexing):
after a deploy, after changing EMBED_MODEL, or for the evals. Same build as Fill: a full rebuild from the
vault as it is now, swapped in when ready, the old one discarded. Safe to re-run.

Run from backend/:

    uv run python scripts/kb_reindex.py
"""

import asyncio
import logging

from vik import db, jobs, kv, migrate
from vik.config import get_settings
from vik.kb import index


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    await migrate.migrate()
    await db.connect()
    await kv.connect()
    try:
        b = await index.start_build()
        job = await db.fetchval("select job_id::text from kb_index_builds where id = $1::uuid", b["build_id"])
        await jobs.wait_for([job], timeout_s=3600)
        print(await index.status())
    finally:
        await db.close()
        await kv.close()


if __name__ == "__main__":
    if get_settings().jobs_mode != "inline":
        raise SystemExit("Run with JOBS_MODE=inline: the build runs in this process.")
    asyncio.run(main())
