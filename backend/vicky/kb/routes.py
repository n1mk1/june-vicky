"""REST surface for the knowledge base (docs/API.md §Knowledge base). Mounted under /api/v1/kb behind
the access gate."""

from datetime import UTC, datetime

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from vicky import db, jobs, llm
from vicky.config import get_settings
from vicky.kb import autofill, ingest, ocr, store
from vicky.kb.store import NoteConflict, NoteInvalid, NoteNotFound

router = APIRouter(prefix="/kb")


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
           from kb_notes""")
    files = await db.fetchrow("select count(*) as files, count(*) filter (where status = 'failed') as failed, "
                              "coalesce(sum(size), 0)::bigint as bytes from kb_files")
    recent = await db.fetch(
        """select id::text, kind::text, status::text, error, result, enqueued_at, finished_at from jobs
           where kind in ('kb_ingest', 'kb_organize') order by enqueued_at desc limit 8""")
    failures = await db.fetch("select id::text, filename, error from kb_files where status = 'failed' "
                              "order by created_at desc limit 20")
    return {**counts, **files, "jobs": recent, "running": any(j["status"] in ("queued", "running") for j in recent),
            "failures": failures, "ocr": ocr.available(), "llm": llm.enabled()}


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
    limit = get_settings().kb_upload_max_bytes
    uploads = []
    for f in files[:200]:
        data = await f.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"{f.filename} is over {limit // (1024 * 1024)} MB")
        uploads.append((f.filename or "upload", data, f.content_type or ""))
    return await ingest.import_files(uploads)


class OrganizeIn(BaseModel):
    full: bool = False


@router.post("/organize")
async def organize(body: OrganizeIn) -> dict:
    return {"job_id": await jobs.enqueue("kb_organize", {"full": body.full})}


@router.get("/export")
async def export(originals: bool = False) -> Response:
    data = await store.export_zip(originals)
    name = f"vicky-knowledge-base-{datetime.now(UTC):%Y-%m-%d}.zip"
    return Response(data, media_type="application/zip", headers={"content-disposition": f'attachment; filename="{name}"'})


@router.get("/files/{fid}")
async def original(fid: str) -> Response:
    try:
        row = await db.fetchrow("select filename, mime, bytes from kb_files where id::text = $1", fid)
    except Exception:
        row = None
    if row is None:
        raise HTTPException(404, "That file isn't in the knowledge base.")
    name = row["filename"].rsplit("/", 1)[-1].replace('"', "")
    return Response(bytes(row["bytes"]), media_type=row["mime"] or "application/octet-stream",
                    headers={"content-disposition": f'attachment; filename="{name}"'})


@router.post("/autofill")
async def fill() -> dict:
    return await autofill.autofill()
