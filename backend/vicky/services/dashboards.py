"""Dashboards: stored widget specs + layout; values are evaluated by code on every read.

`version` is optimistic concurrency: writes carry the version they saw and get 409 when it
moved. Every change is published on `dashboard:{id}` so other tabs refresh.

`time_range` is the dashboard-wide zoom every chart's dataZoom follows. It is stored as asked
(`{last_months}` or `{from, to}` months) and resolved against the data's latest period on read.
`chat` maps a request to a widget or a time range with the offline phrase mapper (viz/phrases.py);
the spec is evaluated by code before it is added, and missing data answers with the reason.
"""

import re
from typing import Any

from vicky import db, qa
from vicky.model.context import TruthContext
from vicky.model.currencies import CURRENCIES
from vicky.model.metrics import label_period
from vicky.realtime import publish
from vicky.services import engagements
from vicky.viz import WidgetSpec, build_option, default_dashboard, evaluate_widget, spec_hash
from vicky.viz.defaults import RESERVED
from vicky.viz.evaluate import period_bounds
from vicky.viz.phrases import _CHART_VERB, interpret, normalise
from vicky.viz.spec import spec_json

CURRENCY_LIST = [{"code": c, "name": n, "symbol": sym.strip()} for c, (n, sym) in CURRENCIES.items()]

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


async def _ctx_for_dashboard(dashboard_id: str, currency: str | None = None) -> tuple[dict, TruthContext]:
    dash = await db.fetchrow("select * from dashboards where id::text = $1", dashboard_id)
    if dash is None:
        raise engagements.NotFound("dashboard")
    return dash, await engagements.context(str(dash["engagement_id"]), currency)


async def get(dashboard_id: str, theme: str = "vicky-dark", currency: str | None = None) -> dict:
    """The dashboard with every widget evaluated; money in `currency` (default: the reporting currency),
    converted at Bank of Canada rates for each period."""
    theme = theme if theme in THEMES else THEMES[0]
    dash, ctx = await _ctx_for_dashboard(dashboard_id, currency)
    rows = await db.fetch('select * from widgets where dashboard_id = $1 order by "order", created_at', dash["id"])
    widgets = []
    for r in rows:
        evaluated, option = _evaluated(r["spec"], ctx, theme)
        widgets.append({"id": str(r["id"]), "role": r["role"], "spec": r["spec"], "status": evaluated["status"],
                        "evaluated": evaluated, "option": option, "created_by": r["created_by"]})
    ids = {w["id"] for w in widgets}
    return {"id": str(dash["id"]), "engagement_id": str(dash["engagement_id"]), "version": dash["version"],
            "company": ctx.company, "truthpack_version": ctx.version, "currency": ctx.currency,
            "reporting_currency": ctx.profile.get("reporting_currency", ctx.currency), "currencies": CURRENCY_LIST,
            "layout": [li for li in (dash["layout"] or []) if li.get("widget_id") in ids],
            "reserved": [dict(r) for r in RESERVED], "time_range": resolve_time_range(dash["time_range"], ctx),
            "widgets": widgets}


async def active(theme: str = "vicky-dark", currency: str | None = None) -> dict:
    eid = await engagements.require_confirmed()
    did = await db.fetchval("select id::text from dashboards where engagement_id = $1 and name = 'default'", eid)
    if did is None:
        did = await ensure_default(eid, await engagements.context(eid))
    return await get(did, theme, currency)


async def preview(dashboard_id: str, spec: dict, theme: str = "vicky-dark", currency: str | None = None) -> dict:
    _, ctx = await _ctx_for_dashboard(dashboard_id, currency)
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


async def add_widget(dashboard_id: str, spec: dict, version: int | None, created_by: str = "founder",
                     currency: str | None = None) -> dict:
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
    out = await get(dashboard_id, currency=currency)
    await publish(f"dashboard:{dashboard_id}", "widget.diff",
                  {"version": out["version"], "op": "add", "title": ws.title, "by": created_by})
    return out


async def remove_widget(dashboard_id: str, widget_id: str, currency: str | None = None) -> dict:
    async with db.pool().acquire() as conn, conn.transaction():
        dash = await _check_version(conn, dashboard_id, None)
        n = await conn.execute("delete from widgets where dashboard_id = $1 and id::text = $2", dash["id"], widget_id)
        if n.endswith(" 0"):
            raise engagements.NotFound("widget")
        layout = [x for x in (dash["layout"] or []) if x.get("widget_id") != widget_id]
        await conn.execute("update dashboards set layout = $2, version = version + 1 where id = $1", dash["id"], layout)
    out = await get(dashboard_id, currency=currency)
    await publish(f"dashboard:{dashboard_id}", "widget.diff", {"version": out["version"], "op": "remove", "widget_id": widget_id})
    return out


async def set_layout(dashboard_id: str, layout: list[dict[str, Any]], version: int | None,
                     currency: str | None = None) -> dict:
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
    out = await get(dashboard_id, currency=currency)
    await publish(f"dashboard:{dashboard_id}", "layout.diff", {"version": out["version"]})
    return out


# ---------------------------------------------------------------- time range

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _shift(ym: tuple[int, int], months: int) -> str:
    i = ym[0] * 12 + (ym[1] - 1) + months
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def clean_time_range(tr: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate a time range: `{last_months: 1–240}` or `{from, to}` as YYYY-MM; empty clears it."""
    if not tr:
        return None
    if tr.get("last_months") is not None:
        try:
            n = int(tr["last_months"])
        except (TypeError, ValueError) as e:
            raise engagements.Invalid("last_months must be a whole number of months") from e
        if not 1 <= n <= 240:
            raise engagements.Invalid("last_months must be between 1 and 240")
        return {"last_months": n}
    lo, hi = tr.get("from"), tr.get("to")
    if not (isinstance(lo, str) and isinstance(hi, str) and _MONTH_RE.match(lo) and _MONTH_RE.match(hi)):
        raise engagements.Invalid("A time range needs last_months, or from and to as YYYY-MM")
    return {"from": min(lo, hi), "to": max(lo, hi)}


def resolve_time_range(tr: dict[str, Any] | None, ctx: TruthContext) -> dict[str, Any] | None:
    """`{last_months?, from, to, label}`, months resolved against the data's latest period."""
    if not tr or not ctx.model.periods:
        return None
    if tr.get("last_months"):
        n = int(tr["last_months"])
        end = period_bounds(ctx.model.periods[-1])[1]
        lo, hi = _shift(end, -(n - 1)), _shift(end, 0)
        name = f"Last {n // 12} years" if n % 12 == 0 and n > 12 else f"Last {n} month{'s' if n > 1 else ''}"
    else:
        lo, hi, name = tr["from"], tr["to"], "Custom range"
    return {**tr, "from": lo, "to": hi, "label": f"{name} · {label_period(lo)} → {label_period(hi)}"}


async def set_time_range(dashboard_id: str, time_range: dict[str, Any] | None, version: int | None,
                         currency: str | None = None) -> dict:
    clean = clean_time_range(time_range)
    async with db.pool().acquire() as conn, conn.transaction():
        dash = await _check_version(conn, dashboard_id, version)
        await conn.execute("update dashboards set time_range = $2, version = version + 1 where id = $1",
                           dash["id"], clean)
    out = await get(dashboard_id, currency=currency)
    await publish(f"dashboard:{dashboard_id}", "time_range.diff",
                  {"version": out["version"], "time_range": out["time_range"]})
    return out


# ---------------------------------------------------------------- chat (offline phrase mapper)

NOT_UNDERSTOOD = ("I can chart a metric from your data or zoom the dashboard. Try “burn excluding credits as % of "
                  "revenue by quarter” or “zoom to the last 6 months”.")
_GROUPED = re.compile(r"\b(?:by|per|each|every) (?:month|quarter|year)s?\b|\b(?:monthly|quarterly) (?:chart|trend|view)\b")
_ASKING = re.compile(r"^(?:what|whats|what's|which|how|when|where|who|why|is|are|was|were|did|does|do|can|could|tell me|"
                     r"give me the|list|explain|compare|summari[sz]e|show me how)\b")


async def _log(dashboard_id: str, role: str, content: str, tool_calls: list[dict] | None = None) -> None:
    await db.execute("insert into dashboard_messages (dashboard_id, role, content, tool_calls) "
                     "values ($1::uuid, $2::message_role, $3, $4)", dashboard_id, role, content, tool_calls or [])


async def chat(dashboard_id: str, text: str, currency: str | None = None) -> dict:
    """One dashboard request → a reply plus the widget added or the time range set.

    The reply never carries a figure: it names the widget, the period range or the missing-data reason.
    """
    text = (text or "").strip()[:500]
    dash, ctx = await _ctx_for_dashboard(dashboard_id, currency)
    intent = interpret(text, ctx)
    out: dict[str, Any] = {"kind": intent.kind, "reply": "", "spec": None, "widget_id": None, "missing": None,
                           "time_range": None, "dashboard": None, "citations": [], "suggestions": [], "chart": None}
    tool: dict[str, Any] | None = None
    t = normalise(text)
    # A widget needs an explicit ask: a chart verb ("show", "plot", "add") or a grouping ("by quarter").
    # Everything else ("total revenue over the last 12 months", "runway?") is a question to answer.
    asks_for_chart = bool(_CHART_VERB.search(t)) or bool(_GROUPED.search(t))
    is_question = text.rstrip().endswith("?") or bool(_ASKING.match(t))
    if intent.kind in ("question", "none") or (intent.kind == "widget" and (is_question or not asks_for_chart)):
        intent = intent.model_copy(update={"kind": "answer"})

    if intent.kind == "answer":
        a = await qa.answer_any(text, ctx)
        out.update(kind="answer", reply=a["reply"], citations=a["citations"], suggestions=a["suggestions"],
                   chart=a["chart"])
        tool = {"name": "answer", "input": {"topic": a.get("topic")}}
    elif intent.kind == "time_range":
        tr = {"last_months": intent.last_months} if intent.last_months else None
        d = await set_time_range(dashboard_id, tr, None)
        out.update(dashboard=d, time_range=d["time_range"])
        out["reply"] = (f"Zoomed every chart to {d['time_range']['label']}." if d["time_range"]
                        else "Showing the full range on every chart.")
        tool = {"name": "set_time_range", "input": tr}
    elif intent.kind == "widget" and intent.spec is not None:
        spec = intent.spec
        out["spec"] = spec_json(spec)
        ev = evaluate_widget(spec, ctx)
        if ev.status == "missing" and ev.missing is not None:
            out.update(kind="missing", missing=ev.missing.model_dump(mode="json"), reply=ev.missing.reason)
        elif ev.status != "ok":
            out.update(kind="error", reply=f"I couldn't build “{spec.title}”: {ev.error}")
        else:
            h = spec_hash(spec)
            existing = await db.fetchval("select id::text from widgets where dashboard_id = $1 and spec_hash = $2",
                                         dash["id"], h)
            if existing:
                out.update(kind="exists", widget_id=existing, reply=f"“{spec.title}” is already on your dashboard.")
            else:
                d = await add_widget(dashboard_id, out["spec"], None, created_by="vicky", currency=currency)
                wid = next((w["id"] for w in d["widgets"] if w["evaluated"].get("spec_hash") == h), None)
                out.update(kind="widget_added", widget_id=wid, dashboard=d, reply=f"Added “{spec.title}”.")
                tool = {"name": "add_widget", "input": out["spec"], "widget_id": wid}
    else:
        out["reply"] = NOT_UNDERSTOOD

    await _log(dashboard_id, "founder", text)
    await _log(dashboard_id, "vicky", out["reply"], [tool] if tool else [])
    return out
