"""Retrieval eval (docs/08-RAG.md §Testing and evals): recall@5 and MRR of each search setup on a labelled
fixture vault (backend/data/samples/rag_eval/). Builds the vault in its own database (`<db>_rag_eval`, dropped
and recreated each run), indexes it like Fill dashboard does, then asks every question.

Setups: the search before this index existed (full-text + keywords over whole notes), BM25 alone, BM25 with
glossary expansion, the recovery pass, and with VOYAGE_API_KEY set also hybrid (vectors + rerank).

Run from backend/ with Postgres up (pgvector for the hybrid rows):

    uv run python evals/rag/run.py
"""

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import asyncpg
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from vicky import db, jobs, migrate  # noqa: E402
from vicky.config import get_settings  # noqa: E402
from vicky.kb import index, rag, store, voyage  # noqa: E402
from vicky.kb.tools import terms  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data" / "samples" / "rag_eval"
TARGETS = {"recall@5": 0.95, "MRR": 0.85}


async def _fresh_db() -> str:
    u = urlparse(os.environ.get("DATABASE_URL", get_settings().database_url))
    name = f"{(u.path or '/vicky').lstrip('/') or 'vicky'}_rag_eval"
    admin = await asyncpg.connect(urlunparse(u._replace(path="/postgres")))
    await admin.execute(f'drop database if exists "{name}" with (force)')
    await admin.execute(f'create database "{name}"')
    await admin.close()
    return urlunparse(u._replace(path=f"/{name}"))


async def _legacy(q: str) -> list[str]:
    """The search kb_search used before the index: full-text over whole notes, then any-word keywords."""
    out: list[str] = []
    for r in [*await store.search(q, 10), *await store.keyword_search(terms(q), 20)]:
        if r["path"] not in out:
            out.append(r["path"])
    return out


async def _ranked(q: str, mode: str) -> list[str]:
    r = await rag.retrieve(q, mode=mode, k=8)  # type: ignore[arg-type]
    return list(dict.fromkeys(c["path"] for c in r.chunks))


def _score(rows: list[tuple[str, list[str]]]) -> dict[str, float]:
    rr, hit5 = [], 0
    for want, got in rows:
        rank = got.index(want) + 1 if want in got else None
        rr.append(1 / rank if rank else 0.0)
        hit5 += bool(rank and rank <= 5)
    return {"recall@5": hit5 / len(rows), "MRR": sum(rr) / len(rr)}


async def main() -> None:
    dsn = await _fresh_db()
    await migrate.migrate(dsn)
    await db.connect(dsn)
    os.environ["JOBS_MODE"] = "inline"
    get_settings.cache_clear()
    try:
        paths = {}
        for n in yaml.safe_load((DATA / "notes.yaml").read_text(encoding="utf-8")):
            made = await store.create_note(
                {
                    "title": n["title"],
                    "path": n["path"].removesuffix(".md"),
                    "content": n["content"],
                    "tags": n.get("tags") or [],
                }
            )
            paths[n["path"]] = made["path"]
        b = await index.start_build()
        job = await db.fetchval("select job_id::text from kb_index_builds where id = $1::uuid", b["build_id"])
        await jobs.wait_for([job], 600)
        cases = yaml.safe_load((DATA / "cases.yaml").read_text(encoding="utf-8"))
        setups: list[tuple[str, object]] = [("before the index (full-text over notes)", None)]
        glossary = rag._glossary
        results = {}
        for name, mode, expand in [
            ("BM25", "ask", False),
            ("BM25 + glossary", "ask", True),
            ("BM25 + glossary + recovery", "recover", True),
        ]:
            rag._glossary = glossary if expand else (lambda: [])  # type: ignore[assignment]
            results[name] = _score([(paths[c["note"]], await _ranked(c["q"], mode)) for c in cases])
        rag._glossary = glossary  # type: ignore[assignment]
        results[setups[0][0]] = _score([(paths[c["note"]], await _legacy(c["q"])) for c in cases])
        if voyage.enabled() and await index.has_vector():
            results["hybrid + rerank"] = _score(
                [(paths[c["note"]], await _ranked(c["q"], "ask")) for c in cases]
            )
            results["hybrid + rerank + recovery"] = _score(
                [(paths[c["note"]], await _ranked(c["q"], "recover")) for c in cases]
            )
        else:
            print("(no VOYAGE_API_KEY or no pgvector: hybrid rows skipped)")
        print(f"\n{len(cases)} questions over {len(paths)} notes\n")
        print(f"{'setup':<42} {'recall@5':>9} {'MRR':>7}")
        for name in [setups[0][0], *[k for k in results if k != setups[0][0]]]:
            s = results[name]
            print(f"{name:<42} {s['recall@5']:>9.3f} {s['MRR']:>7.3f}")
        print(f"\ntargets: recall@5 >= {TARGETS['recall@5']}, MRR >= {TARGETS['MRR']}")
        misses = [c["q"] for c in cases if paths[c["note"]] not in (await _ranked(c["q"], "recover"))[:5]]
        if misses:
            print("\nmissed by BM25 + glossary + recovery:")
            for q in misses:
                print(f"  - {q}")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
