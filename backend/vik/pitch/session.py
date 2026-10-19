"""The pitch room (docs/04-APP-FLOW.md §5): deck → present out loud → live interrupts or Q&A after → wrap-up.

Deck: a PDF's pages are rendered to JPEG for the browser (never stored) and their text is read; a PowerPoint's
slides are read as text (title and lines). The deck never enters the knowledge base. Every slide gets two
checks: its numeric claims against the TruthPack by `check_claim` (the result becomes the TruthPack's deck
claims, so the attack list and every court see them), and its statements against the founder's own knowledge
base by retrieval (`vik.pitch.verify`: supported, contradicted, new or unclear, with a verbatim note quote).

Presenting: the browser commits a transcript segment at each pause, tagged with the slide on screen. Each
segment's claims are extracted and checked in code and added to the ledger, and its statements are checked
against the notes. In live mode a contradiction of the data or of the notes (or a forecast stated as fact) is
an interrupt candidate, scored in code as severity × the investor's
interrupt tendency × lane fit; at most one per slide and none within the cooldown. The interrupting line is
written by code from the check, so the figure it quotes is the engine's. The founder's spoken reply is judged
and the investor hands the floor back.

End: live mode closes with Vik's wrap-up; after mode stores the spoken claims beside the deck's and opens a
court session in `simulate` mode, whose Q&A the browser runs by voice on the court routes. Its questions are the
panel's own (market, retention, runway …) plus the discrepancies: each statement the notes contradict or don't
cover becomes a question the founder must explain (perhaps the claim is new and justified).

Hot state lives in Redis under `vik:pitch:{id}` (6 h), the deck under `vik:deck:{id}`; nothing here is
durable except what the court stores.
"""

import asyncio
import base64
import io
import logging
import re
import time
import uuid
from typing import Any

from vik import kv
from vik.areopagus import registry
from vik.areopagus.schema import VCPersona
from vik.audit import audit_text
from vik.court import minds
from vik.court import session as court
from vik.llm import minds as agents
from vik.model.context import TruthContext
from vik.model.truth import _lc, check_claim
from vik.pitch import verify, voice
from vik.services import engagements

log = logging.getLogger(__name__)

TTL_S = 6 * 3600
MAX_PAGES = 40
SLIDE_WIDTH_PX = 1280
SLIDE_TEXT_CHARS = 2000
COOLDOWN_MS = 30_000
PER_SLIDE = 1
QA_QUESTIONS = 6
# Severity of a claim by status; `unsupported` stays under the interrupt bar (it's asked about after).
SEVERITY = {"contradicts": 1.0, "forecast_as_fact": 0.7, "unsupported": 0.3}
# A statement the founder's own notes contradict is as serious as a figure the data contradicts; one the notes
# don't cover is asked about after the pitch, never interrupted.
KB_SEVERITY = {"contradicted": 0.9}
KB_QUESTIONS = 4  # the most knowledge-base discrepancies the Q&A asks about
INTERRUPT_BAR = 0.12
FILLERS = re.compile(r"\b(um+|uh+|erm+|er|you know|basically|kind of|sort of|i mean)\b", re.I)
OPENERS = {
    "blunt": "Stop there.",
    "dry_exacting": "One correction before you go on.",
    "calm_precise": "Let me pause you there.",
    "analytical": "Let me pause you there.",
    "quiet_probing": "Can I stop you for a second?",
    "warm_conversational": "Sorry to jump in.",
    "genial_hard_nosed": "Sorry to jump in.",
}


class PitchError(Exception):
    pass


def _key(pid: str) -> str:
    return f"vik:pitch:{pid}"


def _deck_key(did: str) -> str:
    return f"vik:deck:{did}"


# ---------------------------------------------------------------- deck


def read_deck(data: bytes, filename: str = "") -> list[dict]:
    """Each slide as {n, text, image (JPEG data URL or None), title, bullets}: a PDF or a PowerPoint.
    Blocking: run it in a thread."""
    if data.startswith(b"%PDF"):
        return read_pdf(data)
    if data.startswith(b"PK") and (filename.lower().endswith(".pptx") or b"ppt/" in data[:4000]):
        return read_pptx(data)
    raise PitchError("Upload the deck as a PDF or a PowerPoint (.pptx) file.")


def _chart_lines(chart) -> list[str]:
    """A chart's series as "name: category value, …" from its cached values (what the chart draws)."""
    try:
        cats = list(chart.plots[0].categories) if chart.plots else []
        out = []
        for series in chart.series:
            vals = ", ".join(
                f"{c}: {v:g}" for c, v in zip(cats, series.values, strict=False) if v is not None
            )
            if vals:
                out.append(f"{series.name or 'Chart'}: {vals}")
        return out
    except Exception:  # a chart without cached values has nothing to read
        return []


def read_pptx(data: bytes) -> list[dict]:
    """Each slide's text in reading order: title, text frames, tables and chart data. Speaker notes are left
    out (the panel checks what is shown and said). A PowerPoint isn't rendered to an image on the server, so
    the stage shows the slide's title and lines."""
    from pptx import Presentation

    from vik.kb.convert import _pptx_shapes

    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as e:
        raise PitchError("That file isn't a PowerPoint the deck reader can open.") from e
    if len(prs.slides) == 0:
        raise PitchError("That deck has no slides.")
    if len(prs.slides) > MAX_PAGES:
        raise PitchError(f"Decks are limited to {MAX_PAGES} slides.")
    out = []
    for i, slide in enumerate(prs.slides, 1):
        ts = slide.shapes.title
        title = ts.text.strip() if ts is not None and ts.has_text_frame else ""
        lines: list[str] = []
        for sh in _pptx_shapes(slide.shapes):
            if ts is not None and sh.shape_id == ts.shape_id:
                continue
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        lines.append(" · ".join(cells))
            elif getattr(sh, "has_chart", False) and sh.has_chart:
                lines += _chart_lines(sh.chart)
            elif sh.has_text_frame:
                lines += [ln.strip() for ln in sh.text_frame.text.splitlines() if ln.strip()]
        # One line per bullet, so each is its own statement for the checks.
        text = "\n".join(re.sub(r"\s+", " ", ln).strip() for ln in [title, *lines] if ln.strip())
        out.append(
            {
                "n": i,
                "text": text[:SLIDE_TEXT_CHARS],
                "image": None,
                "title": title[:200],
                "bullets": lines[:30],
            }
        )
    return out


def read_pdf(data: bytes) -> list[dict]:
    """Each page as {n, text, image (JPEG data URL)}. Blocking: run it in a thread."""
    import pypdfium2 as pdfium

    from vik.kb.ocr import render_scale

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as e:  # pdfium raises its own error type for anything it can't open
        raise PitchError("That file isn't a PDF the deck reader can open.") from e
    try:
        if len(pdf) == 0:
            raise PitchError("That PDF has no pages.")
        if len(pdf) > MAX_PAGES:
            raise PitchError(f"Decks are limited to {MAX_PAGES} slides.")
        out = []
        for i in range(len(pdf)):
            page = pdf[i]
            try:
                w, h = page.get_size()
                img = page.render(scale=render_scale(w, h, SLIDE_WIDTH_PX / max(w, 1.0))).to_pil()
                buf = io.BytesIO()
                img.convert("RGB").save(buf, "JPEG", quality=82, optimize=True)
                tp = page.get_textpage()
                try:
                    raw = tp.get_text_range()
                    # Lines kept (a slide's bullets are separate statements), spaces within them squashed.
                    text = "\n".join(
                        ln for ln in (re.sub(r"[^\S\n]+", " ", x).strip() for x in raw.splitlines()) if ln
                    )
                finally:
                    tp.close()
                out.append(
                    {
                        "n": i + 1,
                        "text": text[:SLIDE_TEXT_CHARS],
                        "image": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
                    }
                )
            finally:
                page.close()
        return out
    finally:
        pdf.close()


async def _checks(text: str, ctx: TruthContext) -> list[dict]:
    """The text's numeric claims, each checked against the TruthPack by code."""
    if not text.strip():
        return []
    out = []
    for c in await agents.extract_claims(text):
        r = check_claim(
            c["metric"],
            c["value"],
            c["unit"],
            ctx.figures,
            period=c.get("period"),
            is_forecast=c.get("is_forecast", False),
            facts=ctx.facts,
        )
        out.append(
            {
                **r.model_dump(mode="json"),
                "text": c["text"],
                "period": c.get("period"),
                "is_forecast": bool(c.get("is_forecast", False)),
            }
        )
    return out


def _stored(c: dict) -> dict:
    """A check as a TruthPack deck claim (the attack list re-checks it at every context build)."""
    return {k: c.get(k) for k in ("text", "metric", "value", "unit", "period", "is_forecast")}


def _ledger_row(c: dict, slide: int | None, source: str, t_ms: int | None = None) -> dict:
    fig = c.get("figure") or {}
    return {
        "id": uuid.uuid4().hex[:10],
        "slide": slide,
        "source": source,  # "deck" (pre-scan) or "spoken"
        "t_ms": t_ms,
        "text": c.get("text") or "",
        "metric": c.get("metric"),
        "value": c.get("value"),
        "unit": c.get("unit"),
        "status": c["status"],
        "explanation": c.get("explanation") or "",
        "figure_id": c.get("figure_id"),
        "truth": fig.get("display"),
        "truth_label": fig.get("label"),
    }


def _kb_row(k: dict, slide: int | None, source: str, t_ms: int | None = None) -> dict:
    """A statement checked against the knowledge base, as the pitch keeps it."""
    return {
        "id": uuid.uuid4().hex[:10],
        "slide": slide,
        "source": source,  # "deck" or "spoken"
        "t_ms": t_ms,
        "text": k["text"],
        "topic": k.get("topic") or "",
        "verdict": k["verdict"],  # supported | contradicted | new | unclear
        "quote": k.get("quote") or "",
        "path": k.get("path"),
        "cite": k.get("cite"),
        "why": k.get("why") or "",
        "chunk": k.get("chunk"),
    }


async def _scan(text: str, ctx: TruthContext) -> tuple[list[dict], list[dict]]:
    """Both checks of a slide or a spoken segment, at once: its figures against the metrics engine, its
    statements against the knowledge base."""
    checks, kb = await asyncio.gather(_checks(text, ctx), verify.check(text))
    return checks, kb


async def add_deck(data: bytes, filename: str) -> dict:
    """Read and check a deck. It is never added to the knowledge base: it is what the vault is checked against."""
    eid = await engagements.require_confirmed()
    ctx = await engagements.context(eid)
    pages = await asyncio.to_thread(read_deck, data, filename)
    sem = asyncio.Semaphore(4)

    async def scan(p: dict) -> tuple[list[dict], list[dict]]:
        async with sem:
            return await _scan(p["text"], ctx)

    scanned = await asyncio.gather(*(scan(p) for p in pages))
    did = uuid.uuid4().hex
    slides = [
        {
            "n": p["n"],
            "text": p["text"],
            "title": p.get("title") or "",
            "bullets": p.get("bullets") or [],
            "claims": [_ledger_row(c, p["n"], "deck") for c in cs],
            "kb": [_kb_row(k, p["n"], "deck") for k in ks],
        }
        for p, (cs, ks) in zip(pages, scanned, strict=True)
    ]
    stored = [_stored(c) for cs, _ in scanned for c in cs]
    await kv.set_json(
        _deck_key(did),
        {"id": did, "engagement_id": eid, "filename": filename, "slides": slides, "stored": stored},
        TTL_S,
    )
    await engagements.set_deck_claims(eid, stored)
    return {
        "id": did,
        "filename": filename,
        "kind": "pdf" if data.startswith(b"%PDF") else "pptx",
        "slides": [{**s, "image": p["image"]} for s, p in zip(slides, pages, strict=True)],
    }


# ---------------------------------------------------------------- presenting


async def load(pid: str) -> dict:
    st = await kv.get_json(_key(pid))
    if st is None:
        raise engagements.NotFound("pitch")
    return st


async def _save(st: dict) -> None:
    await kv.set_json(_key(st["id"]), st, TTL_S)


def view(st: dict) -> dict:
    return {k: v for k, v in st.items() if k not in ("engagement_id", "stored")}


def _chair_open(panel: list[VCPersona], mode: str, deck: bool) -> str:
    names = ", ".join(p.name for p in panel[:-1]) + (
        f" and {panel[-1].name}" if len(panel) > 1 else panel[0].name
    )
    how = (
        "If something you say doesn't match your data, one of them will stop you and ask."
        if mode == "live"
        else "They'll hold their questions until you finish. Press End when you're done."
    )
    slides = " Move through your slides as you speak." if deck else ""
    return f"I'm Vik, chairing. {names} are listening. The floor is yours.{slides} {how}"


async def begin(mode: str, panel_ids: list[str] | None, deck_id: str | None) -> dict:
    eid = await engagements.require_confirmed()
    panel = await registry.panel(panel_ids)
    if not panel:
        raise PitchError("Seat at least one investor.")
    mode = mode if mode in ("live", "after") else "after"
    deck = await kv.get_json(_deck_key(deck_id)) if deck_id else None
    if deck_id and deck is None:
        raise PitchError("That deck has expired. Upload it again.")
    st: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "engagement_id": eid,
        "mode": mode,
        "status": "presenting",  # → answering (an interrupt is open) → presenting … → qa | ended
        "panel": [p.id for p in panel],
        "deck_id": deck_id,
        "slides": len(deck["slides"]) if deck else 0,
        "started_at": time.time(),
        "segments": [],
        "ledger": [c for s in deck["slides"] for c in s["claims"]] if deck else [],
        "kb": [k for s in deck["slides"] for k in s.get("kb", [])] if deck else [],
        "stored": deck["stored"] if deck else [],
        "interrupts": [],
        "pending": None,
        "last_interrupt_ms": None,
        "court_id": None,
        "stats": None,
        # Each seat's voice for this sitting: the archetype's, never one a panel-mate (or Vik) has.
        "voices": voice.cast(panel),
        "say": [{"speaker": "vik", "text": _chair_open(panel, mode, bool(deck))}],
    }
    await _save(st)
    return view(st)


def _interrupt_line(p: VCPersona, c: dict, said: str, ctx: TruthContext) -> str:
    """At most two sentences, written by code from the claim check: the figure is the engine's."""
    opener = OPENERS.get(p.style.tone, "Let me stop you there.")
    quote = (c.get("text") or "").strip().rstrip(".")
    fig = c.get("figure") or {}
    if c["status"] == "contradicts" and fig.get("label") and fig.get("display"):
        text = (
            f'{opener} You said "{quote}", but your data says {_lc(fig["label"])} is {fig["display"]}; '
            "which one is right?"
        )
        if minds.passes(text, ctx, [said]):
            return text
    if c["status"] == "forecast_as_fact":
        text = f'{opener} "{quote}" sounds like the plan, not something that has happened. What has actually happened so far?'
        if minds.passes(text, ctx, [said]):
            return text
    return f"{opener} That doesn't match the data you gave us. Where does that number come from?"


def _kb_line(
    p: VCPersona, k: dict, said: str, ctx: TruthContext, notes: dict[str, dict] | None = None
) -> str:
    """The interrupt for a statement the founder's own notes contradict, written by code: the note is quoted
    word for word (the verifier checked it is in the note), with its cite token. `notes` (path → note) lets
    the audit check the quote against the note itself."""
    opener = OPENERS.get(p.style.tone, "Let me stop you there.")
    claim = k["text"].strip().rstrip(".")
    if k.get("quote") and k.get("cite"):
        text = (
            f'{opener} You said "{claim}", but your own notes say "{k["quote"]}" {k["cite"]}. '
            "Which is right, and what changed?"
        )
        if notes and audit_text(text, ctx.available(), [said], notes=notes).passed:
            return text
    return f"{opener} That isn't what your own notes say. Which is right, and what changed?"


def _candidate(
    panel: list[VCPersona], checks: list[dict], kb: list[dict] | None = None
) -> tuple[VCPersona, dict, float] | None:
    """The strongest interrupt: a figure check (it has `status`) or a notes check (it has `verdict`)."""
    best = None
    items = [(c, SEVERITY.get(c["status"], 0.0), _lens_of(c)) for c in checks]
    items += [(k, KB_SEVERITY.get(k["verdict"], 0.0), "claims") for k in kb or []]
    for c, sev, lens in items:
        for p in panel:
            lane = 0.4 + 0.6 * max(p.weight("claims"), p.weight(lens))
            score = sev * p.style.interrupt_tendency * lane
            if best is None or score > best[2]:
                best = (p, c, score)
    return best if best and best[2] >= INTERRUPT_BAR else None


def _lens_of(c: dict) -> str:
    m = str(c.get("metric") or "").lower()
    if any(w in m for w in ("churn", "retention", "nrr", "grr")):
        return "retention"
    if any(w in m for w in ("runway", "cash", "burn")):
        return "runway"
    if any(w in m for w in ("margin", "cac", "ltv", "payback")):
        return "unit_economics"
    if any(w in m for w in ("growth", "arr", "mrr", "revenue")):
        return "forecast"
    return "claims"


async def segment(pid: str, text: str, slide: int | None, t_ms: int) -> dict:
    st = await load(pid)
    if st["status"] not in ("presenting", "answering"):
        raise PitchError("The presentation is over.")
    text = text.strip()[:4000]
    ctx = await engagements.context(st["engagement_id"])
    checks, kb = await _scan(text, ctx)
    st = await load(pid)  # the claim calls take a moment; build on what's stored now
    rows = [_ledger_row(c, slide, "spoken", t_ms) for c in checks]
    kb_rows = [_kb_row(k, slide, "spoken", t_ms) for k in kb]
    st["segments"].append({"slide": slide, "t_ms": t_ms, "text": text})
    st["ledger"] += rows
    st.setdefault("kb", []).extend(kb_rows)
    st["stored"] += [_stored(c) for c in checks]
    interrupt = None
    last = st["last_interrupt_ms"]
    cooled = last is None or t_ms - last >= COOLDOWN_MS
    on_slide = sum(1 for i in st["interrupts"] if i["slide"] == slide)
    if st["mode"] == "live" and st["status"] == "presenting" and cooled and on_slide < PER_SLIDE:
        panel = await registry.panel(st["panel"], strict=False)
        if (cand := _candidate(panel, checks, kb)) is not None:
            p, c, score = cand
            on_notes = "verdict" in c
            notes = await court._notes_for([c["chunk"]]) if on_notes and c.get("chunk") else None
            interrupt = {
                "id": uuid.uuid4().hex[:10],
                "speaker": p.id,
                "text": _kb_line(p, c, text, ctx, notes) if on_notes else _interrupt_line(p, c, text, ctx),
                "slide": slide,
                "t_ms": t_ms,
                "on": "notes" if on_notes else "data",
                "claim": next(r for r, k in zip(kb_rows, kb, strict=True) if k is c)
                if on_notes
                else next(r for r, k in zip(rows, checks, strict=True) if k is c),
                "score": round(score, 3),
                "reply": None,
                "judged": None,
            }
            st["interrupts"].append(interrupt)
            st["pending"] = interrupt["id"]
            st["last_interrupt_ms"] = t_ms
            st["status"] = "answering"
    await _save(st)
    return {"claims": rows, "kb": kb_rows, "interrupt": interrupt, "pitch": view(st)}


def _hand_back(checks: list[dict], said: str = "") -> str:
    if any(c["status"] == "contradicts" for c in checks):
        return "That still doesn't square with your data. We'll come back to it; carry on."
    if checks and all(c["status"] == "matches" for c in checks):
        return "That matches your data. Thank you, carry on."
    if not checks and not re.search(r"\d", said):
        return "I'd want the number behind that. Noted; keep going."
    return "Noted. Keep going."


async def reply(pid: str, text: str) -> dict:
    st = await load(pid)
    if st["status"] != "answering" or not st["pending"]:
        raise PitchError("Nobody asked a question.")
    it = next(i for i in st["interrupts"] if i["id"] == st["pending"])
    ctx = await engagements.context(st["engagement_id"])
    text = text.strip()[:4000]
    checks = await _checks(text, ctx)
    score = await agents.judge(text, None, checks, ctx, it["text"])
    st = await load(pid)
    it = next(i for i in st["interrupts"] if i["id"] == st["pending"])
    it["reply"] = text
    it["judged"] = score
    it["hand_back"] = _hand_back(checks, text)
    st["ledger"] += [_ledger_row(c, it["slide"], "spoken") for c in checks]
    st["stored"] += [_stored(c) for c in checks]
    st["pending"] = None
    st["status"] = "presenting"
    await _save(st)
    return {"say": [{"speaker": it["speaker"], "text": it["hand_back"]}], "score": score, "pitch": view(st)}


def discrepancies(kb: list[dict]) -> list[dict]:
    """What the Q&A asks the founder to explain: statements their own notes contradict first, then claims the
    notes don't cover (news since, or unfounded); one question per statement, at most KB_QUESTIONS."""
    seen: set[str] = set()
    out = []
    for verdict in ("contradicted", "new"):
        for k in kb:
            key = re.sub(r"\W+", " ", k["text"].lower()).strip()
            if k["verdict"] != verdict or key in seen:
                continue
            seen.add(key)
            out.append(k)
    return out[:KB_QUESTIONS]


def delivery(st: dict) -> dict:
    words = sum(len(re.findall(r"\w+", s["text"])) for s in st["segments"])
    fillers = sum(len(FILLERS.findall(s["text"])) for s in st["segments"])
    return {"words": words, "fillers": fillers}


def _wrap_up(st: dict) -> str:
    """Vik's spoken close in live mode; the counts come from the ledger."""
    spoken = [r for r in st["ledger"] if r["source"] == "spoken"]
    bad = sum(1 for r in spoken if r["status"] in ("contradicts", "forecast_as_fact"))
    asked = len(st["interrupts"])
    if not spoken:
        claims = "You didn't put a number on anything you said, which the panel will notice."
    elif not bad:
        claims = "Every figure you said out loud held up against your data."
    elif len(spoken) == 1:
        claims = "The one figure you said out loud didn't hold up against your data."
    elif bad == len(spoken):
        claims = "None of the figures you said out loud held up against your data."
    else:
        claims = f"{bad} of the {len(spoken)} figures you said out loud didn't hold up against your data."
    stops = (
        "Nobody had to stop you."
        if not asked
        else "You were stopped once."
        if asked == 1
        else f"You were stopped {asked} times."
    )
    kb = st.get("kb") or []
    off = sum(1 for k in kb if k["verdict"] == "contradicted")
    notes = (
        ""
        if not kb
        else " Everything you said and showed squared with your own notes."
        if not off
        else " One statement didn't match your own notes."
        if off == 1
        else f" {off} statements didn't match your own notes."
    )
    return (
        f"That's the pitch. {claims}{notes} {stops} The ledger on the right has every claim and what your "
        "data and notes say."
    )


async def end(pid: str) -> dict:
    st = await load(pid)
    if st["status"] in ("qa", "ended"):
        return {"pitch": view(st), "court": await court.view(st["court_id"]) if st["court_id"] else None}
    st["stats"] = delivery(st)
    if st["mode"] == "live":
        st["status"] = "ended"
        st["pending"] = None
        st["say"] = [{"speaker": "vik", "text": _wrap_up(st)}]
        await _save(st)
        return {"pitch": view(st), "court": None}
    # After mode: what was said joins the deck's claims on the TruthPack, then the panel's Q&A opens.
    await engagements.set_deck_claims(st["engagement_id"], st["stored"])
    sid = await court.start(
        st["panel"],
        QA_QUESTIONS,
        "coached",
        None,
        knowledge_on=False,
        discrepancies=discrepancies(st.get("kb") or []),
    )
    st["status"] = "qa"
    st["court_id"] = sid
    await _save(st)
    return {"pitch": view(st), "court": await court.view(sid)}
