"""REST surface for the knowledge base (docs/API.md §Knowledge base). Mounted under /api/v1/kb behind
the access gate."""

import re
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from vicky import db, jobs, llm
from vicky.config import get_settings
from vicky.kb import autofill, ingest, ocr, store
from vicky.kb.store import NoteConflict, NoteInvalid, NoteNotFound

router = APIRouter(prefix="/kb")
MAX_IMPORT_FILES = 200


def _http(e: Exception) -> HTTPException:
    if isinstance(e, NoteNotFound):
        return HTTPException(404, "That note doesn't exist any more.")
    if isinstance(e, NoteConflict):
        return HTTPException(409, str(e))
    return HTTPException(422, str(e))


class NoteIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    path: str | None = Field(default=None, max_length=400)
    content: str | None = None
    format: str | None = None
    tags: list[str] | None = None
    summary: str | None = Field(default=None, max_length=1000)
    links: list[str] | None = None
    version: int | None = None


@router.get("/status")
async def status() -> dict:
    counts = await db.fetchrow(
        """select count(*) filter (where kind <> 'hub') as notes, count(*) filter (where kind = 'hub') as hubs,
                  count(*) filter (where kind = 'table') as tables, count(*) filter (where kind = 'document') as documents,
                  count(*) filter (where organized_at is null) as unorganized, max(organized_at) as organized_at
           from kb_notes"""
    )
    files = await db.fetchrow(
        "select count(*) as files, count(*) filter (where status = 'failed') as failed, "
        "coalesce(sum(size), 0)::bigint as bytes from kb_files"
    )
    # A job counts as running only while it is live: one left "running" or "queued" by a process that died is
    # never coming back (the same rule the index build uses to wait for the vault).
    recent = await db.fetch(
        """select id::text, kind::text, status::text, error, result, enqueued_at, finished_at,
                  status in ('queued', 'running')
                    and coalesce(started_at, enqueued_at) > now() - make_interval(secs => $1) as live
           from jobs where kind in ('kb_ingest', 'kb_organize') order by enqueued_at desc limit 8""",
        jobs.STALE_AFTER_S,
    )
    running = any(j.pop("live") for j in recent)
    failures = await db.fetch(
        "select id::text, filename, error from kb_files where status = 'failed' "
        "order by created_at desc limit 20"
    )
    from vicky.kb import index

    try:
        idx = await index.status()
    except Exception as e:  # no index tables yet
        idx = {"status": "none", "error": str(e)[:200]}
    try:
        from vicky import kv

        raw = await kv.client().hgetall(f"rag:stats:{kv.today().replace('-', '')}")
        stats = {k: int(v) for k, v in raw.items()}
    except Exception:
        stats = {}
    asked = sum(
        stats.get(k, 0) for k in ("path_chunks", "path_recover", "path_figures", "path_offline", "offer")
    )
    rag_out = {
        **stats,
        "offer_rate": round(stats.get("offer", 0) / asked, 3) if asked else None,
        "accept_rate": round(stats.get("offer_accepted", 0) / stats["offer"], 3)
        if stats.get("offer")
        else None,
    }
    return {
        **counts,
        **files,
        "jobs": recent,
        "running": running,
        "failures": failures,
        "ocr": ocr.available(),
        "llm": llm.enabled(),
        "index": idx,
        "rag": rag_out,
    }


@router.post("/index")
async def rebuild_index() -> dict:
    """Rebuild the search index from the vault as it is now (Retry after a failed build; Fill dashboard
    does the same)."""
    from vicky.kb import index

    if not await db.fetchval("select exists (select 1 from kb_notes)"):
        raise HTTPException(422, "The knowledge base is empty. Import some files first.")
    return await index.start_build()


@router.get("/notes")
async def notes() -> list[dict]:
    return await store.list_notes()


@router.get("/notes/{nid}")
async def note(nid: str) -> dict:
    try:
        return await store.get_note(nid)
    except NoteNotFound as e:
        raise _http(e) from e


@router.post("/notes")
async def note_create(body: NoteIn) -> dict:
    try:
        return await store.create_note(body.model_dump(exclude_none=True))
    except (NoteInvalid, NoteNotFound) as e:
        raise _http(e) from e


@router.put("/notes/{nid}")
async def note_update(nid: str, body: NoteIn) -> dict:
    try:
        return await store.update_note(nid, body.model_dump(exclude_none=True))
    except (NoteInvalid, NoteNotFound, NoteConflict) as e:
        raise _http(e) from e


@router.delete("/notes/{nid}")
async def note_delete(nid: str) -> dict:
    try:
        await store.delete_note(nid)
    except NoteNotFound as e:
        raise _http(e) from e
    return {"ok": True}


@router.get("/graph")
async def graph() -> dict:
    return await store.graph()


@router.get("/search")
async def search(q: str = "", limit: int = 20) -> list[dict]:
    return await store.search(q, min(max(limit, 1), 50))


@router.post("/import")
async def import_files(files: list[UploadFile] = File(...)) -> dict:
    s = get_settings()
    limit, total_cap = s.kb_upload_max_bytes, s.kb_unzip_max_bytes
    uploads = []
    total = 0
    for f in files[:MAX_IMPORT_FILES]:
        data = await f.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"{f.filename} is over {limit // (1024 * 1024)} MB")
        total += len(data)
        if total > total_cap:
            raise HTTPException(
                413,
                f"One import can bring in at most {total_cap // (1024 * 1024)} MB. "
                "Import the files in smaller batches.",
            )
        uploads.append((f.filename or "upload", data, f.content_type or ""))
    out = await ingest.import_files(uploads)
    out["files"] += [
        {
            "filename": f.filename or "upload",
            "status": "skipped",
            "error": f"Only {MAX_IMPORT_FILES} files are read per import; import the rest separately.",
        }
        for f in files[MAX_IMPORT_FILES:]
    ]
    return out


class OrganizeIn(BaseModel):
    full: bool = False


@router.post("/organize")
async def organize(body: OrganizeIn) -> dict:
    return {"job_id": await jobs.enqueue("kb_organize", {"full": body.full})}


@router.get("/export")
async def export(originals: bool = False) -> Response:
    data = await store.export_zip(originals)
    name = f"vicky-knowledge-base-{datetime.now(UTC):%Y-%m-%d}.zip"
    return Response(data, media_type="application/zip", headers=attachment_headers(name))


@router.get("/files/{fid}")
async def original(fid: str) -> Response:
    try:
        row = await db.fetchrow("select filename, mime, bytes from kb_files where id::text = $1", fid)
    except Exception:
        row = None
    if row is None:
        raise HTTPException(404, "That file isn't in the knowledge base.")
    return Response(
        bytes(row["bytes"]),
        media_type=row["mime"] or "application/octet-stream",
        headers=attachment_headers(row["filename"].rsplit("/", 1)[-1]),
    )


def attachment_headers(name: str) -> dict[str, str]:
    """A download's headers. HTTP headers are Latin-1, so the name goes as an ASCII fallback plus the
    RFC 5987 `filename*` with the real one; control characters (CR, LF) never reach the header, and the
    browser may not sniff the bytes into something it would render."""
    name = re.sub(r"[\x00-\x1f\x7f]+", "", name) or "download"
    fallback = (
        name.encode("ascii", "replace").decode("ascii").replace('"', "").replace("\\", "") or "download"
    )
    return {
        "content-disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name, safe='')}",
        "x-content-type-options": "nosniff",
    }


@router.post("/autofill")
async def fill() -> dict:
    return await autofill.autofill()
