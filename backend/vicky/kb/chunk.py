"""Cut a note into retrieval chunks (docs/08-RAG.md §Indexing).

A chunk's `text` is always `content[start:end]`, so a quote taken from it is a quote from the note and the
citation audit is unchanged. Chunks follow the converter's own structure: a heading (`## Page 4`,
`## Slide 7: Traction`, any markdown heading) starts a new section and no chunk crosses one, so a quote keeps
its page. Inside a section, paragraphs and tables are packed to about 300–500 tokens with a one-block
overlap; a table stays whole unless it is longer than the limit, and then splits by rows, each piece carrying
the header row in its context (not in its text, which must stay a span of the note).

CSV notes give one chunk, the header row: questions about values belong to the metrics engine.
"""

import hashlib
import re
from dataclasses import dataclass, field

TARGET_CHARS = 1600   # ~400 tokens
MAX_CHARS = 2400      # ~600 tokens
OVERLAP_MAX = 400     # the previous block is carried over when it is at most this long
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


@dataclass
class Chunk:
    ord: int
    heading: str
    start: int
    end: int
    text: str
    header: str = ""                       # a split table's header row, for context only
    tokens: list[str] = field(default_factory=list)

    @property
    def text_sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass
class _Block:
    start: int
    end: int
    table: bool


def _lines(content: str) -> list[tuple[int, int, str]]:
    """(start, end, line) with end excluding the newline."""
    out, pos = [], 0
    for line in content.split("\n"):
        out.append((pos, pos + len(line), line))
        pos += len(line) + 1
    return out


def _sections(content: str) -> list[tuple[str, int, int]]:
    """(heading, start, end) spans; text before the first heading has heading ''."""
    secs: list[tuple[str, int, int]] = []
    heading, start = "", 0
    in_fence = False
    for s, _e, line in _lines(content):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else HEADING.match(line)
        if m:
            if s > start:
                secs.append((heading, start, s))
            heading, start = re.sub(r"[*_`]", "", m.group(2)).strip(), s
    if len(content) > start:
        secs.append((heading, start, len(content)))
    return secs


def _blocks(content: str, start: int, end: int) -> list[_Block]:
    """Paragraphs, fenced blocks and tables inside [start, end), as spans without surrounding blank lines."""
    blocks: list[_Block] = []
    cur: list[tuple[int, int, str]] = []
    in_fence = False

    def flush() -> None:
        if cur:
            table = all(ln.lstrip().startswith("|") for _, _, ln in cur)
            blocks.append(_Block(cur[0][0], cur[-1][1], table))
            cur.clear()

    for s, e, line in _lines(content[start:end]):
        s, e = s + start, e + start
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            cur.append((s, e, line))
            if not in_fence:
                flush()
            continue
        if in_fence:
            cur.append((s, e, line))
            continue
        if not line.strip():
            flush()
            continue
        is_row = line.lstrip().startswith("|")
        if cur and is_row != all(ln.lstrip().startswith("|") for _, _, ln in cur):
            flush()  # a table and the paragraph around it are separate blocks
        cur.append((s, e, line))
    flush()
    return blocks


def _split_long(content: str, b: _Block) -> list[tuple[int, int, str]]:
    """A block longer than MAX_CHARS as (start, end, header) pieces: tables by rows, prose by sentences."""
    lines = [(s, e, ln) for s, e, ln in _lines(content[b.start:b.end])]
    lines = [(s + b.start, e + b.start, ln) for s, e, ln in lines]
    pieces: list[tuple[int, int, str]] = []
    if b.table and len(lines) > 2:
        header = lines[0][2]
        body = lines[2:] if re.match(r"^\s*\|[\s:|-]+\|?\s*$", lines[1][2]) else lines[1:]
        first = lines[0][0]
        cur_start = first
        for i, (s, e, _ln) in enumerate(body):
            if e - cur_start > TARGET_CHARS and s > cur_start:
                pieces.append((cur_start, body[i - 1][1], "" if cur_start == first else header))
                cur_start = s
        pieces.append((cur_start, b.end, "" if cur_start == first else header))
        return pieces
    # prose (or a code block): cut at sentence ends, else at a space
    pos = b.start
    while b.end - pos > MAX_CHARS:
        window = content[pos:pos + MAX_CHARS]
        cut = max(window.rfind(". ", 0, TARGET_CHARS + 400), window.rfind("\n", 0, TARGET_CHARS + 400))
        if cut < TARGET_CHARS // 2:
            cut = window.rfind(" ", 0, TARGET_CHARS)
        if cut <= 0:
            cut = TARGET_CHARS
        else:
            cut += 1
        pieces.append((pos, pos + cut, ""))
        pos += cut
        while pos < b.end and content[pos] in " \n":
            pos += 1
    if pos < b.end:
        pieces.append((pos, b.end, ""))
    return pieces


def _trim(content: str, start: int, end: int) -> tuple[int, int]:
    while start < end and content[start] in " \n\t\r":
        start += 1
    while end > start and content[end - 1] in " \n\t\r":
        end -= 1
    return start, end


def chunk_note(content: str, fmt: str = "md") -> list[Chunk]:
    content = content or ""
    if not content.strip():
        return []
    if fmt == "csv":
        first = content.split("\n", 1)[0]
        s, e = _trim(content, 0, len(first))
        return [Chunk(0, "", s, e, content[s:e])] if e > s else []
    chunks: list[Chunk] = []

    def add(heading: str, start: int, end: int, header: str = "") -> None:
        start, end = _trim(content, start, end)
        if end > start:
            chunks.append(Chunk(len(chunks), heading, start, end, content[start:end], header))

    for heading, s_start, s_end in _sections(content):
        blocks = _blocks(content, s_start, s_end)
        if not blocks:
            continue
        pack: list[_Block] = []
        for b in blocks:
            if b.end - b.start > MAX_CHARS:
                if pack:
                    add(heading, pack[0].start, pack[-1].end)
                    pack = []
                for ps, pe, header in _split_long(content, b):
                    add(heading, ps, pe, header)
                continue
            if pack and b.end - pack[0].start > TARGET_CHARS:
                add(heading, pack[0].start, pack[-1].end)
                last = pack[-1]
                carry = last.end - last.start <= OVERLAP_MAX and not last.table and b.end - last.start <= MAX_CHARS
                pack = [last] if carry else []
            pack.append(b)
        if pack:
            add(heading, pack[0].start, pack[-1].end)
    # A section heading line alone (e.g. "## Page 3" with nothing under it) yields no chunk.
    kept = [c for c in chunks if not HEADING.match(c.text) or "\n" in c.text]
    for i, c in enumerate(kept):
        c.ord = i
    return kept


def context_line(note: dict, c: Chunk) -> str:
    """What goes in front of a chunk when it is embedded (contextual retrieval): never stored as its text."""
    tags = ", ".join(note.get("tags") or [])
    parts = [note.get("title") or "", note.get("path") or "", tags, (note.get("summary") or "")[:400], c.heading]
    return " · ".join(p for p in parts if p)


def embed_text(note: dict, c: Chunk) -> str:
    head = context_line(note, c)
    return "\n".join(p for p in (head, c.header, c.text) if p)


def embed_sha(note: dict, c: Chunk, model: str) -> str:
    return hashlib.sha256(f"{model}\n{embed_text(note, c)}".encode()).hexdigest()
