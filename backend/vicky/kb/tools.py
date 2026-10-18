"""Read-only vault access for the agents: `kb_search` and `kb_read` for the Claude tool runner, and
the same keyword search for the offline path.

A note is cited by its path: `“exact words from the note” [kb:folder/Note.md]`. Notes are the
founder's own material, not computed figures, so a number from a note may only appear inside such a
verbatim quote; the audit (`audit_text(..., notes=...)`) checks each quote against the note's text
and still blocks every number outside one that no Figure backs. A `Vault` records every note its
tools returned in the turn; only those notes can be cited.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from anthropic import beta_async_tool

from vicky import db
from vicky.kb import store

log = logging.getLogger(__name__)

SEARCH_LIMIT = 5
EXCERPTS = 3
EXCERPT_CHARS = 280
READ_CHARS = 12000
RESULT_CHARS = 20000

STOPWORDS = set("""a about after all also am an and any are as at be been before but by can could did do does doing
for from had has have how i if in into is it its me my no not of on or our out over said say says so some than that
the their them then there these they this those to up us was we were what when where which while who why will with
would you your vicky note notes knowledge base vault doc docs document documents tell show find give""".split())

CITE_RULE = ("Quote a note only word for word inside double quotes, followed by its cite token, e.g. "
             "\"exact words\" [kb:folder/Note.md]. Never restate, round, convert or compute a number from a note; "
             "numbers you state yourself must come from the figures.")


def terms(query: str) -> list[str]:
    out: list[str] = []
    for w in re.findall(r"[a-z0-9]+", query.lower().replace("’", "'")):
        if (len(w) >= 2 or w.isdigit()) and w not in STOPWORDS and w not in out:
            out.append(w)
    return out[:12]


def _hits(line: str, ts: list[str]) -> int:
    low = line.lower()
    return sum(1 for t in ts if re.search(rf"\b{re.escape(t)}", low))


def _trim(line: str, ts: list[str], width: int = EXCERPT_CHARS) -> str:
    """A window of `line` around its first hit, cut at spaces, so it stays a verbatim substring."""
    if len(line) <= width:
        return line
    low = line.lower()
    first = min((m.start() for t in ts for m in [re.search(rf"\b{re.escape(t)}", low)] if m), default=0)
    lo = max(0, first - width // 3)
    if lo:
        sp = line.find(" ", lo)
        lo = sp + 1 if 0 <= sp < first else lo
    hi = min(len(line), lo + width)
    if hi < len(line):
        sp = line.rfind(" ", lo, hi)
        hi = sp if sp > lo else hi
    return line[lo:hi].strip()


def excerpts(content: str, ts: list[str], n: int = EXCERPTS) -> list[str]:
    """Up to `n` lines of the note that name the most query terms (headings count for less), best
    first; each is a verbatim piece of the note."""
    lines = [ln.strip() for ln in (content or "").splitlines() if ln.strip() and not ln.strip().startswith("---")]
    scored = [(_hits(ln, ts) - (0.5 if ln.startswith("#") else 0), i, ln) for i, ln in enumerate(lines)]
    best = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))[:n]
    if not best:
        best = [s for s in scored if not s[2].startswith("#")][:1]
    return [_trim(ln, ts) for _, _, ln in best]


def cite(path: str) -> str:
    return f"[kb:{path}]"


async def has_notes() -> bool:
    """False when the vault is empty or the database is unreachable (agents then run without it)."""
    try:
        return bool(await db.fetchval("select exists (select 1 from kb_notes)"))
    except Exception as e:
        log.info("knowledge base not available to agents: %s", e)
        return False


@dataclass
class Vault:
    """One agent turn's view of the vault: what its tools returned, so the audit can verify quotes."""
    seen: dict[str, dict] = field(default_factory=dict)  # path → {id, path, title, kind, content}

    def _keep(self, n: dict) -> None:
        self.seen[n["path"]] = {k: n[k] for k in ("id", "path", "title", "kind", "content")}

    def notes(self) -> dict[str, dict]:
        """For `audit_text(..., notes=...)`."""
        return self.seen

    async def search(self, query: str, limit: int = SEARCH_LIMIT) -> dict[str, Any]:
        query = str(query or "").strip()[:300]
        ts = terms(query)
        if not query or not ts:
            return {"notes": [], "error": "Give a few keywords to search for."}
        ids: list[str] = []
        for r in [*await store.search(query, limit), *await store.keyword_search(ts, limit * 2)]:
            if r["id"] not in ids:
                ids.append(r["id"])
        ids = ids[:limit]
        full = await store.contents(ids)
        out = []
        for i in ids:
            n = full.get(i)
            if n is None:
                continue
            self._keep(n)
            item = {"id": n["id"], "path": n["path"], "title": n["title"], "kind": n["kind"], "cite": cite(n["path"]),
                    "summary": n["summary"], "excerpts": excerpts(n["content"], ts)}
            if n["format"] == "csv":
                item["header"] = n["content"].split("\n", 1)[0][:400]
            out.append(item)
        return {"notes": out, "how_to_cite": CITE_RULE,
                "note": "The summary is a description written for the vault; quote only from excerpts or kb_read."}

    async def read(self, ref: str) -> dict[str, Any]:
        n = await store.find_note(str(ref or ""))
        if n is None:
            return {"error": f"no note {ref!r}; use an id or path from kb_search"}
        self._keep(n)
        text = n["content"]
        return {"id": n["id"], "path": n["path"], "title": n["title"], "kind": n["kind"], "format": n["format"],
                "cite": cite(n["path"]), "content": text[:READ_CHARS], "truncated": len(text) > READ_CHARS,
                "how_to_cite": CITE_RULE}

    def tools(self) -> list[Any]:
        async def kb_search(query: str) -> str:
            return json.dumps(await self.search(query), default=str)[:RESULT_CHARS]

        async def kb_read(note: str) -> str:
            return json.dumps(await self.read(note), default=str)[:RESULT_CHARS]

        return [
            beta_async_tool(kb_search, name="kb_search", strict=True,
                            description="Keyword search over the founder's knowledge base (their own notes: decks, "
                                        "memos, board packs, tables). Returns note title, path, cite token and "
                                        "verbatim excerpts. " + CITE_RULE,
                            input_schema={"type": "object", "properties": {"query": {"type": "string"}},
                                          "required": ["query"], "additionalProperties": False}),
            beta_async_tool(kb_read, name="kb_read", strict=True,
                            description="Read one note from the knowledge base by id or path (from kb_search). "
                                        + CITE_RULE,
                            input_schema={"type": "object", "properties": {"note": {"type": "string"}},
                                          "required": ["note"], "additionalProperties": False}),
        ]


async def vault_for_agents() -> Vault | None:
    """A fresh Vault when there is anything in it, else None (the agent gets no kb tools)."""
    return Vault() if await has_notes() else None
