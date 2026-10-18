"""Ask Vicky over the knowledge-base index (docs/08-RAG.md §Ask Vicky).

After the deterministic answer, along these paths in order:
0. the answer caches (exact, then a guarded semantic match);
1. first-pass retrieval: when confident, Haiku answers from the passages;
2. a wider recovery pass, the same way;
3. when the notes are needed and still not found: an **offer** of the catch-all (Haiku over the whole vault).
   Nothing runs until the user accepts it (`accept_offer`); the miss is logged either way;
4. the offline answer, plus verbatim quotes of the best passages when the data has none.

Every model-written reply is held to `audit_text(..., notes=…, require_citations=True)`: each statement
cites a computed figure or quotes a note word for word with its `[kb:path]`, or the reply isn't used.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from vicky import db, kv
from vicky.audit import audit_text
from vicky.config import get_settings
from vicky.kb import rag
from vicky.kb.bm25 import tokens
from vicky.kb.index import has_vector, kb_version, vectors_on
from vicky.kb.tools import Vault, excerpts, terms
from vicky.model.context import TruthContext

log = logging.getLogger(__name__)
ANS_TTL_S = 24 * 3600
OFFER_TTL_S = 15 * 60
SEMANTIC_MIN = 0.95
QUOTE_MIN_COVER = 0.5  # quote passages without a model only when they cover most of the question
TIMEOUT_S = 25
FULL_TIMEOUT_S = 60

RAG_SYSTEM = """You are Vicky, answering a founder's question about their own company from two sources: the \
computed figures in <data> and passages of the founder's own knowledge base in <passages>.
Every sentence you write must carry a citation:
- a number from <data>, written exactly as it appears there (same rounding and units), or
- a passage quoted word for word inside double quotes, followed by its cite token, e.g. "exact words" [kb:folder/Note.md].
A number from a passage may appear only inside such a quote: never restate, round, convert or compute it.
If you can't cite a statement, leave it out. Never estimate, invent a number or a benchmark, and never give \
valuation or investment advice.
Set answerable to false when the data and the passages don't answer the question; then keep reply to one \
short sentence. Otherwise answer in at most four short sentences of plain prose, no lists, no markdown."""

FULL_RULES = """<vault> below holds every note of the founder's knowledge base. The same citation rules apply: \
quote a note word for word inside double quotes followed by [kb:its path]."""


# ---------------------------------------------------------------- helpers

def _guard(question: str) -> str:
    """What must match for two questions to share a cached answer: digits, periods and finance terms."""
    toks = tokens(question)
    vocab = {t for g in rag._glossary() for m in g for t in m}
    keep = {t for t in toks if any(ch.isdigit() for ch in t) or re.fullmatch(r"q[1-4]|h[12]|fy\d*", t)
            or t[:3] in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
            or t in vocab}
    return " ".join(sorted(keep))


def _guard_key(ctx: TruthContext, question: str) -> str:
    """The semantic cache's guard: the dashboard's currency (figures are converted to it) and the question's
    digits, periods and finance terms."""
    return f"{ctx.currency}|{_guard(question)}"


def _key(build: str, kbv: int, ctx: TruthContext, question: str) -> str:
    return (f"rag:ans:{build}:{kbv}:{ctx.truthpack_id}:{ctx.version}:{ctx.currency}:"
            f"{rag._sha(rag.normalize(question))}")


def _chunk_block(chunks: list[dict]) -> str:
    out = []
    for c in chunks:
        ctx_lines = "".join(f"\n<context>{t}</context>" for t in c.get("context") or [])
        out.append(f'<passage cite="{c["cite"]}" note="{c["path"]}" heading="{c["heading"]}">\n{c["text"]}{ctx_lines}\n</passage>')
    return "<passages>\n" + "\n".join(out) + "\n</passages>"


async def link_figures(citations: list[dict], ctx: TruthContext) -> list[dict]:
    """Name the knowledge-base note behind each figure citation (the table or document Fill dashboard sent
    to intake): `source.kb_note = {id, path}`."""
    ds = {c["source"].get("dataset_id") for c in citations if c.get("figure_id") and isinstance(c.get("source"), dict)}
    refs = {c["source"].get("ref") for c in citations if c.get("figure_id") and isinstance(c.get("source"), dict)}
    ds.discard(None)
    refs.discard(None)
    if not (ds or refs) or not ctx.engagement_id:
        return citations
    try:
        rows = await db.fetch(
            """select d.id::text as dataset_id, u.filename, n.id::text as note_id, n.path
               from uploads u join kb_notes n on n.id = u.kb_note_id
               left join datasets d on d.upload_id = u.id
               where u.engagement_id = $1::uuid""", ctx.engagement_id)
    except Exception as e:
        log.info("could not link figures to notes: %s", e)
        return citations
    by_ds = {r["dataset_id"]: r for r in rows if r["dataset_id"]}
    by_file = {r["filename"]: r for r in rows}
    for c in citations:
        src = c.get("source")
        if not c.get("figure_id") or not isinstance(src, dict):
            continue
        r = by_ds.get(src.get("dataset_id")) or by_file.get(src.get("ref") or "")
        if r:
            src["kb_note"] = {"id": r["note_id"], "path": r["path"]}
    return citations


# ---------------------------------------------------------------- caches

async def cached(question: str, ctx: TruthContext, build: str, kbv: int) -> dict | None:
    hit = None
    try:
        hit = await kv.get_json(_key(build, kbv, ctx, question))
    except Exception:
        pass
    if hit:
        await rag.stat("ans_hit")
        return {**hit, "rag": {**(hit.get("rag") or {}), "cache": "exact"}}
    if not (vectors_on() and await has_vector()):
        return None
    vec = await rag.query_vector(question)
    if vec is None:
        return None
    from vicky.kb.voyage import to_pg

    row = await db.fetchrow(
        """select answer, 1 - (embedding <=> $6::halfvec) as sim from qa_cache
           where build_id = $1::uuid and kb_version = $2 and truthpack_id is not distinct from $3::uuid
             and truthpack_version is not distinct from $4 and guard = $5 and created_at > now() - interval '24 hours'
           order by embedding <=> $6::halfvec limit 1""",
        build, kbv, ctx.truthpack_id, ctx.version, _guard_key(ctx, question), to_pg(vec))
    if row and float(row["sim"]) >= SEMANTIC_MIN:
        await rag.stat("ans_semantic_hit")
        ans = row["answer"]
        return {**ans, "rag": {**(ans.get("rag") or {}), "cache": "semantic"}}
    await rag.stat("ans_miss")
    return None


async def remember(question: str, ctx: TruthContext, build: str, kbv: int, out: dict) -> None:
    keep = {k: v for k, v in out.items() if k != "offer"}
    try:
        await kv.set_json(_key(build, kbv, ctx, question), keep, ANS_TTL_S)
    except Exception:
        pass
    if not (vectors_on() and await has_vector()):
        return
    vec = await rag.query_vector(question)
    if vec is None:
        return
    from vicky.kb.voyage import to_pg

    try:
        await db.execute("delete from qa_cache where created_at < now() - interval '24 hours'")
        await db.execute(
            """insert into qa_cache (build_id, kb_version, truthpack_id, truthpack_version, question, question_norm,
                                     guard, answer, embedding)
               values ($1::uuid, $2, $3::uuid, $4, $5, $6, $7, $8, $9::halfvec)""",
            build, kbv, ctx.truthpack_id, ctx.version, question[:500], rag.normalize(question)[:500],
            _guard_key(ctx, question),
            json.loads(json.dumps(keep, default=str)), to_pg(vec))
    except Exception as e:
        log.info("semantic cache write failed: %s", e)


# ---------------------------------------------------------------- answers

async def _ask_model(route: str, system: list[str], content: str, ctx: TruthContext, vault: Vault,
                     extra: list) -> tuple[str | None, bool | None, Any]:
    """(reply, answerable, audit result). One regeneration with the findings when the audit fails."""
    from vicky.llm.client import LLMError, get_llm, with_timeout
    from vicky.llm.schemas import RagReply

    messages: list[dict] = [{"role": "user", "content": content}]
    res = None
    for attempt in range(2):
        try:
            r = await with_timeout(get_llm().parse(route, RagReply, system=system, messages=messages),
                                   FULL_TIMEOUT_S if route == "qa_full" else TIMEOUT_S)
        except LLMError as e:
            log.info("%s failed: %s", route, e)
            return None, None, res
        if not r.answerable:
            return None, False, res
        text = r.reply.strip()
        res = audit_text(text, ctx.available() + extra, notes=vault.notes(), require_citations=True)
        if text and res.passed:
            return text, True, res
        if attempt == 0:
            messages += [{"role": "assistant", "content": json.dumps({"answerable": True, "reply": text})},
                         {"role": "user", "content": "That reply failed the citation audit: "
                          f"{res.feedback() or 'it was empty'}. Rewrite it so every sentence cites a figure from "
                          "<data> or quotes a passage word for word with its [kb:path]; drop anything you can't cite."}]
    return None, True, res


async def _done(text: str, res: Any, offline: dict, ctx: TruthContext, meta: dict) -> dict:
    from vicky.qa import _with_notes

    cites = await link_figures([c.model_dump(mode="json") for c in res.citations], ctx)
    out = {**offline, "reply": text, "citations": cites, "audit": {"passed": True, "findings": []}, "llm": True,
           "rag": meta}
    return _with_notes(out, res)


async def from_chunks(question: str, ctx: TruthContext, offline: dict, r: rag.Retrieval | None,
                      path: str) -> tuple[dict | None, bool | None]:
    """Haiku answers from the figures and the retrieved passages (or the figures alone when `r` is None)."""
    from vicky.qa import fact_sheet

    sheet, extra = fact_sheet(ctx)
    vault = Vault()
    chunks = r.chunks if r else []
    await vault.keep_ids([c["note_id"] for c in chunks])
    parts = [f'<data company="{ctx.company}">\n{sheet}\n</data>']
    if chunks:
        parts.append(_chunk_block(chunks))
    parts.append(f"Question: {question}")
    parts.append(f"A deterministic draft answer from the data (correct, but possibly clumsy): {offline['reply']}")
    text, answerable, res = await _ask_model("qa_rag", [RAG_SYSTEM], "\n\n".join(parts), ctx, vault, extra)
    if text is None:
        return None, answerable
    meta = {"path": path, **({"confidence": round(r.confidence, 3), "signals": r.signals} if r else {})}
    return await _done(text, res, offline, ctx, meta), True


def _folder(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


async def vault_fits() -> tuple[bool, int]:
    """(whether the whole vault fits one catch-all read, how many notes it has)."""
    row = await db.fetchrow("select count(*) filter (where kind <> 'hub') as n, coalesce(sum(length(content)), 0) as size "
                            "from kb_notes")
    return int(row["size"]) <= get_settings().rag_full_max_tokens * 4, int(row["n"])


async def _snapshot(recovered: rag.Retrieval | None) -> tuple[str, list[dict]]:
    """Every note, sorted by path, as the catch-all's <vault>. Over the cap, it fills up in order of
    relevance: the notes the recovery pass found, hubs, the rest of their folders, then the most recently
    updated notes, so it is never empty while the vault isn't."""
    notes = await db.fetch("select id::text, path, title, kind, format, summary, content, updated_at "
                           "from kb_notes order by path")
    cap = get_settings().rag_full_max_tokens * 4
    if sum(len(n["content"]) for n in notes) > cap:
        hits = [c["path"] for c in (recovered.chunks if recovered else [])]
        folders = {_folder(p) for p in hits[:20]}
        rank = {p: i for i, p in enumerate(dict.fromkeys(hits))}

        def priority(n: dict) -> tuple:
            return (0 if n["path"] in rank else 1 if n["kind"] == "hub" else 2 if _folder(n["path"]) in folders else 3,
                    rank.get(n["path"], 0), -n["updated_at"].timestamp())

        out, size = [], 0
        for n in sorted(notes, key=priority):
            if size + len(n["content"]) > cap:
                continue
            out.append(n)
            size += len(n["content"])
        notes = sorted(out, key=lambda n: n["path"])
    body = "\n".join(f'<note path="{n["path"]}" title="{n["title"]}">\n{n["content"]}\n</note>' for n in notes)
    return f"<vault>\n{body}\n</vault>", notes


async def catch_all(question: str, ctx: TruthContext, offline: dict,
                    recovered: rag.Retrieval | None) -> tuple[dict | None, bool | None]:
    """Haiku over the whole vault. Runs only after the user accepted the offer. (answer, answerable):
    answerable is None when the model couldn't be reached."""
    from vicky.qa import fact_sheet

    snap, notes = await _snapshot(recovered)
    vault = Vault()
    for n in notes:
        vault._keep(n)
    sheet, extra = fact_sheet(ctx)
    content = (f'<data company="{ctx.company}">\n{sheet}\n</data>\n\nQuestion: {question}\n\n'
               f"A deterministic draft answer from the data (correct, but possibly clumsy): {offline['reply']}")
    text, answerable, res = await _ask_model("qa_full", [RAG_SYSTEM, FULL_RULES, snap], content, ctx, vault, extra)
    if text is None:
        return None, answerable
    return await _done(text, res, offline, ctx, {"path": "catch_all", "notes": len(notes)}), True


async def quote_answer(question: str, ctx: TruthContext, offline: dict, r: rag.Retrieval | None) -> dict | None:
    """No model: the best line of the best passages, verbatim and cited, when the data has no answer."""
    from vicky.qa import _with_notes

    if r is None or not r.chunks or (r.signals.get("cover") or 0.0) < QUOTE_MIN_COVER:
        return None
    vault = Vault()
    await vault.keep_ids([c["note_id"] for c in r.chunks[:4]])
    ts = terms(question)
    quotes, used = [], set()
    for c in r.chunks:
        if c["path"] in used or c["path"] not in vault.notes():
            continue
        for line in excerpts(c["text"], ts, 3):
            if line.lstrip().startswith(("#", "|")) or len(line.split()) < 4:
                continue  # a heading, a table row or a fragment isn't an answer
            q = f"“{line}” {c['cite']}"
            if audit_text(q, ctx.available(), notes=vault.notes()).passed:
                quotes.append(q)
                used.add(c["path"])
                break
        if len(quotes) == 2:
            break
    if not quotes:
        return None
    reply = "Your numbers don't cover that, but your notes do: " + " ".join(quotes)
    res = audit_text(reply, ctx.available(), notes=vault.notes(), require_citations=True)
    if not res.passed:
        return None
    cites = [c.model_dump(mode="json") for c in res.citations]
    return _with_notes({**offline, "reply": reply, "citations": cites, "topic": "notes",
                        "audit": {"passed": True, "findings": []}, "rag": {"path": "quotes"}}, res)


# ---------------------------------------------------------------- offers

class OfferGone(Exception):
    pass


async def can_offer() -> bool:
    from vicky import llm
    from vicky.llm.client import over_budget

    if not llm.enabled():
        return False
    try:
        if await over_budget():
            return False
    except Exception:
        return False
    return bool(await db.fetchval("select exists (select 1 from kb_notes)"))


async def create_offer(dashboard_id: str, question: str, ctx: TruthContext, retrievals: list[rag.Retrieval]) -> dict:
    build = next((r.build_id for r in retrievals if r.build_id), None)
    kbv = await kb_version()
    await db.execute("update rag_misses set decision = 'expired', decided_at = now() "
                     "where decision = 'pending' and created_at < now() - interval '15 minutes'")
    miss = await db.fetchval(
        """insert into rag_misses (build_id, kb_version, surface, dashboard_id, question, retrieved)
           values ($1::uuid, $2, 'ask', $3::uuid, $4, $5) returning id::text""",
        build, kbv, dashboard_id, question[:500], {"passes": [r.summary() for r in retrievals]})
    oid = uuid.uuid4().hex
    rec = {"dashboard_id": dashboard_id, "question": question, "miss_id": miss, "build_id": build}
    try:
        await kv.set_json(f"rag:offer:{oid}", rec, OFFER_TTL_S)
    except Exception as e:  # without Redis the offer can't be redeemed: don't make one
        log.info("could not store the catch-all offer: %s", e)
        return {}
    fits, n = await vault_fits()
    await rag.stat("offer")
    prompt = (f"Search all {n} notes with AI? This reads your whole knowledge base and takes a few seconds." if fits
              else f"Search your notes with AI? Your {n} notes are more than one read can hold, so this reads as many "
                   "as fit, starting with the ones closest to your question. It takes a few seconds.")
    return {"kind": "catch_all", "id": oid, "prompt": prompt, "whole_vault": fits,
            "notes": n, "expires_at": (datetime.now(UTC) + timedelta(seconds=OFFER_TTL_S)).isoformat()}


async def take_offer(dashboard_id: str, offer_id: str) -> dict:
    """The offer, once: deleted as it's read. Expired, used or another dashboard's → OfferGone."""
    if not re.fullmatch(r"[0-9a-f]{32}", offer_id or ""):
        raise OfferGone("unknown offer")
    try:
        raw = await kv.client().getdel(f"rag:offer:{offer_id}")
    except Exception as e:
        raise OfferGone(f"offer store unavailable: {e}") from e
    rec = json.loads(raw) if raw else None
    if not rec:
        raise OfferGone("This offer expired or was already used. Ask the question again.")
    if rec["dashboard_id"] != dashboard_id:
        raise OfferGone("That offer belongs to another dashboard.")
    return rec


async def decline(rec: dict) -> None:
    await db.execute("update rag_misses set decision = 'declined', decided_at = now() where id = $1::uuid",
                     rec["miss_id"])
    await rag.stat("offer_declined")


async def accept(rec: dict, ctx: TruthContext, offline: dict) -> dict:
    """Run the catch-all for an accepted offer; log the outcome on the miss."""
    from vicky.llm.client import over_budget

    await rag.stat("offer_accepted")
    out, answerable = None, None
    recovered = None
    budget_spent = await over_budget()
    if not budget_spent:
        recovered = await rag.retrieve(rec["question"], mode="recover")
        out, answerable = await catch_all(rec["question"], ctx, offline, recovered)
    cited = [n["path"] for n in (out or {}).get("notes") or []]
    await db.execute("update rag_misses set decision = 'accepted', decided_at = now(), passed = $2, cited_notes = $3 "
                     "where id = $1::uuid", rec["miss_id"], out is not None, cited)
    if out is None:
        # Say what actually happened: nothing was read when the budget is spent or the model is unreachable.
        reply = ("Today's AI budget is used up, so I couldn't search every note. Try again tomorrow." if budget_spent
                 else "I couldn't reach the AI service to read your notes. Try again in a moment." if answerable is None
                 else "I read every note and still couldn't find a cited answer to that.")
        return {**offline, "reply": reply, "citations": [], "rag": {"path": "catch_all", "passed": False}}
    build = recovered.build_id if recovered else None
    if build:
        await remember(rec["question"], ctx, build, await kb_version(), out)
    return out


# ---------------------------------------------------------------- the ladder

def _extra_queries(offline: dict, ctx: TruthContext) -> list[str]:
    f = ctx.figures.get(offline.get("topic") or "")
    return [getattr(f, "label", "")] if f is not None and getattr(f, "label", "") else []


async def answer(question: str, ctx: TruthContext, offline: dict, *, dashboard_id: str | None = None) -> dict:
    from vicky import llm

    s = get_settings()
    first = await rag.retrieve(question, mode="ask")
    build = first.build_id
    if build is None:
        return offline
    kbv = first.kb_version
    hit = await cached(question, ctx, build, kbv)
    if hit:
        return hit
    needs_notes = offline.get("topic") == "not_found"
    if not llm.enabled():
        return (await quote_answer(question, ctx, offline, first) if needs_notes else None) or offline

    def log_path(path: str, r: rag.Retrieval | None) -> None:
        log.info("ask vicky: path=%s kb_v=%s confidence=%s ms=%s", path, kbv, r and round(r.confidence, 3), r and r.ms)

    if first.chunks and first.confidence >= s.rag_conf_min:
        out, answerable = await from_chunks(question, ctx, offline, first, "chunks")
        if out:
            log_path("chunks", first)
            await rag.stat("path_chunks")
            await remember(question, ctx, build, kbv, out)
            return out
        needs_notes = needs_notes or answerable is False
    elif not needs_notes:
        out, _ = await from_chunks(question, ctx, offline, None, "figures")
        if out:
            await rag.stat("path_figures")
            await remember(question, ctx, build, kbv, out)
            return out
        return offline
    recovered = await rag.retrieve(question, mode="recover", extra_queries=_extra_queries(offline, ctx))
    if recovered.chunks and recovered.confidence >= s.rag_conf_min:
        out, answerable = await from_chunks(question, ctx, offline, recovered, "recover")
        if out:
            log_path("recover", recovered)
            await rag.stat("path_recover")
            await remember(question, ctx, build, kbv, out)
            return out
        needs_notes = needs_notes or answerable is False
    if not needs_notes:
        out, _ = await from_chunks(question, ctx, offline, None, "figures")
        return out or offline
    base = await quote_answer(question, ctx, offline, recovered) or offline
    if dashboard_id and await can_offer():
        offer = await create_offer(dashboard_id, question, ctx, [first, recovered])
        if offer:
            log_path("offer", recovered)
            return {**base, "offer": offer}
    await rag.stat("path_offline")
    return base
