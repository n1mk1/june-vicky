"""Background jobs. A `jobs` row is the record; Redis only carries the queue.

JOBS_MODE=inline runs handlers inside the API process (free tier). JOBS_MODE=worker hands them to
the arq worker (`uv run arq vik.jobs.WorkerSettings`). Same handlers either way.

A run that is cancelled (arq's job timeout, a redeploy, a sleeping free-tier instance) is marked
`failed` with error `interrupted`. If the process dies before it can say so, the sweeper marks the
row `stale` once it has been `running` longer than any job may run. Only failed or stale jobs retry.

Inline runs share INLINE_CONCURRENCY slots, fewer than the DB pool's connections, so a burst of jobs
leaves connections for requests; a job stays `queued` until a slot frees. A job that waits on other jobs
gives its slot up while it waits (`slot_released`), so waiting can't wedge the queue.
"""

import asyncio
import contextlib
import logging
import traceback
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from vik import db, kv
from vik.config import get_settings
from vik.realtime import publish

log = logging.getLogger(__name__)
Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any] | None]]
HANDLERS: dict[str, Handler] = {}
STALE_AFTER_S = 15 * 60
JOB_TIMEOUT_S = 600  # arq's job_timeout; an inline run has no timeout but gets the same sweep
RUNNING_STALE_AFTER_S = JOB_TIMEOUT_S + 5 * 60
INTERRUPTED = "interrupted"
RETRYABLE = ("failed", "stale")
_inline_tasks: set[asyncio.Task] = set()
INLINE_CONCURRENCY = 6  # the DB pool holds 10; the rest stay free for requests
_inline_slots: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


@dataclass
class _Slot:
    held: bool = False


_slot: ContextVar[_Slot | None] = ContextVar("vik_job_slot", default=None)


class RetryRefused(Exception):
    """The job exists but isn't failed or stale; `status` says what it is."""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


def job(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


def _register_handlers() -> None:
    # Import modules that define @job handlers. A broken handler module must not wedge the queue.
    try:
        import vik.services.jobs_handlers  # noqa: F401
    except Exception as e:
        log.error("could not load job handlers: %s", e)


async def enqueue(
    kind: str, payload: dict[str, Any], engagement_id: str | None = None, session_id: str | None = None
) -> str:
    job_id = await db.fetchval(
        "insert into jobs (kind, payload, engagement_id, session_id) values ($1, $2, $3, $4) returning id::text",
        kind,
        payload,
        engagement_id,
        session_id,
    )
    if get_settings().jobs_mode == "worker":
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(_redis_settings(RedisSettings))
        await pool.enqueue_job("run_job_arq", job_id)
        await pool.aclose()
    else:
        _start_inline(job_id)
    return job_id


def _start_inline(job_id: str) -> None:
    task = asyncio.create_task(_run_inline(job_id))
    _inline_tasks.add(task)
    task.add_done_callback(_inline_tasks.discard)


def _slots() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _inline_slots.get(loop)
    if sem is None:
        for old in [lp for lp in _inline_slots if lp.is_closed()]:
            del _inline_slots[old]
        sem = _inline_slots[loop] = asyncio.Semaphore(INLINE_CONCURRENCY)
    return sem


async def _run_inline(job_id: str) -> dict | None:
    sem = _slots()
    slot = _Slot()
    _slot.set(slot)  # this task's own context: the handler (and tasks it starts) see the slot
    await sem.acquire()
    slot.held = True
    try:
        return await run_job(job_id)
    finally:
        if slot.held:
            slot.held = False
            sem.release()


@contextlib.asynccontextmanager
async def slot_released() -> AsyncIterator[None]:
    """Inside an inline job: give the job's slot back while it waits on other jobs, and take one again
    before carrying on. Elsewhere (a request, the arq worker) it does nothing."""
    slot = _slot.get()
    if slot is None or not slot.held:
        yield
        return
    sem = _slots()
    slot.held = False
    sem.release()
    try:
        yield
    finally:
        await sem.acquire()  # if this is cancelled the slot stays released, and `held` says so
        slot.held = True


async def run_job(job_id: str) -> dict | None:
    _register_handlers()
    row = await db.fetchrow(
        "update jobs set status='running', started_at=now(), attempts=attempts+1 "
        "where id=$1 and status in ('queued','stale','failed') returning *",
        job_id,
    )
    if row is None:
        return None
    channel = (
        f"session:{row['session_id']}"
        if row["session_id"]
        else f"engagement:{row['engagement_id']}"
        if row["engagement_id"]
        else "kb"
    )
    await publish(channel, "job.status", {"job_id": job_id, "kind": row["kind"], "status": "running"})
    handler = HANDLERS.get(row["kind"])
    try:
        if handler is None:
            raise RuntimeError(f"no handler for job kind {row['kind']}")
        result = await handler(
            {
                **row["payload"],
                "_job_id": job_id,
                "_engagement_id": str(row["engagement_id"] or ""),
                "_session_id": str(row["session_id"] or ""),
            }
        )
        await db.execute(
            "update jobs set status='done', result=$2, finished_at=now() where id=$1", job_id, result or {}
        )
        await publish(channel, "job.status", {"job_id": job_id, "kind": row["kind"], "status": "done"})
        return result
    except Exception as e:
        log.error("job %s failed: %s\n%s", job_id, e, traceback.format_exc())
        await db.execute(
            "update jobs set status='failed', error=$2, finished_at=now() where id=$1", job_id, str(e)[:2000]
        )
        await publish(
            channel,
            "job.status",
            {"job_id": job_id, "kind": row["kind"], "status": "failed", "error": str(e)[:300]},
        )
        return None
    except BaseException:
        # Cancelled (arq's job timeout, shutdown, a redeploy): record it so the row doesn't stay
        # `running` for good, then let the cancellation carry on.
        log.warning("job %s (%s) interrupted", job_id, row["kind"])
        with contextlib.suppress(Exception):
            await db.execute(
                "update jobs set status='failed', error=$2, finished_at=now() where id=$1 and status='running'",
                job_id,
                INTERRUPTED,
            )
            await publish(
                channel,
                "job.status",
                {"job_id": job_id, "kind": row["kind"], "status": "failed", "error": INTERRUPTED},
            )
        raise


async def wait_for(job_ids: list[str], timeout_s: float = 300) -> None:
    """Wait for jobs to settle (used by session start when memos must finish first). Called from inside
    an inline job, the job's slot is free while it waits."""
    async with slot_released():
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            rows = await db.fetch("select status from jobs where id = any($1::uuid[])", job_ids)
            if all(r["status"] in ("done", "failed", "stale") for r in rows):
                return
            await asyncio.sleep(0.25)


async def sweep_stale() -> int:
    """Queued jobs nobody picked up, and running jobs whose process died without saying so, become
    `stale` (retryable)."""
    res = await db.execute(
        """update jobs set status='stale',
                  error=case when status='running' then 'no longer running (the process stopped)' else error end
           where (status='queued' and enqueued_at < now() - make_interval(secs => $1))
              or (status='running' and coalesce(started_at, enqueued_at) < now() - make_interval(secs => $2))""",
        STALE_AFTER_S,
        RUNNING_STALE_AFTER_S,
    )
    return int(res.split()[-1]) if res else 0


async def retry(job_id: str) -> None:
    """Re-queue a failed or stale job. KeyError when there is no such job; RetryRefused when it is
    queued, running or done (re-running those would duplicate work)."""
    try:
        uuid.UUID(str(job_id))
    except ValueError as e:
        raise KeyError(job_id) from e
    row = await db.fetchrow(
        """update jobs set status='queued', error=null, enqueued_at=now(), started_at=null, finished_at=null
           where id=$1 and status = any($2::job_status[]) returning id""",
        job_id,
        list(RETRYABLE),
    )
    if row is None:
        status = await db.fetchval("select status::text from jobs where id=$1", job_id)
        if status is None:
            raise KeyError(job_id)
        raise RetryRefused(status)
    if get_settings().jobs_mode == "worker":
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(_redis_settings(RedisSettings))
        await pool.enqueue_job("run_job_arq", job_id)
        await pool.aclose()
    else:
        _start_inline(job_id)


async def shutdown(timeout_s: float = 10.0) -> None:
    """Cancel the inline jobs still running (each marks its row `interrupted`) and wait for them."""
    tasks = [t for t in _inline_tasks if not t.done()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=timeout_s)
    _inline_tasks.difference_update(t for t in tasks if t.done())


def _redis_settings(cls):
    u = urlparse(get_settings().redis_url)
    return cls(
        host=u.hostname or "localhost",
        port=u.port or 6379,
        password=u.password,
        username=u.username,
        ssl=u.scheme == "rediss",
        database=int((u.path or "/0").lstrip("/") or 0),
    )


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
    job_timeout = JOB_TIMEOUT_S
    redis_settings = _worker_redis()
