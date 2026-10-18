"""Review the catch-all misses (docs/08-RAG.md §Learning from misses).

Every catch-all offer is logged in `rag_misses`, accepted or not. An accepted miss whose answer quoted a note
that retrieval didn't rank in its top 8 is a retrieval failure: the fix is a glossary entry, a chunking rule,
a better summary, or a weight. This lists the unreviewed misses with what retrieval returned, so each can
become a case in backend/data/samples/rag_eval/cases.yaml.

Run from backend/:

    uv run python scripts/rag_misses.py            # list unreviewed misses
    uv run python scripts/rag_misses.py --mark-reviewed
"""

import asyncio
import sys

from vicky import db


async def main(mark: bool) -> None:
    await db.connect()
    try:
        rows = await db.fetch(
            "select id::text, created_at, question, decision, passed, cited_notes, retrieved from rag_misses "
            "where not reviewed order by created_at")
        for r in rows:
            passes = (r["retrieved"] or {}).get("passes") or []
            ranked = [c["path"] for p in passes[-1:] for c in p.get("chunks", [])]
            failed = [n for n in r["cited_notes"] if n not in ranked[:8]]
            print(f"\n{r['created_at']:%Y-%m-%d %H:%M}  [{r['decision']}]  {r['question']}")
            for p in passes:
                print(f"  {p.get('mode')}: confidence {p.get('confidence')}  top: {[c['path'] for c in p.get('chunks', [])][:5]}")
            if r["cited_notes"]:
                print(f"  catch-all quoted: {r['cited_notes']}")
            if failed:
                print(f"  RETRIEVAL FAILURE: {failed} not in the recovery top 8")
        print(f"\n{len(rows)} unreviewed")
        if mark and rows:
            await db.execute("update rag_misses set reviewed = true where id = any($1::uuid[])", [r["id"] for r in rows])
            print("marked reviewed")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main("--mark-reviewed" in sys.argv))
