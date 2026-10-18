"""Import: store each original in `kb_files`, convert it to notes (in a thread: OCR blocks), then
organize. A file whose bytes are already in the vault is skipped, so dumping the same folder twice
adds nothing. A zip exported from this vault (`.vicky/meta.json`) comes back with its paths, titles,
tags, summaries and links as they were.
"""

import asyncio
import hashlib
import json
import logging
import mimetypes

from vicky import db, jobs
from vicky.kb import convert
from vicky.kb.convert import Draft, Unreadable
from vicky.kb.store import INBOX, insert_draft

log = logging.getLogger(__name__)
VAULT_META = ".vicky/meta.json"


async def store_files(uploads: list[tuple[str, bytes, str]]) -> dict:
    """Expand zips and store every file. Returns {file_ids, files: [{filename, status}], vault_meta}."""
    stored, report, vault_meta = [], [], {}
    for filename, data, mime in uploads:
        try:
            entries = convert.expand(filename, data)
        except Unreadable as e:
            report.append({"filename": filename, "status": "failed", "error": str(e)})
            continue
        for name, blob in entries:
            if name == VAULT_META:
                try:
                    vault_meta.update((json.loads(blob.decode("utf-8")) or {}).get("notes") or {})
                except (ValueError, UnicodeDecodeError):
                    pass
                continue
            if not blob:
                continue
            sha = hashlib.sha256(blob).hexdigest()
            dup = await db.fetchval("select 1 from kb_files f where sha256 = $1 and exists "
                                    "(select 1 from kb_notes n where n.file_id = f.id)", sha)
            if dup:
                report.append({"filename": name, "status": "duplicate"})
                continue
            kind = convert.file_kind(name)
            fid = await db.fetchval(
                "insert into kb_files (filename, mime, bytes, size, sha256, kind) values ($1,$2,$3,$4,$5,$6) "
                "returning id::text", name[:400], (mime if len(entries) == 1 else "") or
                mimetypes.guess_type(name)[0] or "application/octet-stream", blob, len(blob), sha, kind)
            stored.append(fid)
            report.append({"filename": name, "status": "stored", "id": fid})
    return {"file_ids": stored, "files": report, "vault_meta": vault_meta}


async def import_files(uploads: list[tuple[str, bytes, str]]) -> dict:
    """Store, then convert and organize in a background job. Returns the store report and job id."""
    out = await store_files(uploads)
    job_id = None
    if out["file_ids"]:
        job_id = await jobs.enqueue("kb_ingest", {"file_ids": out["file_ids"], "vault_meta": out["vault_meta"]})
    return {"job_id": job_id, "files": out["files"]}


def _restore(d: Draft, meta: dict) -> tuple[Draft, str, list[str], str | None]:
    """Apply an exported vault's metadata to a draft at the same path."""
    d.title = str(meta.get("title") or d.title)
    d.tags = list(meta.get("tags") or d.tags)
    d.summary = str(meta.get("summary") or d.summary)
    d.meta = {**(meta.get("meta") or {}), **d.meta}
    author = meta.get("author") if meta.get("author") in ("import", "ai", "founder") else "import"
    kind = meta.get("kind") if meta.get("kind") in ("table", "document", "note", "hub") else None
    return d, author, [str(x) for x in meta.get("links") or []], kind


async def convert_files(file_ids: list[str], vault_meta: dict | None = None) -> dict:
    vault_meta = vault_meta or {}
    notes = failed = 0
    errors = []
    for fid in file_ids:
        row = await db.fetchrow("select id::text, filename, bytes from kb_files where id = $1", fid)
        if row is None:
            continue
        try:
            drafts = await asyncio.to_thread(convert.convert, row["filename"], bytes(row["bytes"]))
        except Unreadable as e:
            await db.execute("update kb_files set status = 'failed', error = $2 where id = $1", fid, str(e)[:500])
            failed += 1
            errors.append({"filename": row["filename"], "error": str(e)})
            continue
        except Exception as e:  # a converter bug must not lose the rest of the batch
            log.exception("kb convert failed for %s", row["filename"])
            await db.execute("update kb_files set status = 'failed', error = $2 where id = $1", fid,
                             f"Could not convert: {e}"[:500])
            failed += 1
            errors.append({"filename": row["filename"], "error": f"Could not convert: {e}"})
            continue
        async with db.pool().acquire() as conn, conn.transaction():
            for d in drafts:
                path = f"{d.folder or INBOX}/{d.name}"
                if not d.folder and d.name in vault_meta:  # a root-level note of an exported vault
                    path = d.name
                author, links, kind, organized = "import", [], None, False
                if path in vault_meta:
                    d, author, links, kind = _restore(d, vault_meta[path])
                    organized = True
                nid = await insert_draft(conn, d, path=path, file_id=fid, author=author, links=links, kind=kind)
                if organized:
                    await conn.execute("update kb_notes set organized_at = now() where id = $1", nid)
                notes += 1
            await conn.execute("update kb_files set status = 'converted', error = null where id = $1", fid)
    return {"notes": notes, "failed": failed, "errors": errors[:20]}


async def ingest_job(payload: dict) -> dict:
    from vicky.kb.organize import organize

    out = await convert_files(payload.get("file_ids") or [], payload.get("vault_meta") or {})
    out["organize"] = await organize()
    return out
