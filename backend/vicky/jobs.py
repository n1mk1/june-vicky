"""Background jobs. A `jobs` row is the record; Redis only carries the queue.

JOBS_MODE=inline runs handlers inside the API process (free tier). JOBS_MODE=worker hands them to
the arq worker (`uv run arq vicky.jobs.WorkerSettings`). Same handlers either way.
"""

import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from vicky import db, kv
from vicky.config import get_settings
from vicky.realtime import publish

log = logging.getLogger(__name__)
Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]
HANDLERS: dict[str, Handler] = {}
STALE_AFTER_S = 15 * 60
_inline_tasks: set[asyncio.Task] = set()


def job(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn
    return deco


def _register_handlers() -> None:
    # Import modules that define @job handlers. A broken handler module must not wedge the queue.
    try:
        import vicky.services.jobs_handlers  # noqa: F401
    except Exception as e:
        log.error("could not load job handlers: %s", e)


async def enqueue(kind: str, payload: dict[str, Any], engagement_id: str | None = None,
                  session_id: str | None = None) -> str:
    job_id = await db.fetchval(
        "insert into jobs (kind, payload, engagement_id, session_id) values ($1, $2, $3, $4) returning id::text",
        kind, payload, engagement_id, session_id,
    )
    if get_settings().jobs_mode == "worker":
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(_redis_settings(RedisSettings))
        await pool.enqueue_job("run_job_arq", job_id)
        await pool.aclose()
    else:
        task = asyncio.create_task(run_job(job_id))
        _inline_tasks.add(task)
        task.add_done_callback(_inline_tasks.discard)
    return job_id


async def run_job(job_id: str) -> dict | None:
    _register_handlers()
    row = await db.fetchrow("update jobs set status='running', started_at=now(), attempts=attempts+1 "
                            "where id=$1 and status in ('queued','stale','failed') returning *", job_id)
    if row is None:
        return None
    channel = (f"session:{row['session_id']}" if row["session_id"] else
               f"engagement:{row['engagement_id']}" if row["engagement_id"] else "kb")
    await publish(channel, "job.status", {"job_id": job_id, "kind": row["kind"], "status": "running"})
    handler = HANDLERS.get(row["kind"])
    try:
        if handler is None:
            raise RuntimeError(f"no handler for job kind {row['kind']}")
        result = await handler({**row["payload"], "_job_id": job_id, "_engagement_id": str(row["engagement_id"] or ""),
                                "_session_id": str(row["session_id"] or "")})
        await db.execute("update jobs set status='done', result=$2, finished_at=now() where id=$1", job_id, result or {})
        await publish(channel, "job.status", {"job_id": job_id, "kind": row["kind"], "status": "done"})
        return result
    except Exception as e:
        log.error("job %s failed: %s\n%s", job_id, e, traceback.format_exc())
        await db.execute("update jobs set status='failed', error=$2, finished_at=now() where id=$1", job_id, str(e)[:2000])
        await publish(channel, "job.status", {"job_id": job_id, "kind": row["kind"], "status": "failed", "error": str(e)[:300]})
        return None


async def wait_for(job_ids: list[str], timeout_s: float = 300) -> None:
    """Wait for jobs to settle (used by session start when memos must finish first)."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        rows = await db.fetch("select status from jobs where id = any($1::uuid[])", job_ids)
        if all(r["status"] in ("done", "failed", "stale") for r in rows):
            return
        await asyncio.sleep(0.25)


async def sweep_stale() -> int:
    res = await db.execute(
        "update jobs set status='stale' where status='queued' and enqueued_at < now() - make_interval(secs => $1)",
        STALE_AFTER_S)
    return int(res.split()[-1]) if res else 0


async def retry(job_id: str) -> None:
    await db.execute("update jobs set status='queued', error=null, enqueued_at=now() where id=$1", job_id)
    if get_settings().jobs_mode == "worker":
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(_redis_settings(RedisSettings))
        await pool.enqueue_job("run_job_arq", job_id)
        await pool.aclose()
    else:
        task = asyncio.create_task(run_job(job_id))
        _inline_tasks.add(task)
        task.add_done_callback(_inline_tasks.discard)


def _redis_settings(cls):
    u = urlparse(get_settings().redis_url)
    return cls(host=u.hostname or "localhost", port=u.port or 6379, password=u.password, username=u.username,
               ssl=u.scheme == "rediss", database=int((u.path or "/0").lstrip("/") or 0))


# ---------------------------------------------------------------- arq worker

async def run_job_arq(ctx: dict, job_id: str) -> dict | None:
    return await run_job(job_id)


async def _startup(ctx: dict) -> None:
    logging.basicConfig(level=logging.INFO)
    await db.connect()
    await kv.connect()


async def _shutdown(ctx: dict) -> None:
    await db.close()
    await kv.close()


def _worker_redis():
    from arq.connections import RedisSettings

    return _redis_settings(RedisSettings)


class WorkerSettings:
    functions = [run_job_arq]
    on_startup = _startup
    on_shutdown = _shutdown
    max_jobs = 8
    job_timeout = 600
    redis_settings = _worker_redis()
