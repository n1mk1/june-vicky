"""Hybrid retrieval over the active index (docs/08-RAG.md §Retrieval, §Confidence, §Caching).

`retrieve(query, mode=…)`:
1. **Expand by code:** glossary synonyms are added to the BM25 query at half weight (full weight in recovery).
2. **BM25** (in process) and **vector search** (pgvector, Voyage query embedding) in parallel.
3. **Reciprocal rank fusion**, dropping chunks whose note changed since the Fill (their text may be gone,
   so a quote could not be verified) and collapsing the same passage imported twice.
4. **Graph boost** for notes linked to the top three, **rerank** with Voyage, **small-to-big** context.
5. **Confidence** from code signals; the result is cached under the build and vault version.

Every Redis use is best-effort: a cache or stats failure never fails a search.
"""

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from vicky import db, kv
from vicky.config import get_settings
from vicky.kb import voyage
from vicky.kb.bm25 import BM25, tokens
from vicky.kb.index import active_build_id, has_vector, kb_version, vectors_on

log = logging.getLogger(__name__)
Mode = Literal["ask", "court", "recover"]
RRF_K = 60
SMALL_WORDS = 90          # a chunk under ~120 tokens gets its neighbours as context
PER_NOTE = 3
RET_TTL_S = 3600
EMB_TTL_S = 30 * 86400
RR_TTL_S = 3600
STATS_TTL_S = 8 * 86400
MODES: dict[str, dict[str, Any]] = {
    "ask": {"lists": 50, "rerank": 30, "fast": False, "k": 8},
    "court": {"lists": 30, "rerank": 20, "fast": True, "k": 4},
    "recover": {"lists": 100, "rerank": 60, "fast": False, "k": 8},
}


def cite(path: str) -> str:
    return f"[kb:{path}]"


def normalize(q: str) -> str:
    q = re.sub(r"\s+", " ", (q or "").lower().replace("’", "'")).strip()
    return q.strip(" ?!.,;:\"'")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------- glossary

@lru_cache
def _glossary() -> list[list[tuple[str, ...]]]:
    raw = yaml.safe_load((Path(__file__).with_name("glossary.yaml")).read_text(encoding="utf-8")) or []
    groups = []
    for g in raw:
        members = [tuple(tokens(str(m))) for m in g]
        groups.append([m for m in members if m])
    return groups


def _contains(seq: list[str], sub: tuple[str, ...]) -> bool:
    n = len(sub)
    return any(tuple(seq[i:i + n]) == sub for i in range(len(seq) - n + 1))


def expand(query: str, weight: float = 0.5) -> tuple[dict[str, float], list[str]]:
    """(token → weight, the query's own content tokens)."""
    qt = tokens(query)
    out: dict[str, float] = {}
    for t in qt:
        out[t] = 1.0
    for group in _glossary():
        if any(_contains(qt, m) for m in group):
            for m in group:
                for t in m:
                    out.setdefault(t, weight)
    return out, list(dict.fromkeys(qt))


def _equivalents(t: str) -> set[str]:
    eq = {t}
    for group in _glossary():
        if any(t in m for m in group):
            eq |= {x for m in group for x in m}
    return eq


# ---------------------------------------------------------------- the in-process index

@dataclass
class _Index:
    build_id: str
    rows: list[dict]
    bm25: BM25
    pos: dict[str, int]
    by_note: dict[str, list[int]]
    vectors: bool = False  # the build stored embeddings (an index built without a Voyage key has none)


_INDEX: _Index | None = None


def _doc_tokens(r: dict) -> list[str]:
    return tokens(" ".join([r["title"] or "", " ".join(r["tags"] or []), r["heading"] or "", r["text"]]))
_LOCK = asyncio.Lock()


async def _index(build_id: str) -> _Index:
    global _INDEX
    if _INDEX is not None and _INDEX.build_id == build_id:
        return _INDEX
    async with _LOCK:
        if _INDEX is not None and _INDEX.build_id == build_id:
            return _INDEX
        rows = await db.fetch(
            """select c.id::text, c.note_id::text, c.note_md5, c.ord, c.heading, c.start_char, c.end_char, c.text,
                      c.text_sha256, n.path, n.title, n.tags, n.links
               from kb_chunks c join kb_notes n on n.id = c.note_id
               where c.build_id = $1::uuid order by n.path, c.ord""", build_id)
        docs = (_doc_tokens(r) for r in rows)  # streamed: no token list per chunk is kept
        by_note: dict[str, list[int]] = {}
        for i, r in enumerate(rows):
            by_note.setdefault(r["note_id"], []).append(i)
        vectors = bool(await db.fetchval("select embed_model is not null from kb_index_builds where id = $1::uuid",
                                         build_id))
        _INDEX = _Index(build_id, rows, BM25(docs), {r["id"]: i for i, r in enumerate(rows)}, by_note, vectors)
        log.info("kb BM25 index loaded for build %s: %d chunks", build_id, len(rows))
        return _INDEX


def drop_index() -> None:
    global _INDEX
    _INDEX = None


# ---------------------------------------------------------------- result

@dataclass
class Retrieval:
    chunks: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    signals: dict[str, Any] = field(default_factory=dict)
    build_id: str | None = None
    kb_version: int = 0
    mode: str = "ask"
    cached: bool = False
    ms: int = 0

    @property
    def available(self) -> bool:
        return self.build_id is not None

    def summary(self) -> dict[str, Any]:
        return {"mode": self.mode, "confidence": round(self.confidence, 3), "signals": self.signals,
                "chunks": [{"id": c["id"], "path": c["path"], "score": round(c.get("score", 0.0), 4),
                            "rerank": c.get("rerank")} for c in self.chunks], "cached": self.cached, "ms": self.ms}


async def stat(field_: str, n: int = 1) -> None:
    try:
        key = f"rag:stats:{kv.today().replace('-', '')}"
        await kv.client().hincrby(key, field_, n)
        await kv.client().expire(key, STATS_TTL_S)
    except Exception:
        pass


async def _cache_get(key: str) -> Any:
    try:
        return await kv.get_json(key)
    except Exception:
        return None


async def _cache_set(key: str, value: Any, ttl: int) -> None:
    try:
        await kv.set_json(key, value, ttl)
    except Exception:
        pass


# ---------------------------------------------------------------- pieces

async def query_vector(text: str) -> list[float] | None:
    if not vectors_on() or not await has_vector():
        return None
    model = get_settings().embed_model
    key = f"rag:emb:{model}:{_sha(normalize(text))}"
    hit = await _cache_get(key)
    if hit:
        await stat("emb_hit")
        return hit
    try:
        (vec,) = await voyage.embed([text], "query", timeout_s=8.0)
    except voyage.VoyageError as e:
        log.info("query embedding failed, BM25 only: %s", e)
        return None
    await stat("emb_miss")
    await _cache_set(key, vec, EMB_TTL_S)
    return vec


async def _vector_hits(build_id: str, vec: list[float] | None, limit: int) -> list[tuple[str, float]]:
    if vec is None:
        return []
    async with db.acquire() as conn, conn.transaction():
        await conn.execute(f"set local hnsw.ef_search = {max(100, limit * 2)}")
        rows = await conn.fetch(
            "select id::text, 1 - (embedding <=> $1::halfvec) as sim from kb_chunks "
            "where build_id = $2::uuid and embedding is not null order by embedding <=> $1::halfvec limit $3",
            voyage.to_pg(vec), build_id, limit)
    return [(r["id"], float(r["sim"])) for r in rows]


def _rrf(lists: list[list[str]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for lst in lists:
        for rank, cid in enumerate(lst, 1):
            out[cid] = out.get(cid, 0.0) + 1.0 / (RRF_K + rank)
    return out


async def _notes_now(note_ids: list[str]) -> dict[str, dict]:
    rows = await db.fetch("select id::text, md5(content) as md5, path, title, kind, updated_at from kb_notes "
                          "where id = any($1::uuid[])", note_ids)
    return {r["id"]: r for r in rows}


async def _rerank(query: str, idx: _Index, ids: list[str], model: str, build_id: str) -> dict[str, float] | None:
    if not vectors_on() or not ids:
        return None
    key = f"rag:rr:{build_id}:{model}:{_sha(normalize(query))}:{_sha(','.join(ids))}"
    hit = await _cache_get(key)
    if hit:
        await stat("rr_hit")
        return hit
    docs = [f"{idx.rows[idx.pos[i]]['title']} · {idx.rows[idx.pos[i]]['heading']}\n{idx.rows[idx.pos[i]]['text']}"
            for i in ids]
    try:
        scored = await voyage.rerank(query, docs, model=model)
    except voyage.VoyageError as e:
        log.info("rerank failed, fused order kept: %s", e)
        return None
    out = {ids[i]: s for i, s in scored if 0 <= i < len(ids)}
    await stat("rr_miss")
    await _cache_set(key, out, RR_TTL_S)
    return out


def _context(idx: _Index, i: int) -> list[str]:
    r = idx.rows[i]
    if len(r["text"].split()) >= SMALL_WORDS:
        return []
    sibs = idx.by_note.get(r["note_id"], [])
    k = sibs.index(i)
    out = []
    for j in (k - 1, k + 1):
        if 0 <= j < len(sibs) and idx.rows[sibs[j]]["heading"] == r["heading"]:
            out.append(idx.rows[sibs[j]]["text"])
    return out


def _confidence(signals: dict[str, Any], with_vectors: bool) -> float:
    if with_vectors:
        return (0.40 * (signals.get("rerank") or 0.0) + 0.20 * signals.get("agree", 0.0)
                + 0.15 * signals.get("sim", 0.0) + 0.15 * signals.get("cover", 0.0) + 0.10 * signals.get("margin", 0.0))
    return 0.6 * signals.get("cover", 0.0) + 0.4 * signals.get("margin", 0.0)


# ---------------------------------------------------------------- retrieve

async def retrieve(query: str, *, mode: Mode = "ask", k: int | None = None,
                   extra_queries: list[str] | None = None) -> Retrieval:
    t0 = time.perf_counter()
    cfg = MODES[mode]
    k = k or cfg["k"]
    build_id = await active_build_id()
    if not build_id or not (query or "").strip():
        return Retrieval(mode=mode, build_id=build_id)
    kbv = await kb_version()
    idx = await _index(build_id)
    qn = normalize(query)
    extra = [e for e in (extra_queries or []) if e and normalize(e) != qn]
    key = f"rag:ret:{build_id}:{kbv}:{mode}:{k}:{_sha(qn + '|' + '|'.join(sorted(map(normalize, extra))))}"
    hit = await _cache_get(key)
    if hit:
        await stat("ret_hit")
        out = await _hydrate(idx, hit["order"], hit["scores"], hit.get("rerank") or {}, k)
        r = Retrieval(out, hit["confidence"], hit["signals"], build_id, kbv, mode, True,
                      int((time.perf_counter() - t0) * 1000))
        return r
    await stat("ret_miss")

    # 1–2: expanded BM25 and vector search, per query
    queries = [(query, 0.5)]
    if mode == "recover":
        queries = [(query, 0.5), (query, 1.0), *((e, 0.5) for e in extra)]
    vec_texts = list(dict.fromkeys([query, *(extra if mode == "recover" else [])]))
    # A build without embeddings has nothing to search by vector: don't embed the question for it.
    vecs = await asyncio.gather(*(query_vector(t) for t in vec_texts)) if idx.vectors else [None] * len(vec_texts)
    vec_lists = await asyncio.gather(*(_vector_hits(build_id, v, cfg["lists"]) for v in vecs))
    lists: list[list[str]] = []
    bm25_top: list[str] = []
    q_terms: list[str] = []
    for qtext, w in queries:
        weighted, own = expand(qtext, w)
        if qtext == query and not q_terms:
            q_terms = own
        hits = [idx.rows[i]["id"] for i, _s in idx.bm25.search(weighted, cfg["lists"])]
        if qtext == query and not bm25_top:
            bm25_top = hits
        lists.append(hits)
    bm25_scores = dict((idx.rows[i]["id"], s) for i, s in idx.bm25.search(expand(query, 0.5)[0], cfg["lists"]))
    for vl in vec_lists:
        lists.append([cid for cid, _ in vl if cid in idx.pos])
    sims = {cid: s for vl in vec_lists for cid, s in vl}

    # 3: fuse; drop chunks of changed notes; collapse duplicates
    fused = _rrf(lists)
    cand_notes = list({idx.rows[idx.pos[c]]["note_id"] for c in fused if c in idx.pos})
    now = await _notes_now(cand_notes) if cand_notes else {}
    live: dict[str, float] = {}
    by_text: dict[str, str] = {}
    for cid, s in sorted(fused.items(), key=lambda kv_: -kv_[1]):
        if cid not in idx.pos:
            continue
        row = idx.rows[idx.pos[cid]]
        note = now.get(row["note_id"])
        if note is None or note["md5"] != row["note_md5"]:
            continue
        dup = by_text.get(row["text_sha256"])
        if dup is not None:
            other = now[idx.rows[idx.pos[dup]]["note_id"]]
            if note["updated_at"] > other["updated_at"]:  # keep the passage in the most recently updated note
                live.pop(dup)
                by_text[row["text_sha256"]] = cid
                live[cid] = s
            continue
        by_text[row["text_sha256"]] = cid
        live[cid] = s

    # 4: graph boost from the top three notes
    order = sorted(live, key=lambda c: -live[c])
    top_paths = list(dict.fromkeys(idx.rows[idx.pos[c]]["path"] for c in order))[:3]
    if top_paths:
        top_links = {p for c in order[:12] if idx.rows[idx.pos[c]]["path"] in top_paths
                     for p in (idx.rows[idx.pos[c]]["links"] or [])}
        for c in order:
            row = idx.rows[idx.pos[c]]
            if row["path"] in top_paths[:3]:
                continue
            if row["path"] in top_links or any(p in (row["links"] or []) for p in top_paths):
                live[c] *= 1.10
        order = sorted(live, key=lambda c: -live[c])

    # 4b: rerank
    s = get_settings()
    model = s.rerank_model_fast if cfg["fast"] else s.rerank_model
    rr = await _rerank(query, idx, order[:cfg["rerank"]], model, build_id) if order else None
    if rr:
        order = sorted(order[:cfg["rerank"]], key=lambda c: -rr.get(c, 0.0)) + order[cfg["rerank"]:]

    # 5: keep k (at most PER_NOTE per note), then confidence
    kept: list[str] = []
    per: dict[str, int] = {}
    for c in order:
        nid = idx.rows[idx.pos[c]]["note_id"]
        if per.get(nid, 0) >= PER_NOTE:
            continue
        per[nid] = per.get(nid, 0) + 1
        kept.append(c)
        if len(kept) >= k:
            break
    with_vec = any(vec_lists)  # vector hits came back, not merely a query vector
    signals: dict[str, Any] = {"vectors": with_vec, "reranked": bool(rr)}
    if kept:
        top = kept[0]
        top_bm = set(bm25_top[:10])
        top_vec = {cid for cid, _ in (vec_lists[0] if vec_lists else [])[:10]}
        signals["agree"] = 1.0 if top in top_bm and top in top_vec else 0.0
        best_sim = max(sims.values()) if sims else 0.0
        signals["sim"] = round(min(1.0, max(0.0, (best_sim - 0.3) / 0.5)), 4)
        # Coverage weighted by rarity: a word no note contains weighs as much as the rarest one, so a question
        # about something the vault lacks scores low, while filler words barely count.
        top_tokens = set().union(*(set(_doc_tokens(idx.rows[idx.pos[c]])) for c in kept[:3]))
        rarest = max(idx.bm25.idf.values(), default=1.0)
        weight = {t: max((idx.bm25.idf.get(e, 0.0) for e in _equivalents(t)), default=0.0) or rarest for t in q_terms}
        total = sum(weight.values())
        got = sum(w for t, w in weight.items() if _equivalents(t) & top_tokens)
        signals["cover"] = round(got / total, 4) if total else 0.0
        if rr:
            scores = [rr.get(c, 0.0) for c in kept]
            signals["rerank"] = round(scores[0], 4)
        else:
            scores = [bm25_scores.get(c, 0.0) for c in kept] if not with_vec else [live[c] for c in kept]
        s1, s5 = scores[0], (scores[4] if len(scores) >= 5 else (scores[-1] if len(scores) > 1 else 0.0))
        signals["margin"] = round((s1 - s5) / s1, 4) if s1 > 0 else 0.0
        conf = _confidence(signals, with_vec)
    else:
        conf = 0.0
    scores_out = {c: live[c] for c in kept}
    rr_out = {c: rr[c] for c in kept if rr and c in rr}
    await _cache_set(key, {"order": kept, "scores": scores_out, "rerank": rr_out, "confidence": conf,
                           "signals": signals}, RET_TTL_S)
    out = await _hydrate(idx, kept, scores_out, rr_out, k, now)
    return Retrieval(out, conf, signals, build_id, kbv, mode, False, int((time.perf_counter() - t0) * 1000))


async def _hydrate(idx: _Index, order: list[str], scores: dict[str, float], rr: dict[str, float], k: int,
                   now: dict[str, dict] | None = None) -> list[dict]:
    ids = [c for c in order if c in idx.pos][:k]
    if now is None:
        now = await _notes_now(list({idx.rows[idx.pos[c]]["note_id"] for c in ids})) if ids else {}
    out = []
    for c in ids:
        i = idx.pos[c]
        row = idx.rows[i]
        note = now.get(row["note_id"])
        if note is None or note["md5"] != row["note_md5"]:
            continue
        out.append({"id": c, "note_id": row["note_id"], "path": note["path"], "title": note["title"],
                    "kind": note["kind"], "heading": row["heading"], "text": row["text"], "start": row["start_char"],
                    "end": row["end_char"], "context": _context(idx, i), "score": scores.get(c, 0.0),
                    "rerank": rr.get(c), "cite": cite(note["path"])})
    return out
