"""The knowledge-base search index (docs/08-RAG.md §Indexing).

Fill dashboard starts a build: every note is chunked (and embedded, with a Voyage key and pgvector) from its
current content under a new build id, next to the active build. When it is ready, one transaction makes it
active and deletes the old build's chunks and semantic-cache rows; its Redis caches are then dropped and every
process throws away its BM25 index. A failed or cancelled build deletes only its own chunks, so the old build
keeps serving. Imports and edits never touch the index: search shows the vault as of the last Fill.

The one shortcut: a chunk whose embedded text and model are byte-identical to one in the build it replaces
copies that vector instead of calling Voyage (`RAG_REUSE_EMBEDDINGS`).
"""

import asyncio
import hashlib
import logging
from typing import Any

from vicky import db, jobs, kv
from vicky.config import get_settings
from vicky.kb import voyage
from vicky.kb.chunk import chunk_note, embed_sha, embed_text
from vicky.realtime import publish

log = logging.getLogger(__name__)
SETTLE_TIMEOUT_S = 600
STUCK_AFTER_S = 30 * 60
LOCK_KEY = 7_331_006  # serializes starting and activating builds (two Fills at once)  # a build still "building" after this long has lost its process
INSERT_BATCH = 500
_has_vector: bool | None = None


class Cancelled(Exception):
    pass


async def has_vector() -> bool:
    """True when kb_chunks has an embedding column (pgvector was available to the migration)."""
    global _has_vector
    if _has_vector is None:
        _has_vector = bool(await db.fetchval(
            "select exists (select 1 from information_schema.columns where table_name = 'kb_chunks' "
            "and column_name = 'embedding')"))
    return _has_vector


def vectors_on() -> bool:
    return voyage.enabled()


async def kb_version() -> int:
    return int(await db.fetchval("select version from kb_meta where id") or 0)


async def active_build() -> dict | None:
    return await db.fetchrow(
        "select id::text, status, notes, chunks, embedded, reused, embed_model, started_at, finished_at, created_at "
        "from kb_index_builds where status = 'active'")


async def active_build_id() -> str | None:
    try:
        return await db.fetchval("select id::text from kb_index_builds where status = 'active'")
    except Exception as e:  # tables not migrated yet, or no database: no index
        log.info("no knowledge-base index: %s", e)
        return None


async def start_build(engagement_id: str | None = None) -> dict:
    """Queue a full rebuild. A build already queued or running is cancelled: the new one starts from the
    vault as it is now."""
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute("select pg_advisory_xact_lock($1)", LOCK_KEY)
        await conn.execute("update kb_index_builds set status = 'cancelled', finished_at = now() "
                           "where status in ('queued', 'building')")
        bid = await conn.fetchval("insert into kb_index_builds (engagement_id) values ($1) returning id::text",
                                  engagement_id)
    job_id = await jobs.enqueue("kb_index", {"build_id": bid})
    await db.execute("update kb_index_builds set job_id = $2 where id = $1::uuid", bid, job_id)
    return {"build_id": bid, "status": "queued"}


async def _status(bid: str) -> str | None:
    return await db.fetchval("select status from kb_index_builds where id = $1::uuid", bid)


async def _check(bid: str) -> None:
    if await _status(bid) != "building":
        raise Cancelled(bid)


async def _wait_for_vault(bid: str) -> None:
    """The vault must be settled: wait for imports and organize passes still running."""
    deadline = asyncio.get_event_loop().time() + SETTLE_TIMEOUT_S
    while asyncio.get_event_loop().time() < deadline:
        # Only live work counts: an import left "running" by a process that died is never coming back.
        busy = await db.fetchval("select count(*) from jobs where kind in ('kb_ingest', 'kb_organize') "
                                 "and status in ('queued', 'running') "
                                 "and coalesce(started_at, enqueued_at) > now() - make_interval(secs => $1)",
                                 jobs.STALE_AFTER_S)
        if not busy:
            return
        if await _status(bid) not in ("queued", "building"):
            raise Cancelled(bid)
        await asyncio.sleep(0.5)
    log.warning("kb index %s: imports still running after %ss; indexing the vault as it is", bid, SETTLE_TIMEOUT_S)


async def build(bid: str) -> dict[str, Any]:
    """The `kb_index` job."""
    s = get_settings()
    try:
        await _wait_for_vault(bid)
        started = await db.fetchval("update kb_index_builds set status = 'building', started_at = now() "
                                    "where id = $1::uuid and status = 'queued' returning id", bid)
        if not started:
            raise Cancelled(bid)
        notes = await db.fetch("select id::text, path, title, kind, format, tags, summary, content, "
                               "md5(content) as md5 from kb_notes order by path")
        rows: list[dict] = []
        for n in notes:
            for c in chunk_note(n["content"], n["format"]):
                rows.append({"note": n, "chunk": c, "sha": embed_sha(n, c, s.embed_model), "vec": None})
        embedded = reused = 0
        model = None
        if await has_vector() and vectors_on() and rows:
            model = s.embed_model
            if s.rag_reuse_embeddings:
                old = await active_build_id()
                if old:
                    found = await db.fetch(
                        "select distinct on (sha256) sha256, embedding::text as v from kb_chunks "
                        "where build_id = $1::uuid and embed_model = $2 and embedding is not null "
                        "and sha256 = any($3::text[])", old, model, [r["sha"] for r in rows])
                    by_sha = {f["sha256"]: f["v"] for f in found}
                    for r in rows:
                        if r["sha"] in by_sha:
                            r["vec"] = by_sha[r["sha"]]
                            reused += 1
            todo = [r for r in rows if r["vec"] is None]
            for i in range(0, len(todo), voyage.BATCH):
                await _check(bid)
                part = todo[i:i + voyage.BATCH]
                vecs = await voyage.embed([embed_text(r["note"], r["chunk"]) for r in part], "document")
                for r, v in zip(part, vecs, strict=True):
                    r["vec"] = voyage.to_pg(v)
                embedded += len(part)
        await _check(bid)
        await _insert(bid, rows, model)
        old = await _activate(bid, notes=len(notes), chunks=len(rows), embedded=embedded, reused=reused, model=model)
        await _discard_caches(old)
        try:  # warm this process's BM25 index now, so the first search after a Fill doesn't wait for it
            from vicky.kb import rag

            await rag._index(bid)
        except Exception as e:
            log.info("could not warm the search index: %s", e)
        await publish("kb", "kb.index.ready", {"build_id": bid, "chunks": len(rows)})
        log.info("kb index %s active: %d notes, %d chunks (%d embedded, %d reused)", bid, len(notes), len(rows),
                 embedded, reused)
        return {"build_id": bid, "notes": len(notes), "chunks": len(rows), "embedded": embedded, "reused": reused}
    except Cancelled:
        await db.execute("delete from kb_chunks where build_id = $1::uuid", bid)
        return {"build_id": bid, "cancelled": True}
    except Exception as e:
        log.exception("kb index %s failed", bid)
        await db.execute("delete from kb_chunks where build_id = $1::uuid", bid)
        await db.execute("update kb_index_builds set status = 'failed', error = $2, finished_at = now() "
                         "where id = $1::uuid and status in ('queued', 'building')", bid, str(e)[:1000])
        await publish("kb", "kb.index.failed", {"build_id": bid, "error": str(e)[:300]})
        raise


async def _insert(bid: str, rows: list[dict], model: str | None) -> None:
    with_vec = await has_vector()
    cols = ("build_id, note_id, note_md5, ord, heading, start_char, end_char, text, text_sha256, sha256, "
            "embed_model")
    if with_vec:
        sql = (f"insert into kb_chunks ({cols}, embedding) values "
               "($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::halfvec)")
    else:
        sql = f"insert into kb_chunks ({cols}) values ($1::uuid, $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10, $11)"
    async with db.pool().acquire() as conn:
        for i in range(0, len(rows), INSERT_BATCH):
            args = []
            for r in rows[i:i + INSERT_BATCH]:
                c, n = r["chunk"], r["note"]
                a = [bid, n["id"], n["md5"], c.ord, c.heading[:300], c.start, c.end, c.text,
                     hashlib.sha256(c.text.encode()).hexdigest(), r["sha"], model if r["vec"] else None]
                if with_vec:
                    a.append(r["vec"])
                args.append(a)
            await conn.executemany(sql, args)


async def _activate(bid: str, **counts: Any) -> str | None:
    """Swap: the new build becomes active and the old one's chunks and semantic-cache rows are deleted.
    Returns the old build id."""
    async with db.pool().acquire() as conn, conn.transaction():
        await conn.execute("select pg_advisory_xact_lock($1)", LOCK_KEY)
        st = await conn.fetchval("select status from kb_index_builds where id = $1::uuid for update", bid)
        if st != "building":
            raise Cancelled(bid)
        old = await conn.fetchval("select id::text from kb_index_builds where status = 'active' for update")
        if old:
            await conn.execute("update kb_index_builds set status = 'superseded' where id = $1::uuid", old)
            await conn.execute("delete from kb_chunks where build_id = $1::uuid", old)
            await conn.execute("delete from qa_cache where build_id = $1::uuid", old)
        await conn.execute(
            "update kb_index_builds set status = 'active', finished_at = now(), notes = $2, chunks = $3, "
            "embedded = $4, reused = $5, embed_model = $6, error = null where id = $1::uuid",
            bid, counts["notes"], counts["chunks"], counts["embedded"], counts["reused"], counts["model"])
    return old


async def _discard_caches(old: str | None) -> None:
    """Drop every Redis entry of the old build (retrieval, rerank, answers). The query-embedding cache
    stays: it encodes questions, not the vault."""
    if not old:
        return
    try:
        r = kv.client()
        async for key in r.scan_iter(match=f"rag:*:{old}:*", count=500):
            await r.unlink(key)
    except Exception as e:  # caches expire on their own; a missed delete is never served (the key names the build)
        log.info("could not drop caches of build %s: %s", old, e)


async def _reap() -> None:
    """A queued or building build whose job ended, vanished or has run for too long has lost its process
    (an inline job dies with a restart): mark it failed so the status says so and Retry is offered."""
    lost = await db.fetch(
        """update kb_index_builds b set status = 'failed', finished_at = now(),
                  error = 'The build stopped before it finished. Press Retry or Fill dashboard again.'
           where b.status in ('queued', 'building') and (
                 exists (select 1 from jobs j where j.id = b.job_id and j.status in ('failed', 'stale', 'done'))
              or (b.job_id is null and b.created_at < now() - interval '2 minutes')
              or coalesce(b.started_at, b.created_at) < now() - make_interval(secs => $1))
           returning b.id::text""", STUCK_AFTER_S)
    for r in lost:
        await db.execute("delete from kb_chunks where build_id = $1::uuid", r["id"])


async def status() -> dict:
    """For GET /kb/status: the latest build, the active one, and how many notes changed since it."""
    await _reap()
    latest = await db.fetchrow(
        "select id::text, status, error, created_at, started_at, finished_at from kb_index_builds "
        "order by created_at desc limit 1")
    act = await active_build()
    changed = indexed = 0
    if act:
        indexed = int(await db.fetchval(
            "select count(distinct c.note_id) from kb_chunks c join kb_notes n on n.id = c.note_id "
            "where c.build_id = $1::uuid and n.kind <> 'hub'", act["id"]) or 0)
        # Notes written since the build read the vault (cheap: kb_notes_updated index). Retrieval itself still
        # compares md5s, so a note touched without a content change is never wrongly skipped.
        changed = int(await db.fetchval(
            "select count(*) from kb_notes where kind <> 'hub' and updated_at > $1 and length(btrim(content)) > 0",
            act["started_at"] or act["created_at"]) or 0)
    state = "none"
    if latest:
        state = {"queued": "building", "building": "building", "active": "ready", "superseded": "ready",
                 "failed": "failed", "cancelled": "building" if not act else "ready"}[latest["status"]]
    return {"status": state, "build_id": (act or {}).get("id"), "latest": latest,
            "built_at": (act or {}).get("finished_at"), "notes": indexed,
            "chunks": (act or {}).get("chunks", 0), "vectors": bool(act and act.get("embed_model")),
            "changed_since": changed}
