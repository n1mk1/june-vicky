"""Vault storage in Postgres. Paths are unique (`folder/name.ext`); `[[wikilinks]]` in markdown are
parsed on read, so renames and moves never leave a stale edge. `links` holds the related-note paths
the organizer (or the founder) set, kept in step on every move.
"""

import io
import json
import re
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

import yaml

from vik import db
from vik.kb.convert import Draft, clean_segment, safe_name, strip_nul

INBOX = "inbox"
KINDS = {"table", "document", "note", "hub"}
WIKILINK = re.compile(r"\[\[([^\[\]|#\n]+?)(?:#[^\[\]|\n]*)?(?:\|[^\[\]\n]*)?\]\]")
# The document full-text search reads. It matches the kb_notes_fts expression index (migration 0008) exactly,
# and is capped so its tsvector stays under Postgres's 1 MB limit (a huge table would fail every search, or
# with the index, its own insert); words past the cap are still found through the title and path.
FTS_CHARS = 200_000
FTS_DOC = f"to_tsvector('simple', left(title || ' ' || summary || ' ' || content, {FTS_CHARS}))"
LIST_COLS = """id::text, path, title, kind, format, tags, summary, links, meta, author, file_id::text,
               length(content) as size, version, organized_at, created_at, updated_at"""


class NoteNotFound(Exception):
    pass


class NoteInvalid(Exception):
    pass


class NoteConflict(Exception):
    pass


# ---------------------------------------------------------------- paths


def clean_path(path: str, fmt: str) -> str:
    """`a/b/name` → `a/b/name.md` with every segment made safe; the extension follows the format."""
    parts = [clean_segment(p) for p in path.replace("\\", "/").split("/")]
    parts = [p for p in parts if p]
    if not parts:
        raise NoteInvalid("A note needs a name")
    name = parts[-1]
    stem = (
        name[: -len(PurePosixPath(name).suffix)]
        if PurePosixPath(name).suffix.lower() in (".md", ".csv")
        else name
    )
    parts[-1] = f"{stem or 'untitled'}.{fmt}"
    return "/".join(parts)[:400]


def folder_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def stem_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


async def unique_path(conn, path: str, exclude_id: str | None = None) -> str:
    base, _, ext = path.rpartition(".")
    candidate, n = path, 1
    while await conn.fetchval(
        "select 1 from kb_notes where lower(path) = lower($1) and ($2::uuid is null or id <> $2)",
        candidate,
        exclude_id,
    ):
        n += 1
        candidate = f"{base} {n}.{ext}"
    return candidate


def _uuid(nid: str) -> str:
    try:
        return str(uuid.UUID(str(nid)))
    except ValueError as e:
        raise NoteNotFound("note") from e


# ---------------------------------------------------------------- links


def wikilinks(content: str) -> list[str]:
    return [m.group(1).strip() for m in WIKILINK.finditer(content or "")]


class Resolver:
    """Resolves a wikilink target the way Obsidian does: full path, path without extension, file
    name, then title (all case-insensitive)."""

    def __init__(self, notes: list[dict]):
        self.by_path: dict[str, str] = {}
        self.by_stem: dict[str, str] = {}
        self.by_name: dict[str, str] = {}
        self.by_title: dict[str, str] = {}
        for n in notes:
            p = n["path"]
            self.by_path[p.lower()] = p
            self.by_stem.setdefault(p.rsplit(".", 1)[0].lower(), p)
            self.by_name.setdefault(stem_of(p).lower(), p)
            self.by_title.setdefault((n.get("title") or "").strip().lower(), p)

    def resolve(self, target: str) -> str | None:
        t = target.strip().replace("\\", "/").lower()
        return (
            self.by_path.get(t)
            or self.by_stem.get(t)
            or self.by_name.get(t.rsplit("/", 1)[-1])
            or self.by_title.get(t)
        )


# ---------------------------------------------------------------- reads


def _row(r: dict) -> dict:
    out = dict(r)
    out["folder"] = folder_of(out["path"])
    return out


async def list_notes() -> list[dict]:
    rows = await db.fetch(f"select {LIST_COLS} from kb_notes order by path")
    return [_row(r) for r in rows]


async def get_note(nid: str) -> dict:
    row = await db.fetchrow(f"select {LIST_COLS}, content from kb_notes where id = $1", _uuid(nid))
    if row is None:
        raise NoteNotFound("note")
    out = _row(row)
    # Names and titles of the whole vault resolve links the way the graph does; only notes that could link
    # here (they list this path, or their text contains its name or title) are read in full.
    everything = await db.fetch("select id::text, path, title from kb_notes")
    res = Resolver(everything)
    me = out["path"]
    names = [f"%{like_escape(x)}%" for x in {stem_of(me), (out["title"] or "").strip()} if x]
    candidates = await db.fetch(
        "select id::text, path, title, links, case when format = 'md' then content else '' end as content "
        "from kb_notes where path <> $1 and ($1 = any(links) or (format = 'md' and content ilike any($2::text[])))",
        me,
        names,
    )
    out["backlinks"] = [
        {"id": n["id"], "path": n["path"], "title": n["title"]}
        for n in candidates
        if me in (n["links"] or []) or any(res.resolve(t) == me for t in wikilinks(n["content"]))
    ]
    by_path = {n["path"]: n for n in everything}
    out["outlinks"] = []
    seen = set()
    for t in [*wikilinks(out["content"] if out["format"] == "md" else ""), *(out["links"] or [])]:
        p = t if t in by_path else res.resolve(t)
        key = p or f"missing:{t.lower()}"
        if key in seen:
            continue
        seen.add(key)
        hit = by_path.get(p) if p else None
        out["outlinks"].append(
            {"id": hit["id"] if hit else None, "path": p, "title": hit["title"] if hit else t}
        )
    if out["file_id"]:
        f = await db.fetchrow(
            "select id::text, filename, kind, size, status from kb_files where id = $1", out["file_id"]
        )
        out["file"] = f
    return out


async def graph() -> dict:
    """Nodes and edges for the graph view. Unresolved wikilinks become ghost nodes (Obsidian-style)."""
    notes = await db.fetch(
        "select id::text, path, title, kind, format, tags, links, author, "
        "case when format = 'md' then content else '' end as content from kb_notes"
    )
    res = Resolver(notes)
    by_path = {n["path"]: n for n in notes}
    edges: dict[tuple[str, str], str] = {}
    ghosts: dict[str, dict] = {}
    for n in notes:
        for t in wikilinks(n["content"]):
            p = res.resolve(t)
            if p is None:
                gid = f"missing:{t.lower()}"
                ghosts.setdefault(
                    gid,
                    {
                        "id": gid,
                        "title": t,
                        "path": None,
                        "kind": "missing",
                        "folder": "",
                        "tags": [],
                        "author": None,
                    },
                )
                edges.setdefault((n["id"], gid), "link")
            elif p != n["path"]:
                edges[(n["id"], by_path[p]["id"])] = "link"
        for p in n["links"] or []:
            if p in by_path and p != n["path"]:
                a, b = n["id"], by_path[p]["id"]
                if (a, b) not in edges and (b, a) not in edges:
                    edges[(a, b)] = "related"
    degree: dict[str, int] = {}
    for a, b in edges:
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    nodes = [
        {
            "id": n["id"],
            "title": n["title"],
            "path": n["path"],
            "kind": n["kind"],
            "folder": folder_of(n["path"]),
            "tags": n["tags"],
            "author": n["author"],
            "degree": degree.get(n["id"], 0),
        }
        for n in notes
    ]
    nodes += [{**g, "degree": degree.get(g["id"], 0)} for g in ghosts.values()]
    return {"nodes": nodes, "links": [{"source": a, "target": b, "type": t} for (a, b), t in edges.items()]}


def like_escape(s: str) -> str:
    """`s` as a literal inside a LIKE pattern (backslash is the escape character)."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# Matches come from the full-text index or the title and path (short columns: the note text is never read for
# them); a union rather than an OR, so the text match can use the index. Only matched notes are ranked.
SEARCH_SQL = f"""
    with hits as (
        select id from kb_notes where {FTS_DOC} @@ plainto_tsquery('simple', $1)
        union
        select id from kb_notes where title ilike '%' || $3 || '%' escape '\\' or path ilike '%' || $3 || '%' escape '\\'
    )
    select {LIST_COLS},
           ts_rank({FTS_DOC}, plainto_tsquery('simple', $1)) as rank,
           substring(content from greatest(1, position(lower($1) in lower(content)) - 80) for 240) as snippet
    from kb_notes where id in (select id from hits)
    order by rank desc, updated_at desc limit $2"""


async def search(q: str, limit: int = 20) -> list[dict]:
    q = strip_nul(q).strip()
    if not q:
        return []
    rows = await db.fetch(SEARCH_SQL, q, limit, like_escape(q))
    return [_row(r) for r in rows]


async def keyword_search(terms: list[str], limit: int = 20) -> list[dict]:
    """Notes matching any of `terms` (letters and digits only), best first; words of four or more
    letters also match as prefixes (churn → churned). For agents, whose questions rarely match a
    note word for word the way `search` needs."""
    terms = [t for t in (re.sub(r"[^a-z0-9]", "", t.lower()) for t in terms) if t][:16]
    if not terms:
        return []
    tsq = " | ".join(f"{t}:*" if len(t) >= 4 else t for t in terms)
    rows = await db.fetch(
        f"""select {LIST_COLS},
                   ts_rank({FTS_DOC}, to_tsquery('simple', $1)) as rank
            from kb_notes
            where {FTS_DOC} @@ to_tsquery('simple', $1)
            order by rank desc, updated_at desc limit $2""",
        tsq,
        limit,
    )
    return [_row(r) for r in rows]


async def contents(ids: list[str]) -> dict[str, dict]:
    """id → {id, path, title, kind, format, summary, content} for the given notes."""
    rows = await db.fetch(
        "select id::text, path, title, kind, format, summary, content from kb_notes "
        "where id = any($1::uuid[])",
        [_uuid(i) for i in ids],
    )
    return {r["id"]: r for r in rows}


async def find_note(ref: str) -> dict | None:
    """A note by id or by path (case-insensitive; the extension may be left off)."""
    ref = ref.strip()
    try:
        nid = _uuid(ref)
    except NoteNotFound:
        nid = None
    return await db.fetchrow(
        "select id::text, path, title, kind, format, summary, content from kb_notes "
        "where ($1::uuid is not null and id = $1) or lower(path) = lower($2) "
        "or lower(regexp_replace(path, '\\.(md|csv)$', '')) = lower($2) "
        "order by (lower(path) = lower($2)) desc limit 1",
        nid,
        ref,
    )


# ---------------------------------------------------------------- writes


async def insert_draft(
    conn,
    d: Draft,
    *,
    path: str,
    file_id: str | None,
    author: str = "import",
    links: list[str] | None = None,
    kind: str | None = None,
) -> str:
    path = await unique_path(conn, clean_path(path, d.format))
    return await conn.fetchval(
        """insert into kb_notes (path, title, kind, format, content, file_id, tags, summary, links, meta, author)
           values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) returning id::text""",
        path,
        (d.title or stem_of(path))[:200],
        kind or d.kind,
        d.format,
        d.content,
        file_id,
        clean_tags(d.tags),
        d.summary[:1000],
        links or [],
        d.meta,
        author,
    )


def clean_tags(tags: list[Any]) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        # Letters and digits in any script (founders tag in their own language), "/" for nesting.
        s = re.sub(r"[^\w/-]+", "-", str(t).strip().lstrip("#").lower()).strip("-_")[:40]
        if s and s not in out:
            out.append(s)
    return out[:12]


async def create_note(body: dict, author: str = "founder") -> dict:
    body = strip_nul(body)  # Postgres text can't hold U+0000
    fmt = "csv" if body.get("format") == "csv" else "md"
    title = str(body.get("title") or "").strip()[:200]
    path = str(body.get("path") or "").strip() or title or "Untitled"
    kind = body.get("kind") if body.get("kind") in KINDS else ("table" if fmt == "csv" else "note")
    d = Draft(
        name="",
        title=title or stem_of(clean_path(path, fmt)),
        kind=kind,
        format=fmt,
        content=str(body.get("content") or ""),
        tags=list(body.get("tags") or []),
        summary=str(body.get("summary") or ""),
    )
    async with db.acquire() as conn, conn.transaction():
        nid = await insert_draft(
            conn, d, path=path, file_id=None, author=author, links=[str(x) for x in body.get("links") or []]
        )
    return await get_note(nid)


async def update_note(nid: str, body: dict, author: str = "founder") -> dict:
    nid = _uuid(nid)
    body = strip_nul(body)  # Postgres text can't hold U+0000
    async with db.acquire() as conn, conn.transaction():
        row = await conn.fetchrow("select * from kb_notes where id = $1 for update", nid)
        if row is None:
            raise NoteNotFound("note")
        if body.get("version") is not None and int(body["version"]) != row["version"]:
            raise NoteConflict("This note changed since you opened it. Reload it to see the latest version.")
        sets: dict[str, Any] = {}
        if "content" in body and body["content"] is not None:
            sets["content"] = str(body["content"])
        if body.get("title"):
            sets["title"] = str(body["title"]).strip()[:200]
        if "tags" in body and body["tags"] is not None:
            sets["tags"] = clean_tags(body["tags"])
        if "summary" in body and body["summary"] is not None:
            sets["summary"] = str(body["summary"])[:1000]
        if "links" in body and body["links"] is not None:
            sets["links"] = [str(x) for x in body["links"]]
        if body.get("path"):
            new = await unique_path(conn, clean_path(str(body["path"]), row["format"]), exclude_id=nid)
            if new != row["path"]:
                sets["path"] = new
        if not sets:
            return await get_note(nid)
        sets["author"] = author if author != "import" else row["author"]
        cols = list(sets)
        await conn.execute(
            f"update kb_notes set {', '.join(f'{c} = ${i + 2}' for i, c in enumerate(cols))}, version = version + 1 "
            "where id = $1",
            nid,
            *[sets[c] for c in cols],
        )
        if "path" in sets:
            await move_links(conn, row["path"], sets["path"])
    return await get_note(nid)


async def move_links(conn, old: str, new: str) -> None:
    await conn.execute(
        "update kb_notes set links = array_replace(links, $1, $2) where $1 = any(links)", old, new
    )


async def delete_note(nid: str) -> None:
    nid = _uuid(nid)
    async with db.acquire() as conn, conn.transaction():
        gone = await conn.fetchrow("delete from kb_notes where id = $1 returning path, title, file_id", nid)
        if gone is None:
            raise NoteNotFound("note")
        path = gone["path"]
        await conn.execute("update kb_notes set links = array_remove(links, $1) where $1 = any(links)", path)
        # The organizer's hubs list every note; drop their lines that point at this one, so the graph
        # doesn't keep a ghost of it. Hubs the founder edited are theirs and stay as written.
        res = Resolver([{"path": path, "title": gone["title"]}])
        for hub in await conn.fetch("select id, content from kb_notes where kind = 'hub' and author = 'ai'"):
            lines = hub["content"].split("\n")
            kept = [ln for ln in lines if not any(res.resolve(t) == path for t in wikilinks(ln))]
            if len(kept) != len(lines):
                await conn.execute(
                    "update kb_notes set content = $2 where id = $1", hub["id"], "\n".join(kept)
                )
        # Its original goes too once no note is made from it (its text lives nowhere else). Other files, such as
        # failed imports the status page lists, are not this note's to drop.
        if gone["file_id"] is not None:
            await conn.execute(
                "delete from kb_files f where f.id = $1 and f.status <> 'stored' and not exists "
                "(select 1 from kb_notes n where n.file_id = f.id)",
                gone["file_id"],
            )


# ---------------------------------------------------------------- export


def frontmatter(n: dict) -> str:
    data: dict[str, Any] = {"title": n["title"]}
    if n["tags"]:
        data["tags"] = list(n["tags"])
    if n["summary"]:
        data["summary"] = n["summary"]
    data["kind"] = n["kind"]
    if (n["meta"] or {}).get("source"):
        data["source"] = n["meta"]["source"]
    if n["links"]:
        data["related"] = [f"[[{p.rsplit('.', 1)[0]}]]" for p in n["links"]]
    return "---\n" + yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip() + "\n---\n\n"


async def export_zip(originals: bool = False) -> bytes:
    notes = await db.fetch(
        "select path, title, kind, format, content, tags, summary, links, meta, author from kb_notes "
        "order by path"
    )
    buf = io.BytesIO()
    meta: dict[str, Any] = {
        "format": "vik-kb",
        "version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "notes": {},
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in notes:
            body = frontmatter(n) + n["content"] if n["format"] == "md" else n["content"]
            z.writestr(n["path"], body)
            meta["notes"][n["path"]] = {
                k: n[k] for k in ("title", "kind", "tags", "summary", "links", "author", "meta")
            }
        if originals:
            used: set[str] = set()
            for f in await db.fetch("select filename, bytes from kb_files order by created_at"):
                filename = safe_name(f["filename"])  # rows stored before names were cleaned may hold "../"
                name = f"_originals/{filename}"
                k = 1
                while name in used:
                    k += 1
                    stem, dot, ext = filename.rpartition(".")
                    name = f"_originals/{stem or filename} {k}{dot}{ext if stem else ''}"
                used.add(name)
                z.writestr(name, bytes(f["bytes"]))
        z.writestr(".vik/meta.json", json.dumps(meta, indent=2, default=str))
    return buf.getvalue()
