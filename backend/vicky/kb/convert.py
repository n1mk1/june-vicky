"""Any file → notes the AI can read later. Code only: no model touches the text or the numbers.

| In | Out |
|---|---|
| CSV / TSV | one CSV note, normalized to comma-separated |
| XLSX | one CSV note per sheet, plus a note with the chart data if the workbook has charts |
| PDF | one markdown note, `## Page n` per page: the text layer, OCR where a page has none, and OCR of the figures (charts, screenshots) on the other pages |
| DOCX | markdown with headings, lists and tables in order; chart data and OCR of images appended |
| PPTX | `## Slide n` per slide: text, tables, chart data as tables, OCR of pictures, speaker notes |
| Images | OCR text |
| HTML / JSON / text / markdown | markdown (a JSON list of records becomes a CSV note) |
| ZIP | expanded first (by `expand`), each entry converted on its own; folders are kept |

Chart numbers come from the chart XML's cached values (what the chart draws), never from a model.
"""

import csv
import io
import json
import logging
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import date, datetime, time
from html.parser import HTMLParser
from pathlib import PurePosixPath
from typing import Any

import yaml

from vicky.config import get_settings
from vicky.kb import ocr

log = logging.getLogger(__name__)

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}
TEXT_EXT = {".txt", ".text", ".md", ".markdown", ".rst", ".log", ".yaml", ".yml", ".xml", ".toml", ".ini"}
KINDS = {".csv": "csv", ".tsv": "csv", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pdf": "pdf", ".docx": "docx",
         ".pptx": "pptx", ".json": "json", ".html": "html", ".htm": "html", ".zip": "zip"}
MAX_TABLE_ROWS = 100_000
MAX_TEXT_CHARS = 2_000_000
MAX_ZIP_ENTRIES = 1000
MIN_FIGURE_CHARS = 6  # OCR output shorter than this (letters/digits) is noise, not a figure


@dataclass
class Draft:
    """A note before it has a path in the vault."""
    name: str               # file name with extension (.md / .csv)
    title: str
    kind: str               # table | document | note
    format: str             # md | csv
    content: str
    folder: str = ""        # from a zip's folders; "" lands in the inbox
    meta: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    summary: str = ""


class Unreadable(Exception):
    pass


# ---------------------------------------------------------------- helpers

def file_kind(filename: str) -> str:
    ext = PurePosixPath(filename.lower()).suffix
    if ext in KINDS:
        return KINDS[ext]
    if ext in IMAGE_EXT:
        return "image"
    if ext in (".md", ".markdown"):
        return "md"
    if ext in TEXT_EXT:
        return "text"
    return "other"


def split_name(filename: str) -> tuple[str, str]:
    """(folder, stem) from a path that may carry folders (zip entries do)."""
    p = PurePosixPath(filename.replace("\\", "/"))
    folder = "/".join(clean_segment(s) for s in p.parent.parts if s not in ("", ".", ".."))
    return folder, clean_segment(p.stem) or "untitled"


def clean_segment(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f#^\[\]]+', " ", s)
    return re.sub(r"\s+", " ", s).strip(" .")[:120]


def safe_name(name: str) -> str:
    """A stored or exported file name: forward slashes, no control characters, and no empty, `.` or `..`
    segment, so it can never point outside the folder it is unzipped into."""
    name = re.sub(r"[\x00-\x1f\x7f]+", "", str(name or "").replace("\\", "/"))
    return "/".join(p for p in name.split("/") if p.strip() not in ("", ".", "..")) or "upload"


def strip_nul(value: Any) -> Any:
    """Postgres text and jsonb can't hold U+0000: drop it from strings, recursively."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [strip_nul(v) for v in value]
    if isinstance(value, dict):
        return {strip_nul(k): strip_nul(v) for k, v in value.items()}
    return value


def _utf16_without_bom(data: bytes) -> str | None:
    """utf-16-le or utf-16-be when NULs fill alternate bytes of the first 1 KB (UTF-16 of mostly-ASCII text)."""
    head = data[:1024]
    if len(head) < 8:
        return None
    even, odd = head[0::2], head[1::2]
    if odd.count(0) >= 0.4 * len(odd) and even.count(0) <= 0.05 * len(even):
        return "utf-16-le"
    if even.count(0) >= 0.4 * len(even) and odd.count(0) <= 0.05 * len(odd):
        return "utf-16-be"
    return None


def decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    enc = _utf16_without_bom(data)
    if enc:
        return data.decode(enc, errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def looks_binary(data: bytes) -> bool:
    head = data[:8000]
    if b"\x00" in head:
        return True
    try:
        head.decode("utf-8")
        return False
    except UnicodeDecodeError as e:
        return e.start < len(head) - 4  # a multi-byte char cut at the edge is fine


def md_escape_cell(v: Any) -> str:
    return str(v if v is not None else "").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def md_table(rows: list[list[Any]]) -> str:
    rows = [r for r in rows if any(str(c or "").strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [[*r, *[""] * (width - len(r))] for r in rows]
    head = "| " + " | ".join(md_escape_cell(c) or " " for c in rows[0]) + " |"
    rule = "|" + "|".join(["---"] * width) + "|"
    body = ["| " + " | ".join(md_escape_cell(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join([head, rule, *body])


def cell_text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == time(0) else v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    return str(v).strip()


def trim_rows(rows: list[list[str]]) -> list[list[str]]:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    width = max((max((i + 1 for i, c in enumerate(r) if c.strip()), default=0) for r in rows), default=0)
    return [[*r[:width], *[""] * (width - len(r[:width]))] for r in rows]


def to_csv(rows: list[list[str]]) -> str:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(rows)
    return out.getvalue()


def tidy_text(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def fenced(text: str, lang: str = "text") -> str:
    fence = "````" if "```" in text else "```"
    return f"{fence}{lang}\n{text.strip()}\n{fence}"


def figure_text_ok(text: str) -> bool:
    return len(re.sub(r"\W", "", text)) >= MIN_FIGURE_CHARS


FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.S)


def split_frontmatter(text: str) -> tuple[dict, str]:
    m = FRONTMATTER.match(text)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return {}, text
    return (data if isinstance(data, dict) else {}), text[m.end():].lstrip("\n")


def first_heading(md: str) -> str | None:
    for ln in md.splitlines()[:12]:
        m = re.match(r"^#\s+(.+?)\s*#*\s*$", ln)
        if m:
            return m.group(1).strip()[:200]
    return None


# ---------------------------------------------------------------- chart XML (DOCX, XLSX, PPTX)

_C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _xml(data: bytes):
    from lxml import etree

    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    return etree.fromstring(data, parser)


def _texts(el) -> str:
    if el is None:
        return ""
    rich = "".join(t.text or "" for t in el.iter(_A + "t"))
    if rich.strip():
        return rich.strip()
    return " ".join((v.text or "").strip() for v in el.iter(_C + "v")).strip()


def _points(el) -> tuple[dict[int, str], str | None]:
    if el is None:
        return {}, None
    pts: dict[int, str] = {}
    for pt in el.iter(_C + "pt"):
        v = pt.find(_C + "v")
        if v is not None and v.text is not None:
            pts[int(pt.get("idx", len(pts)))] = v.text.strip()
    fmt = el.find(f".//{_C}formatCode")
    return pts, (fmt.text.strip() if fmt is not None and fmt.text else None)


def chart_markdown(xml: bytes, label: str) -> str:
    """One chart as a markdown table of the values it draws (the cached series values)."""
    try:
        root = _xml(xml)
    except Exception as e:
        log.info("unreadable chart XML: %s", e)
        return ""
    title = _texts(root.find(f".//{_C}chart/{_C}title"))
    series = []
    refs = []
    for ser in root.iter(_C + "ser"):
        name = _texts(ser.find(_C + "tx")) or f"Series {len(series) + 1}"
        cats, _ = _points(ser.find(_C + "cat") if ser.find(_C + "cat") is not None else ser.find(_C + "xVal"))
        val_el = ser.find(_C + "val") if ser.find(_C + "val") is not None else ser.find(_C + "yVal")
        vals, fmt = _points(val_el)
        if vals:
            series.append((name, cats, vals, fmt))
        elif val_el is not None and val_el.find(f".//{_C}f") is not None:
            refs.append(f"- {name}: plots `{val_el.find(f'.//{_C}f').text}`")
    if not series:
        # No cached values (some writers don't store them): say which cells the chart draws instead.
        if not refs:
            return ""
        return f"### Chart: {title or label}\n\nThe chart stores no values of its own. It plots:\n" + "\n".join(refs)
    idx = sorted({i for _, cats, vals, _ in series for i in (*cats, *vals)})
    cats_all: dict[int, str] = {}
    for _, cats, _, _ in series:
        for i, c in cats.items():
            cats_all.setdefault(i, c)
    rows = [["Category", *[s[0] for s in series]]]
    rows += [[cats_all.get(i, str(i + 1)), *[s[2].get(i, "") for s in series]] for i in idx]
    plot = root.find(f".//{_C}plotArea")
    kinds = sorted({el.tag.replace(_C, "") for el in (plot if plot is not None else []) if el.tag.endswith("Chart")})
    lines = [f"### Chart: {title or label}", ""]
    if kinds:
        lines.append(f"Type: {', '.join(kinds)}. Values as stored in the chart.")
    fmts = {s[3] for s in series if s[3] and s[3] != "General"}
    if fmts:
        lines.append(f"Number format: {', '.join(sorted(fmts))}.")
    lines += ["", md_table(rows)]
    return "\n".join(lines)


def ooxml_charts(data: bytes, prefix: str) -> list[str]:
    """Chart tables from every chart part under `prefix` (word/charts/, xl/charts/) of an Office zip."""
    out = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = sorted(n for n in z.namelist() if n.startswith(prefix) and re.search(r"chart\d*\.xml$", n))
            for i, n in enumerate(names, 1):
                md = chart_markdown(z.read(n), f"chart {i}")
                if md:
                    out.append(md)
    except zipfile.BadZipFile:
        pass
    return out


def ooxml_images_ocr(data: bytes, prefix: str, limit: int = 40) -> list[str]:
    if not ocr.available():
        return []
    out = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in sorted(z.namelist()):
                if n.startswith(prefix) and PurePosixPath(n.lower()).suffix in IMAGE_EXT and len(out) < limit:
                    t = ocr.bytes_text(z.read(n), sparse=True)
                    if figure_text_ok(t):
                        out.append(t)
    except zipfile.BadZipFile:
        pass
    return out


# ---------------------------------------------------------------- per format

def from_csv(stem: str, folder: str, text: str, source: str) -> list[Draft]:
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = trim_rows([[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect)][:MAX_TABLE_ROWS + 1])
    if not rows:
        raise Unreadable("no rows")
    return [Draft(name=f"{stem}.csv", title=stem, kind="table", format="csv", content=to_csv(rows), folder=folder,
                  meta={"source": source, "columns": rows[0], "rows": len(rows) - 1})]


def from_xlsx(stem: str, folder: str, data: bytes, source: str) -> list[Draft]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    drafts = []
    try:
        sheets = wb.worksheets
        for ws in sheets:
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i > MAX_TABLE_ROWS:
                    break
                rows.append([cell_text(v) for v in row])
            rows = trim_rows(rows)
            if not rows:
                continue
            name = stem if len(sheets) == 1 else f"{stem} - {clean_segment(ws.title) or 'sheet'}"
            drafts.append(Draft(name=f"{name}.csv", title=name, kind="table", format="csv", content=to_csv(rows),
                                folder=folder, meta={"source": source, "sheet": ws.title, "columns": rows[0],
                                                     "rows": len(rows) - 1}))
    finally:
        wb.close()
    charts = ooxml_charts(data, "xl/charts/")
    if charts:
        body = f"# {stem}: charts\n\n> Chart data from `{source}`, as stored in the workbook.\n\n" + "\n\n".join(charts)
        drafts.append(Draft(name=f"{stem} - charts.md", title=f"{stem}: charts", kind="document", format="md",
                            content=body, folder=folder, meta={"source": source, "charts": len(charts)}))
    if not drafts:
        raise Unreadable("the workbook has no cells with values")
    return drafts


def from_pdf(stem: str, folder: str, data: bytes, source: str) -> list[Draft]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            reader.decrypt("")
        pages = list(reader.pages)
    except Exception as e:
        raise Unreadable(f"not a readable PDF ({e})") from e
    texts = []
    for p in pages:
        try:
            texts.append(tidy_text(p.extract_text() or ""))
        except Exception:
            texts.append("")
    can_ocr = ocr.available()
    budget = get_settings().ocr_max_pages
    blank = [i + 1 for i, t in enumerate(texts) if len(re.sub(r"\s", "", t)) < 25]
    ocr_text: dict[int, str] = {}
    if can_ocr and blank:
        for n, img in ocr.pdf_pages_as_images(data, blank[:budget]):
            ocr_text[n] = ocr.image_text(img)
    figures: dict[int, list[str]] = {}
    if can_ocr:
        seen = 0
        for n, page in enumerate(pages, 1):
            if n in ocr_text or seen >= budget:
                continue
            try:
                images = list(page.images)
            except Exception:
                continue
            for im in images[:8]:
                try:
                    t = ocr.image_text(im.image, sparse=True)
                except Exception:
                    continue
                seen += 1
                if figure_text_ok(t):
                    figures.setdefault(n, []).append(t)
    unread = [n for n in blank if not ocr_text.get(n, "").strip()]
    head = [f"# {stem}", "", f"> Source: `{source}` · {len(pages)} page{'s' if len(pages) != 1 else ''}"]
    if ocr_text:
        head[-1] += f" · OCR on page{'s' if len(ocr_text) > 1 else ''} {', '.join(map(str, sorted(ocr_text)))}"
    if unread and not can_ocr:
        head[-1] += " · pages without a text layer were not read (OCR isn't installed on this server)"
    body = []
    for n, t in enumerate(texts, 1):
        text = ocr_text.get(n) or t
        body.append(f"## Page {n}")
        body.append(text if text.strip() else "_No text found on this page._")
        for k, fig in enumerate(figures.get(n, []), 1):
            body.append(f"### Figure {k} on page {n} (OCR)")
            body.append(fenced(fig))
    content = "\n\n".join(["\n".join(head), *body])
    return [Draft(name=f"{stem}.md", title=stem, kind="document", format="md", content=content[:MAX_TEXT_CHARS],
                  folder=folder, meta={"source": source, "pages": len(pages), "ocr_pages": sorted(ocr_text),
                                       "figure_pages": sorted(figures), "unread_pages": unread})]


def from_docx(stem: str, folder: str, data: bytes, source: str) -> list[Draft]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        d = docx.Document(io.BytesIO(data))
    except Exception as e:
        raise Unreadable(f"not a readable DOCX ({e})") from e
    parts: list[str] = [f"# {stem}", f"> Source: `{source}`"]
    for child in d.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, d)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name if para.style is not None else "") or ""
            m = re.match(r"Heading (\d)", style)
            if style == "Title":
                parts.append(f"## {text}")
            elif m:
                parts.append(f"{'#' * min(6, int(m.group(1)) + 1)} {text}")
            elif "List" in style:
                parts.append(f"- {text}")
            else:
                parts.append(text)
        elif tag == "tbl":
            t = Table(child, d)
            parts.append(md_table([[c.text.strip() for c in row.cells] for row in t.rows]))
    charts = ooxml_charts(data, "word/charts/")
    if charts:
        parts += ["## Charts", *charts]
    figs = ooxml_images_ocr(data, "word/media/")
    if figs:
        parts += ["## Images (OCR)", *[fenced(f) for f in figs]]
    content = "\n\n".join(p for p in parts if p is not None)
    return [Draft(name=f"{stem}.md", title=stem, kind="document", format="md", content=content[:MAX_TEXT_CHARS],
                  folder=folder, meta={"source": source, "charts": len(charts), "images_ocr": len(figs)})]


def _pptx_shapes(shapes):
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for s in shapes:
        if s.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _pptx_shapes(s.shapes)
        else:
            yield s


def from_pptx(stem: str, folder: str, data: bytes, source: str) -> list[Draft]:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as e:
        raise Unreadable(f"not a readable PPTX ({e})") from e
    parts = [f"# {stem}", f"> Source: `{source}` · {len(prs.slides)} slides"]
    n_charts = n_ocr = 0
    for i, slide in enumerate(prs.slides, 1):
        title_shape = slide.shapes.title
        title = title_shape.text.strip() if title_shape is not None and title_shape.has_text_frame else ""
        parts.append(f"## Slide {i}" + (f": {title}" if title else ""))
        for s in _pptx_shapes(slide.shapes):
            if title_shape is not None and s.shape_id == title_shape.shape_id:
                continue
            if getattr(s, "has_chart", False) and s.has_chart:
                md = chart_markdown(s.chart.part.blob, f"chart on slide {i}")
                if md:
                    parts.append(md)
                    n_charts += 1
            elif getattr(s, "has_table", False) and s.has_table:
                parts.append(md_table([[c.text.strip() for c in row.cells] for row in s.table.rows]))
            elif s.has_text_frame:
                paras = [(p.level, "".join(r.text for r in p.runs).strip()) for p in s.text_frame.paragraphs]
                paras = [(lvl, t) for lvl, t in paras if t]
                if len(paras) == 1:
                    parts.append(paras[0][1])
                elif paras:
                    parts.append("\n".join(f"{'  ' * lvl}- {t}" for lvl, t in paras))
            elif s.shape_type == MSO_SHAPE_TYPE.PICTURE and ocr.available():
                try:
                    t = ocr.bytes_text(s.image.blob, sparse=True)
                except Exception:
                    t = ""
                if figure_text_ok(t):
                    parts.append(f"### Picture on slide {i} (OCR)\n\n{fenced(t)}")
                    n_ocr += 1
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip() if slide.notes_slide.notes_text_frame else ""
            if notes:
                parts.append("> Speaker notes: " + notes.replace("\n", "\n> "))
    content = "\n\n".join(parts)
    return [Draft(name=f"{stem}.md", title=stem, kind="document", format="md", content=content[:MAX_TEXT_CHARS],
                  folder=folder, meta={"source": source, "slides": len(prs.slides), "charts": n_charts,
                                       "images_ocr": n_ocr})]


def from_image(stem: str, folder: str, data: bytes, source: str) -> list[Draft]:
    if not ocr.available():
        body = "_OCR isn't installed on this server, so the text in this image wasn't read._"
        meta = {"source": source, "ocr": False}
    else:
        dense = ocr.bytes_text(data)
        sparse = ocr.bytes_text(data, sparse=True) if len(dense) < 200 else ""
        text = sparse if len(sparse) > len(dense) else dense
        body = fenced(text) if text else "_No text found in this image._"
        meta = {"source": source, "ocr": True}
    content = f"# {stem}\n\n> Source: `{source}` · image, text read by OCR\n\n{body}"
    return [Draft(name=f"{stem}.md", title=stem, kind="document", format="md", content=content, folder=folder, meta=meta)]


class _Html(HTMLParser):
    BLOCK = {"p", "div", "section", "article", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._table: list[list[str]] | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in self.BLOCK:
            self.out.append("\n\n" if tag != "br" else "\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip = max(0, self.skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.out.append("\n\n" + md_table(self._table) + "\n\n")
            self._table = None
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self._in_title:
            self.title += data
        elif self._cell is not None:
            self._cell.append(data)
        elif self._table is None:
            self.out.append(re.sub(r"\s+", " ", data))


def from_html(stem: str, folder: str, text: str, source: str) -> list[Draft]:
    p = _Html()
    p.feed(text)
    body = tidy_text("".join(p.out))
    title = p.title.strip()[:200] or stem
    content = f"# {title}\n\n> Source: `{source}`\n\n{body}"
    return [Draft(name=f"{stem}.md", title=title, kind="document", format="md", content=content[:MAX_TEXT_CHARS],
                  folder=folder, meta={"source": source})]


def from_json(stem: str, folder: str, text: str, source: str) -> list[Draft]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return from_text(stem, folder, text, source, lang="json")
    records = data if isinstance(data, list) else None
    if isinstance(data, dict):
        lists = [v for v in data.values() if isinstance(v, list)]
        records = lists[0] if len(lists) == 1 else None
    if records and all(isinstance(r, dict) for r in records) and all(
            not isinstance(v, dict | list) for r in records for v in r.values()):
        cols: list[str] = []
        for r in records:
            cols += [k for k in r if k not in cols]
        rows = [cols, *[[cell_text(r.get(c)) for c in cols] for r in records[:MAX_TABLE_ROWS]]]
        return [Draft(name=f"{stem}.csv", title=stem, kind="table", format="csv", content=to_csv(rows), folder=folder,
                      meta={"source": source, "columns": cols, "rows": len(rows) - 1})]
    pretty = json.dumps(data, indent=2, ensure_ascii=False)
    return from_text(stem, folder, pretty, source, lang="json")


def from_text(stem: str, folder: str, text: str, source: str, lang: str | None = None) -> list[Draft]:
    if lang:
        content = f"# {stem}\n\n> Source: `{source}`\n\n{fenced(text[:MAX_TEXT_CHARS], lang)}"
        return [Draft(name=f"{stem}.md", title=stem, kind="document", format="md", content=content, folder=folder,
                      meta={"source": source})]
    front, body = split_frontmatter(text)
    title = str(front.get("title") or first_heading(body) or stem)[:200]
    tags = front.get("tags") or []
    tags = [str(t) for t in (tags if isinstance(tags, list) else str(tags).split(","))]
    return [Draft(name=f"{stem}.md", title=title, kind="note", format="md", content=body[:MAX_TEXT_CHARS],
                  folder=folder, meta={"source": source}, tags=tags, summary=str(front.get("summary") or "")[:500])]


# ---------------------------------------------------------------- entry points

def expand(filename: str, data: bytes) -> list[tuple[str, bytes]]:
    """A zip's entries as (path inside the zip, bytes); any other file as itself. Guards zip bombs."""
    if file_kind(filename) != "zip":
        return [(filename, data)]
    cap = get_settings().kb_unzip_max_bytes
    out: list[tuple[str, bytes]] = []
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = [i for i in z.infolist() if not i.is_dir()]
            for info in infos[:MAX_ZIP_ENTRIES]:
                name = info.filename.replace("\\", "/")
                parts = PurePosixPath(name).parts
                if any(p.startswith(".") and p != ".vicky" for p in parts) or "__MACOSX" in parts:
                    continue
                total += info.file_size
                if total > cap:
                    raise Unreadable(f"{filename} expands to more than {cap // (1024 * 1024)} MB")
                out.append((name, z.read(info)))
    except zipfile.BadZipFile as e:
        raise Unreadable(f"{filename} is not a valid zip") from e
    except RuntimeError as e:  # zipfile's "is encrypted, password required"
        raise Unreadable(f"{filename} is encrypted; export it without a password") from e
    except NotImplementedError as e:  # Deflate64, LZMA variants zipfile can't read
        raise Unreadable(f"{filename} uses a compression method that can't be read; re-zip it") from e
    except (zlib.error, EOFError, ValueError, OSError) as e:
        raise Unreadable(f"{filename} is damaged ({e})") from e
    return out


def convert(filename: str, data: bytes) -> list[Draft]:
    """Notes made from one file (not a zip: `expand` first). Raises Unreadable."""
    drafts = _convert(filename, data)
    for d in drafts:  # one NUL anywhere would fail the whole insert
        d.name, d.title, d.content, d.folder = (strip_nul(d.name), strip_nul(d.title), strip_nul(d.content),
                                                strip_nul(d.folder))
        d.summary, d.tags, d.meta = strip_nul(d.summary), strip_nul(d.tags), strip_nul(d.meta)
    return drafts


def _convert(filename: str, data: bytes) -> list[Draft]:
    folder, stem = split_name(filename)
    source = PurePosixPath(filename.replace("\\", "/")).name
    kind = file_kind(filename)
    if kind == "csv":
        return from_csv(stem, folder, decode(data), source)
    if kind == "xlsx":
        return from_xlsx(stem, folder, data, source)
    if kind == "pdf":
        return from_pdf(stem, folder, data, source)
    if kind == "docx":
        return from_docx(stem, folder, data, source)
    if kind == "pptx":
        return from_pptx(stem, folder, data, source)
    if kind == "image":
        return from_image(stem, folder, data, source)
    if kind == "html":
        return from_html(stem, folder, decode(data), source)
    if kind == "json":
        return from_json(stem, folder, decode(data), source)
    if kind == "md" or PurePosixPath(filename.lower()).suffix in (".txt", ".text"):
        return from_text(stem, folder, decode(data), source)
    if kind == "text":
        lang = PurePosixPath(filename.lower()).suffix.lstrip(".")
        return from_text(stem, folder, decode(data), source, lang=lang)
    if not looks_binary(data):
        return from_text(stem, folder, decode(data), source, lang="text")
    raise Unreadable(f"{source}: no text could be read from this file type")
