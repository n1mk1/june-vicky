"""Dashboards: stored widget specs + layout; values are evaluated by code on every read.

`version` is optimistic concurrency: writes carry the version they saw and get 409 when it
moved. Every change is published on `dashboard:{id}` so other tabs refresh.
"""

from typing import Any

from vicky import db
from vicky.model.context import TruthContext
from vicky.realtime import publish
from vicky.services import engagements
from vicky.viz import WidgetSpec, build_option, default_dashboard, evaluate_widget, spec_hash
from vicky.viz.defaults import RESERVED
from vicky.viz.spec import spec_json

THEMES = ("vicky-dark", "vicky-light")


class Conflict(Exception):
    pass


async def ensure_default(engagement_id: str, ctx: TruthContext) -> str:
    """Create the default dashboard on first confirm; later confirms add newly unlocked defaults."""
    dash = await db.fetchrow("select * from dashboards where engagement_id = $1 and name = 'default'", engagement_id)
    d = default_dashboard(ctx)
    async with db.pool().acquire() as conn, conn.transaction():
        if dash is None:
            did = await conn.fetchval("insert into dashboards (engagement_id) values ($1) returning id::text", engagement_id)
            layout_existing: list[dict] = []
        else:
            did = str(dash["id"])
            layout_existing = list(dash["layout"] or [])
        existing = {r["spec_hash"] for r in await conn.fetch("select spec_hash from widgets where dashboard_id = $1", did)}
        layout = layout_existing
        for i, (spec, role) in enumerate(zip(d.widgets, d.roles, strict=True)):
            h = spec_hash(spec)
            if h in existing:
                continue
            wid = await conn.fetchval(
                """insert into widgets (dashboard_id, spec, spec_hash, created_by, "order", role)
                   values ($1, $2, $3, 'system', $4, $5) returning id::text""",
                did, spec_json(spec), h, i, role)
            li = next((x for x in d.layout if x.widget_index == i), None)
            if li is not None:
                y_off = 0 if not layout_existing else max((x["y"] + x["h"] for x in layout_existing), default=0)
                y = li.y if not layout_existing else max(li.y, y_off)
                layout.append({"widget_id": wid, "x": li.x, "y": y, "w": li.w, "h": li.h})
        await conn.execute("update dashboards set layout = $2, version = version + 1 where id = $1", did, layout)
    return did


def _evaluated(spec: dict, ctx: TruthContext, theme: str) -> tuple[dict, dict | None]:
    ws = WidgetSpec.model_validate(spec)
    ev = evaluate_widget(ws, ctx)
    option = build_option(ws, ev, theme)
    return ev.model_dump(mode="json"), option


async def _ctx_for_dashboard(dashboard_id: str) -> tuple[dict, TruthContext]:
    dash = await db.fetchrow("select * from dashboards where id::text = $1", dashboard_id)
    if dash is None:
        raise engagements.NotFound("dashboard")
    return dash, await engagements.context(str(dash["engagement_id"]))


async def get(dashboard_id: str, theme: str = "vicky-dark") -> dict:
    theme = theme if theme in THEMES else THEMES[0]
    dash, ctx = await _ctx_for_dashboard(dashboard_id)
    rows = await db.fetch('select * from widgets where dashboard_id = $1 order by "order", created_at', dash["id"])
    widgets = []
    for r in rows:
        evaluated, option = _evaluated(r["spec"], ctx, theme)
        widgets.append({"id": str(r["id"]), "role": r["role"], "spec": r["spec"], "status": evaluated["status"],
                        "evaluated": evaluated, "option": option, "created_by": r["created_by"]})
    ids = {w["id"] for w in widgets}
    return {"id": str(dash["id"]), "engagement_id": str(dash["engagement_id"]), "version": dash["version"],
            "company": ctx.company, "truthpack_version": ctx.version,
            "layout": [li for li in (dash["layout"] or []) if li.get("widget_id") in ids],
            "reserved": [dict(r) for r in RESERVED], "time_range": dash["time_range"], "widgets": widgets}


async def active(theme: str = "vicky-dark") -> dict:
    eid = await engagements.require_confirmed()
    did = await db.fetchval("select id::text from dashboards where engagement_id = $1 and name = 'default'", eid)
    if did is None:
        did = await ensure_default(eid, await engagements.context(eid))
    return await get(did, theme)


async def preview(dashboard_id: str, spec: dict, theme: str = "vicky-dark") -> dict:
    _, ctx = await _ctx_for_dashboard(dashboard_id)
    ws = WidgetSpec.model_validate(spec)
    ev = evaluate_widget(ws, ctx)
    return {"evaluated": ev.model_dump(mode="json"), "option": build_option(ws, ev, theme)}


async def _check_version(conn, dashboard_id: str, version: int | None) -> dict:
    dash = await conn.fetchrow("select * from dashboards where id::text = $1 for update", dashboard_id)
    if dash is None:
        raise engagements.NotFound("dashboard")
    if version is not None and int(version) != dash["version"]:
        raise Conflict(f"The dashboard changed (version {dash['version']}); reload and try again.")
    return dict(dash)


async def add_widget(dashboard_id: str, spec: dict, version: int | None, created_by: str = "founder") -> dict:
    ws = WidgetSpec.model_validate(spec)
    h = spec_hash(ws)
    async with db.pool().acquire() as conn, conn.transaction():
        dash = await _check_version(conn, dashboard_id, version)
        exists = await conn.fetchval("select id::text from widgets where dashboard_id = $1 and spec_hash = $2", dash["id"], h)
        if exists is None:
            order = await conn.fetchval('select coalesce(max("order"), 0) + 1 from widgets where dashboard_id = $1', dash["id"])
            wid = await conn.fetchval(
                """insert into widgets (dashboard_id, spec, spec_hash, created_by, "order", role)
                   values ($1, $2, $3, $4::widget_author, $5, 'custom') returning id::text""",
                dash["id"], spec_json(ws), h, created_by, order)
            layout = list(dash["layout"] or [])
            bottom = max((x["y"] + x["h"] for x in layout), default=0)
            w = 3 if ws.template in ("kpi", "gauge_ring") else 6
            layout.append({"widget_id": wid, "x": 0, "y": bottom, "w": w, "h": 5})
            await conn.execute("update dashboards set layout = $2, version = version + 1 where id = $1", dash["id"], layout)
    out = await get(dashboard_id)
    await publish(f"dashboard:{dashboard_id}", "widget.diff", {"version": out["version"], "op": "add"})
    return out


async def remove_widget(dashboard_id: str, widget_id: str) -> dict:
    async with db.pool().acquire() as conn, conn.transaction():
        dash = await _check_version(conn, dashboard_id, None)
        n = await conn.execute("delete from widgets where dashboard_id = $1 and id::text = $2", dash["id"], widget_id)
        if n.endswith(" 0"):
            raise engagements.NotFound("widget")
        layout = [x for x in (dash["layout"] or []) if x.get("widget_id") != widget_id]
        await conn.execute("update dashboards set layout = $2, version = version + 1 where id = $1", dash["id"], layout)
    out = await get(dashboard_id)
    await publish(f"dashboard:{dashboard_id}", "widget.diff", {"version": out["version"], "op": "remove", "widget_id": widget_id})
    return out


async def set_layout(dashboard_id: str, layout: list[dict[str, Any]], version: int | None) -> dict:
    clean = []
    for li in layout:
        try:
            clean.append({"widget_id": str(li["widget_id"]), "x": max(0, int(li["x"])), "y": max(0, int(li["y"])),
                          "w": min(12, max(1, int(li["w"]))), "h": max(1, int(li["h"]))})
        except (KeyError, TypeError, ValueError) as e:
            raise engagements.Invalid("Each layout item needs widget_id, x, y, w, h") from e
    async with db.pool().acquire() as conn, conn.transaction():
        dash = await _check_version(conn, dashboard_id, version)
        await conn.execute("update dashboards set layout = $2, version = version + 1 where id = $1", dash["id"], clean)
    out = await get(dashboard_id)
    await publish(f"dashboard:{dashboard_id}", "layout.diff", {"version": out["version"]})
    return out
