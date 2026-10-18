"""Dashboards: stored widget specs + layout; values are evaluated by code on every read.

`version` is optimistic concurrency: writes carry the version they saw and get 409 when it
moved. Every change is published on `dashboard:{id}` so other tabs refresh.

`time_range` is the dashboard-wide zoom every chart's dataZoom follows. It is stored as asked
(`{last_months}` or `{from, to}` months) and resolved against the data's latest period on read.
`chat` maps a request to a widget or a time range with the offline phrase mapper (viz/phrases.py);
the spec is evaluated by code before it is added, and missing data answers with the reason.
"""

import json
import logging
import re
from typing import Any

from vicky import db, qa
from vicky.model.context import TruthContext
from vicky.model.currencies import CURRENCIES
from vicky.model.financials import model_notes
from vicky.model.metrics import label_period
from vicky.realtime import publish
from vicky.services import engagements
from vicky.viz import WidgetSpec, build_option, default_dashboard, evaluate_widget, spec_hash
from vicky.viz.defaults import GRID_COLUMNS, RESERVED
from vicky.viz.evaluate import EvaluatedWidget, period_bounds
from vicky.viz.phrases import _CHART_VERB, interpret, normalise
from vicky.viz.spec import spec_json

CURRENCY_LIST = [{"code": c, "name": n, "symbol": sym.strip()} for c, (n, sym) in CURRENCIES.items()]

THEMES = ("vicky-dark", "vicky-light")
log = logging.getLogger(__name__)


class Conflict(Exception):
    pass


def _is_default_role(role: str | None) -> bool:
    return bool(role) and role != "custom"


async def ensure_default(engagement_id: str, ctx: TruthContext) -> str:
    """Create the default dashboard on first confirm; later confirms add newly unlocked defaults.

    One widget per default role: a role already on the dashboard has its spec brought up to date in
    place (the data may have changed it), and a role the founder removed (`dismissed_roles`) is never
    added back.
    """
    dash = await db.fetchrow(
        "select * from dashboards where engagement_id = $1 and name = 'default'", engagement_id
    )
    d = default_dashboard(ctx)
    async with db.acquire() as conn, conn.transaction():
        if dash is None:
            did = await conn.fetchval(
                "insert into dashboards (engagement_id) values ($1) returning id::text", engagement_id
            )
            layout_existing: list[dict] = []
            dismissed: set[str] = set()
        else:
            did = str(dash["id"])
            layout_existing = list(dash["layout"] or [])
            dismissed = set(dash.get("dismissed_roles") or [])
        rows = await conn.fetch(
            "select id::text as id, spec_hash, role, created_by from widgets where dashboard_id = $1 "
            'order by "order", created_at',
            did,
        )
        by_role: dict[str, list] = {}
        for r in rows:
            if _is_default_role(r["role"]):
                by_role.setdefault(r["role"], []).append(r)
        # Earlier confirms could insert a second widget for a role; only one per role is shown, so the
        # hidden copies could never be removed. Keep the first.
        extra = [r["id"] for rs in by_role.values() for r in rs[1:] if r["created_by"] == "system"]
        if extra:
            await conn.execute("delete from widgets where id::text = any($1::text[])", extra)
        live = {r["id"] for r in rows} - set(extra)
        hashes = {r["spec_hash"] for r in rows if r["id"] in live}
        layout = [x for x in layout_existing if x.get("widget_id") in live]  # a copy, without stale entries
        placed: list[tuple[str, Any]] = []
        for i, (spec, role) in enumerate(zip(d.widgets, d.roles, strict=True)):
            h = spec_hash(spec)
            if role in dismissed:
                continue
            current = by_role.get(role, [None])[0]
            if current is not None:
                if current["spec_hash"] != h and h not in hashes:
                    await conn.execute(
                        "update widgets set spec = $2, spec_hash = $3 where id::text = $1",
                        current["id"],
                        spec_json(spec),
                        h,
                    )
                    hashes.add(h)
                continue
            if h in hashes:  # the same chart is already there (added by the founder or by chat)
                continue
            wid = await conn.fetchval(
                """insert into widgets (dashboard_id, spec, spec_hash, created_by, "order", role)
                   values ($1, $2, $3, 'system', $4, $5) returning id::text""",
                did,
                spec_json(spec),
                h,
                i,
                role,
            )
            hashes.add(h)
            li = next((x for x in d.layout if x.widget_index == i), None)
            if li is not None:
                placed.append((wid, li))
        if placed:
            # A new dashboard gets the default layout as designed. Widgets unlocked later keep their relative
            # default arrangement, moved down below everything already there (and the reserved slots).
            offset = 0
            if dash is not None:
                bottom = max([x["y"] + x["h"] for x in layout] + [r["y"] + r["h"] for r in RESERVED])
                offset = max(0, bottom - min(li.y for _, li in placed))
            layout += [
                {"widget_id": wid, "x": li.x, "y": li.y + offset, "w": li.w, "h": li.h} for wid, li in placed
            ]
        await conn.execute(
            "update dashboards set layout = $2, version = version + 1 where id = $1", did, layout
        )
    return did


def _evaluated(spec: dict, ctx: TruthContext, theme: str) -> tuple[dict, dict | None]:
    """One widget's evaluation and option. A widget that can't be evaluated becomes an error tile: one bad
    stored spec must never fail the whole dashboard read."""
    ws: WidgetSpec | None = None
    try:
        ws = WidgetSpec.model_validate(spec)
        ev = evaluate_widget(ws, ctx)
        option = build_option(ws, ev, theme)
        json.dumps(option, allow_nan=False)  # the response must be strict JSON
        return ev.model_dump(mode="json"), option
    except Exception:
        log.exception("dashboard widget failed to evaluate")
        title = ws.title if ws else str((spec or {}).get("title") or "") if isinstance(spec, dict) else ""
        ev = EvaluatedWidget(
            status="error",
            template=ws.template if ws else "",
            title=title,
            spec_hash=spec_hash(ws) if ws else "",
            currency=ctx.currency,
            error="This widget couldn't be computed from the current data.",
        )
        return ev.model_dump(mode="json"), build_option(ws, ev, theme) if ws else None


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
    rows = await db.fetch(
        'select * from widgets where dashboard_id = $1 order by "order", created_at', dash["id"]
    )
    widgets = []
    for r in rows:
        evaluated, option = _evaluated(r["spec"], ctx, theme)
        widgets.append(
            {
                "id": str(r["id"]),
                "role": r["role"],
                "spec": r["spec"],
                "status": evaluated["status"],
                "evaluated": evaluated,
                "option": option,
                "created_by": r["created_by"],
            }
        )
    ids = {w["id"] for w in widgets}
    return {
        "id": str(dash["id"]),
        "engagement_id": str(dash["engagement_id"]),
        "version": dash["version"],
        "company": ctx.company,
        "truthpack_version": ctx.version,
        "currency": ctx.currency,
        "reporting_currency": ctx.profile.get("reporting_currency", ctx.currency),
        "currencies": CURRENCY_LIST,
        "model_notes": model_notes(ctx.model),
        "layout": [li for li in (dash["layout"] or []) if li.get("widget_id") in ids],
        "reserved": [dict(r) for r in RESERVED],
        "time_range": resolve_time_range(dash["time_range"], ctx),
        "widgets": widgets,
    }


async def active(theme: str = "vicky-dark", currency: str | None = None) -> dict:
    eid = await engagements.require_confirmed()
    did = await db.fetchval(
        "select id::text from dashboards where engagement_id = $1 and name = 'default'", eid
    )
    if did is None:
        did = await ensure_default(eid, await engagements.context(eid))
    return await get(did, theme, currency)


async def preview(
    dashboard_id: str, spec: dict, theme: str = "vicky-dark", currency: str | None = None
) -> dict:
    _, ctx = await _ctx_for_dashboard(dashboard_id, currency)
    WidgetSpec.model_validate(spec)  # a malformed spec is a 422
    evaluated, option = _evaluated(spec, ctx, theme)
    return {"evaluated": evaluated, "option": option}


async def _check_version(conn, dashboard_id: str, version: int | None) -> dict:
    dash = await conn.fetchrow("select * from dashboards where id::text = $1 for update", dashboard_id)
    if dash is None:
        raise engagements.NotFound("dashboard")
    if version is not None and int(version) != dash["version"]:
        raise Conflict(f"The dashboard changed (version {dash['version']}); reload and try again.")
    return dict(dash)


async def add_widget(
    dashboard_id: str,
    spec: dict,
    version: int | None,
    created_by: str = "founder",
    currency: str | None = None,
) -> dict:
    ws = WidgetSpec.model_validate(spec)
    h = spec_hash(ws)
    # Only a widget that evaluates now is stored: a spec with no value or an error would be a dead tile.
    _, ctx = await _ctx_for_dashboard(dashboard_id, currency)
    evaluated, _ = _evaluated(spec_json(ws), ctx, THEMES[0])
    if evaluated["status"] != "ok":
        why = (
            (evaluated.get("missing") or {}).get("reason")
            or evaluated.get("error")
            or "it has no value to show"
        )
        raise engagements.Invalid(f"“{ws.title}” can't be added: {why}")
    async with db.acquire() as conn, conn.transaction():
        dash = await _check_version(conn, dashboard_id, version)
        exists = await conn.fetchval(
            "select id::text from widgets where dashboard_id = $1 and spec_hash = $2", dash["id"], h
        )
        if exists is None:
            order = await conn.fetchval(
                'select coalesce(max("order"), 0) + 1 from widgets where dashboard_id = $1', dash["id"]
            )
            wid = await conn.fetchval(
                """insert into widgets (dashboard_id, spec, spec_hash, created_by, "order", role)
                   values ($1, $2, $3, $4::widget_author, $5, 'custom') returning id::text""",
                dash["id"],
                spec_json(ws),
                h,
                created_by,
                order,
            )
            layout = list(dash["layout"] or [])
            bottom = max((x["y"] + x["h"] for x in layout), default=0)
            w = 3 if ws.template in ("kpi", "gauge_ring") else 6
            layout.append({"widget_id": wid, "x": 0, "y": bottom, "w": w, "h": 5})
            await conn.execute(
                "update dashboards set layout = $2, version = version + 1 where id = $1", dash["id"], layout
            )
    out = await get(dashboard_id, currency=currency)
    await publish(
        f"dashboard:{dashboard_id}",
        "widget.diff",
        {"version": out["version"], "op": "add", "title": ws.title, "by": created_by},
    )
    return out


async def remove_widget(dashboard_id: str, widget_id: str, currency: str | None = None) -> dict:
    async with db.acquire() as conn, conn.transaction():
        dash = await _check_version(conn, dashboard_id, None)
        role = await conn.fetchval(
            "delete from widgets where dashboard_id = $1 and id::text = $2 returning role",
            dash["id"],
            widget_id,
        )
        if role is None:
            raise engagements.NotFound("widget")
        layout = [x for x in (dash["layout"] or []) if x.get("widget_id") != widget_id]
        await conn.execute(
            "update dashboards set layout = $2, version = version + 1 where id = $1", dash["id"], layout
        )
        if _is_default_role(role):  # a removed default stays removed when the data is confirmed again
            await conn.execute(
                "update dashboards set dismissed_roles = array_append(dismissed_roles, $2) "
                "where id = $1 and not ($2 = any(dismissed_roles))",
                dash["id"],
                role,
            )
    out = await get(dashboard_id, currency=currency)
    await publish(
        f"dashboard:{dashboard_id}",
        "widget.diff",
        {"version": out["version"], "op": "remove", "widget_id": widget_id},
    )
    return out


async def set_layout(
    dashboard_id: str, layout: list[dict[str, Any]], version: int | None, currency: str | None = None
) -> dict:
    clean = []
    seen: set[str] = set()
    for li in layout:
        try:
            wid, w = str(li["widget_id"]), min(GRID_COLUMNS, max(1, int(li["w"])))
            item = {
                "widget_id": wid,
                "x": min(GRID_COLUMNS - w, max(0, int(li["x"]))),
                "y": max(0, int(li["y"])),
                "w": w,
                "h": max(1, int(li["h"])),
            }
        except (KeyError, TypeError, ValueError) as e:
            raise engagements.Invalid("Each layout item needs widget_id, x, y, w, h") from e
        if wid not in seen:  # one position per widget: the first wins
            seen.add(wid)
            clean.append(item)
    async with db.acquire() as conn, conn.transaction():
        dash = await _check_version(conn, dashboard_id, version)
        await conn.execute(
            "update dashboards set layout = $2, version = version + 1 where id = $1", dash["id"], clean
        )
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


async def set_time_range(
    dashboard_id: str, time_range: dict[str, Any] | None, version: int | None, currency: str | None = None
) -> dict:
    clean = clean_time_range(time_range)
    async with db.acquire() as conn, conn.transaction():
        dash = await _check_version(conn, dashboard_id, version)
        await conn.execute(
            "update dashboards set time_range = $2, version = version + 1 where id = $1", dash["id"], clean
        )
    out = await get(dashboard_id, currency=currency)
    await publish(
        f"dashboard:{dashboard_id}",
        "time_range.diff",
        {"version": out["version"], "time_range": out["time_range"]},
    )
    return out


# ---------------------------------------------------------------- chat (offline phrase mapper)

NOT_UNDERSTOOD = (
    "I can chart a metric from your data or zoom the dashboard. Try “burn excluding credits as % of "
    "revenue by quarter” or “zoom to the last 6 months”."
)
_GROUPED = re.compile(
    r"\b(?:by|per|each|every) (?:month|quarter|year)s?\b|\b(?:monthly|quarterly) (?:chart|trend|view)\b"
)
_ASKING = re.compile(
    r"^(?:what|whats|what's|which|how|when|where|who|why|is|are|was|were|did|does|do|can|could|tell me|"
    r"give me the|list|explain|compare|summari[sz]e|show me how)\b"
)
# "can you show revenue by quarter?" is a request, not a question (but "can you show me how … ?" is one).
_POLITE_CHART = re.compile(
    r"^(?:(?:can|could|would|will) you|please|pls|plz|kindly)(?: please)? (?:show|add|chart|plot|"
    r"graph|display|visuali[sz]e|draw|make|create|put|pin|build|give me a)\b(?! me how)"
)
_REMOVE = re.compile(r"^(?:please )?(?:remove|delete|drop|hide|get rid of|take (?:off|away)|undo)\b")
CANT_REMOVE = (
    "I can't remove widgets from here: use the remove button on the widget itself. I can add a chart, "
    "answer a question about your data or zoom every chart."
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # Postgres text can't hold NUL


async def _log(dashboard_id: str, role: str, content: str, tool_calls: list[dict] | None = None) -> None:
    await db.execute(
        "insert into dashboard_messages (dashboard_id, role, content, tool_calls) "
        "values ($1::uuid, $2::message_role, $3, $4)",
        dashboard_id,
        role,
        content,
        tool_calls or [],
    )


async def chat(dashboard_id: str, text: str, currency: str | None = None) -> dict:
    """One dashboard request → a reply plus the widget added or the time range set.

    The reply never carries a figure: it names the widget, the period range or the missing-data reason.
    """
    text = _CONTROL.sub(" ", text or "").strip()[:500]
    dash, ctx = await _ctx_for_dashboard(dashboard_id, currency)
    intent = interpret(text, ctx)
    out: dict[str, Any] = {
        "kind": intent.kind,
        "reply": "",
        "spec": None,
        "widget_id": None,
        "missing": None,
        "time_range": None,
        "dashboard": None,
        "citations": [],
        "suggestions": [],
        "chart": None,
    }
    tool: dict[str, Any] | None = None
    t = normalise(text)
    # A widget needs an explicit ask: a chart verb ("show", "plot", "add") or a grouping ("by quarter").
    # Everything else ("total revenue over the last 12 months", "runway?") is a question to answer.
    asks_for_chart = bool(_CHART_VERB.search(t)) or bool(_GROUPED.search(t))
    is_question = (text.rstrip().endswith("?") or bool(_ASKING.match(t))) and not _POLITE_CHART.match(t)
    removing = bool(_REMOVE.match(t)) and intent.kind != "time_range"  # "remove zoom" is a time range
    if not removing and (
        intent.kind in ("question", "none")
        or (intent.kind == "widget" and (is_question or not asks_for_chart))
    ):
        intent = intent.model_copy(update={"kind": "answer"})

    if removing:
        out.update(kind="none", reply=CANT_REMOVE)
    elif intent.kind == "answer":
        a = await qa.answer_any(text, ctx, dashboard_id=dashboard_id)
        from vicky.kb.ask import link_figures

        out.update(
            kind="answer",
            reply=a["reply"],
            citations=await link_figures(a["citations"], ctx),
            suggestions=a["suggestions"],
            chart=a["chart"],
        )
        if a.get("offer"):
            out["offer"] = a["offer"]
        tool = {"name": "answer", "input": {"topic": a.get("topic")}}
    elif intent.kind == "time_range":
        tr = {"last_months": intent.last_months} if intent.last_months else intent.span
        d = await set_time_range(dashboard_id, tr, None, currency)
        out.update(dashboard=d, time_range=d["time_range"])
        out["reply"] = (
            f"Zoomed every chart to {d['time_range']['label']}."
            if d["time_range"]
            else "Showing the full range on every chart."
        )
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
            existing = await db.fetchval(
                "select id::text from widgets where dashboard_id = $1 and spec_hash = $2", dash["id"], h
            )
            if existing:
                out.update(
                    kind="exists", widget_id=existing, reply=f"“{spec.title}” is already on your dashboard."
                )
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


async def catch_all(
    dashboard_id: str, offer_id: str, accept: bool, currency: str | None = None
) -> dict | None:
    """Accept or decline a catch-all offer made by `chat`. Declined: nothing runs, returns None."""
    from vicky.kb import ask

    rec = await ask.take_offer(dashboard_id, offer_id)
    if not accept:
        await ask.decline(rec)
        return None
    _dash, ctx = await _ctx_for_dashboard(dashboard_id, currency)
    offline = qa.answer(rec["question"], ctx)
    a = await ask.accept(rec, ctx, offline)
    out: dict[str, Any] = {
        "kind": "answer",
        "reply": a["reply"],
        "spec": None,
        "widget_id": None,
        "missing": None,
        "time_range": None,
        "dashboard": None,
        "citations": await ask.link_figures(a.get("citations") or [], ctx),
        "suggestions": a.get("suggestions") or [],
        "chart": a.get("chart"),
    }
    await _log(dashboard_id, "vicky", out["reply"], [{"name": "catch_all", "input": {"offer_id": offer_id}}])
    return out
