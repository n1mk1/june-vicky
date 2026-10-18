"""Import: store each original in `kb_files`, convert it to notes (in a thread: OCR blocks), then
organize. A file whose bytes are already in the vault (or arriving in the same or a concurrent import)
is skipped, so dumping the same folder twice adds nothing. A zip exported from this vault
(`.vicky/meta.json`) comes back with its paths, titles, tags, summaries and links as they were, and its
`_originals/` are linked to the restored notes instead of being converted a second time.
"""

import asyncio
import hashlib
import json
import logging
import mimetypes
from pathlib import PurePosixPath

from vicky import db, jobs
from vicky.kb import convert
from vicky.kb.convert import Draft, Unreadable, safe_name
from vicky.kb.store import INBOX, insert_draft

log = logging.getLogger(__name__)
VAULT_META = ".vicky/meta.json"
ORIGINALS = "_originals/"
SHA_LOCK = 7_331_003  # with hashtext(sha256): one import at a time checks and stores the same bytes


def _vault_notes(blob: bytes) -> dict[str, dict]:
    """The `notes` map of an exported vault's meta.json; anything malformed reads as no metadata."""
    try:
        m = json.loads(blob.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    notes = m.get("notes") if isinstance(m, dict) else None
    if not isinstance(notes, dict):
        return {}
    return {k: v for k, v in notes.items() if isinstance(k, str) and isinstance(v, dict)}


async def _store_one(name: str, mime: str, blob: bytes, sha: str, status: str) -> str | None:
    """Store a file unless the same bytes are already in the vault or on their way in. Returns its id."""
    async with db.acquire() as conn, conn.transaction():
        await conn.execute("select pg_advisory_xact_lock($1, hashtext($2))", SHA_LOCK, sha)
        dup = await conn.fetchval(
            """select 1 from kb_files f where sha256 = $1 and (
                 exists (select 1 from kb_notes n where n.file_id = f.id)
                 or (f.status = 'stored' and f.created_at > now() - make_interval(secs => $2)))""",
            sha,
            jobs.STALE_AFTER_S,
        )
        if dup:
            return None
        # Earlier copies that never became notes (a failed conversion, an import whose job died) are replaced.
        await conn.execute(
            """delete from kb_files f where sha256 = $1 and status in ('failed', 'stored')
                 and not exists (select 1 from kb_notes n where n.file_id = f.id)""",
            sha,
        )
        return await conn.fetchval(
            "insert into kb_files (filename, mime, bytes, size, sha256, kind, status) values ($1,$2,$3,$4,$5,$6,$7) "
            "returning id::text",
            name[:400],
            mime,
            blob,
            len(blob),
            sha,
            convert.file_kind(name),
            status,
        )


async def store_files(uploads: list[tuple[str, bytes, str]]) -> dict:
    """Expand zips and store every file. Returns {file_ids, files: [{filename, status}], vault_meta, originals}."""
    stored, report, vault_meta, originals = [], [], {}, {}
    seen: set[str] = set()
    for filename, data, mime in uploads:
        try:
            entries = convert.expand(filename, data)
        except Unreadable as e:
            report.append({"filename": safe_name(filename), "status": "failed", "error": str(e)})
            continue
        exported = any(name == VAULT_META for name, _ in entries)
        for raw, blob in entries:
            if raw == VAULT_META:
                vault_meta.update(_vault_notes(blob))
                continue
            name = safe_name(raw)
            if not blob:
                report.append({"filename": name, "status": "skipped", "error": "The file is empty."})
                continue
            sha = hashlib.sha256(blob).hexdigest()
            if sha in seen:
                report.append({"filename": name, "status": "duplicate"})
                continue
            seen.add(sha)
            original = exported and name.startswith(ORIGINALS)
            fid = await _store_one(
                name[len(ORIGINALS) :] if original else name,
                (mime if len(entries) == 1 else "")
                or mimetypes.guess_type(name)[0]
                or "application/octet-stream",
                blob,
                sha,
                "converted" if original else "stored",
            )
            if fid is None:
                report.append({"filename": name, "status": "duplicate"})
                continue
            if original:
                originals[name[len(ORIGINALS) :]] = fid
            else:
                stored.append(fid)
            report.append({"filename": name, "status": "stored", "id": fid})
    return {"file_ids": stored, "files": report, "vault_meta": vault_meta, "originals": originals}


async def import_files(uploads: list[tuple[str, bytes, str]]) -> dict:
    """Store, then convert and organize in a background job. Returns the store report and job id."""
    out = await store_files(uploads)
    job_id = None
    if out["file_ids"] or out["originals"]:
        job_id = await jobs.enqueue(
            "kb_ingest",
            {"file_ids": out["file_ids"], "vault_meta": out["vault_meta"], "originals": out["originals"]},
        )
    return {"job_id": job_id, "files": out["files"]}


def _restore(d: Draft, meta: dict) -> tuple[Draft, str, list[str], str | None]:
    """Apply an exported vault's metadata to a draft at the same path."""
    tags, links, extra = meta.get("tags"), meta.get("links"), meta.get("meta")
    d.title = str(meta.get("title") or d.title)
    d.tags = [str(t) for t in tags] if isinstance(tags, list) else d.tags
    d.summary = str(meta.get("summary") or d.summary)
    d.meta = {**(extra if isinstance(extra, dict) else {}), **d.meta}
    author = meta.get("author") if meta.get("author") in ("import", "ai", "founder") else "import"
    kind = meta.get("kind") if meta.get("kind") in ("table", "document", "note", "hub") else None
    return d, author, [str(x) for x in links] if isinstance(links, list) else [], kind


def _original_for(meta: dict, originals: dict[str, str]) -> str | None:
    """The `_originals/` file a restored note was made from, by its recorded source file name."""
    src = (meta.get("meta") or {}).get("source") if isinstance(meta.get("meta"), dict) else None
    if not src:
        return None
    return next((fid for name, fid in originals.items() if PurePosixPath(name).name == src), None)


async def _fail(fid: str, message: str) -> None:
    await db.execute("update kb_files set status = 'failed', error = $2 where id = $1", fid, message[:500])


async def convert_files(
    file_ids: list[str], vault_meta: dict | None = None, originals: dict[str, str] | None = None
) -> dict:
    vault_meta = vault_meta or {}
    originals = originals or {}
    notes = failed = 0
    errors = []
    for fid in file_ids:
        row = await db.fetchrow("select id::text, filename, bytes from kb_files where id = $1", fid)
        if row is None:
            continue
        try:
            drafts = await asyncio.to_thread(convert.convert, row["filename"], bytes(row["bytes"]))
        except Unreadable as e:
            await _fail(fid, str(e))
            failed += 1
            errors.append({"filename": row["filename"], "error": str(e)})
            continue
        except Exception as e:  # a converter bug must not lose the rest of the batch
            log.exception("kb convert failed for %s", row["filename"])
            await _fail(fid, f"Could not convert: {e}")
            failed += 1
            errors.append({"filename": row["filename"], "error": f"Could not convert: {e}"})
            continue
        try:
            async with db.acquire() as conn, conn.transaction():
                made, relinked = 0, False
                for d in drafts:
                    path = f"{d.folder or INBOX}/{d.name}"
                    if not d.folder and d.name in vault_meta:  # a root-level note of an exported vault
                        path = d.name
                    author, links, kind, organized, source = "import", [], None, False, fid
                    if path in vault_meta:
                        source = _original_for(vault_meta[path], originals) or fid
                        relinked = relinked or source != fid
                        d, author, links, kind = _restore(d, vault_meta[path])
                        organized = True
                    else:
                        # What the converter wrote, so Fill dashboard can tell a founder's edit from the original.
                        d.meta["converted_md5"] = hashlib.md5(d.content.encode("utf-8")).hexdigest()
                    nid = await insert_draft(
                        conn, d, path=path, file_id=source, author=author, links=links, kind=kind
                    )
                    if organized:
                        await conn.execute("update kb_notes set organized_at = now() where id = $1", nid)
                    made += 1
                await conn.execute(
                    "update kb_files set status = 'converted', error = null where id = $1", fid
                )
                # An exported note whose original came back with it points at that original: the export copy
                # itself is then no one's source and is dropped.
                if relinked:
                    await conn.execute(
                        "delete from kb_files f where f.id = $1 and not exists "
                        "(select 1 from kb_notes n where n.file_id = f.id)",
                        fid,
                    )
        except Exception as e:  # one file's notes failing to save must not lose the rest of the batch
            log.exception("kb import could not save the notes of %s", row["filename"])
            await _fail(fid, f"Could not save its notes: {e}")
            failed += 1
            errors.append({"filename": row["filename"], "error": f"Could not save its notes: {e}"})
            continue
        notes += made
    if originals:  # an original no restored note claimed has nothing to show for it
        await db.execute(
            "delete from kb_files f where f.id = any($1::uuid[]) and not exists "
            "(select 1 from kb_notes n where n.file_id = f.id)",
            list(originals.values()),
        )
    return {"notes": notes, "failed": failed, "errors": errors[:20]}


async def ingest_job(payload: dict) -> dict:
    from vicky.kb.organize import organize

    out = await convert_files(
        payload.get("file_ids") or [], payload.get("vault_meta") or {}, payload.get("originals") or {}
    )
    out["organize"] = await organize()
    return out
