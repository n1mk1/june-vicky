"""Job handlers registered with `vicky.jobs`. Reports are built inline at session end today;
this hook re-builds one on demand (e.g. a Retry from the UI) and is where memo, prescan,
extract and persona_gen handlers attach as those pipelines land.
"""

from vicky.areopagus import registry
from vicky.jobs import job
from vicky.services import engagements


@job("report")
async def report_job(payload: dict) -> dict:
    from vicky import db, report

    sid = payload["session_id"]
    sess = await db.fetchrow("select * from sessions where id::text = $1", sid)
    if sess is None:
        raise ValueError(f"no session {sid}")
    ctx = await engagements.context(str(sess["engagement_id"]))
    panel = {p.id: p for p in await registry.panel(sess["panel"])}
    rid = await report.build(sid, ctx, panel)
    return {"report_id": rid}
