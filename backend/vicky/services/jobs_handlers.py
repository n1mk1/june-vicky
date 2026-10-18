"""Job handlers registered with `vicky.jobs`. Reports are built inline at session end today;
this hook re-builds one on demand (e.g. a Retry from the UI). `extract` reads cited facts out of
PDF / DOCX / MD uploads (FR-7); `kb_ingest` converts and organizes knowledge-base imports and
`kb_organize` re-runs the organizer. Memo, prescan and persona_gen attach as those pipelines land.
"""

from vicky.areopagus import registry
from vicky.jobs import job
from vicky.model.currencies import norm_currency
from vicky.services import engagements


@job("report")
async def report_job(payload: dict) -> dict:
    from vicky import db, report

    sid = payload["session_id"]
    sess = await db.fetchrow("select * from sessions where id::text = $1", sid)
    if sess is None:
        raise ValueError(f"no session {sid}")
    ctx = await engagements.context(str(sess["engagement_id"]))
    panel = {p.id: p for p in await registry.panel(sess["panel"], strict=False)}
    rid = await report.build(sid, ctx, panel)
    return {"report_id": rid}


@job("extract")
async def extract_job(payload: dict) -> dict:
    """FR-7: cited facts from a PDF / DOCX / MD upload → pending facts in the TruthPack."""
    from vicky import db
    from vicky.llm import docs

    uid = payload["upload_id"]
    row = await db.fetchrow("select id::text, engagement_id::text as eid, filename, kind::text, bytes from uploads "
                            "where id::text = $1", uid)
    if row is None:
        raise ValueError(f"no upload {uid}")
    currency = await db.fetchval("select currency from company_profiles where engagement_id::text = $1", row["eid"])
    try:
        out = await docs.extract_facts(bytes(row["bytes"]), row["filename"], row["kind"], upload_id=uid,
                                       currency=norm_currency(currency))
    except Exception:
        await db.execute("update uploads set status = 'failed' where id::text = $1", uid)
        raise
    added = await engagements.add_extracted_facts(uid, out["facts"])
    flagged = sum(1 for f in out["facts"] if f.source.verified is False)
    return {"added": added, "flagged": flagged, "dropped": out["dropped"], "lines": out["lines"]}


@job("kb_ingest")
async def kb_ingest_job(payload: dict) -> dict:
    from vicky.kb.ingest import ingest_job

    return await ingest_job(payload)


@job("kb_organize")
async def kb_organize_job(payload: dict) -> dict:
    from vicky.kb.organize import organize

    return await organize(full=bool(payload.get("full")))
