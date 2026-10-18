"""Regression tests for the dashboard and visualisation findings of the 2026-10-18 QA sweep (VIZ-1 … VIZ-16).

Each test reproduces the report's repro; the fixes live in `vicky/viz/*`, `services/dashboards.py`,
`qa.py` and the display rounding in `model/figures.py`.
"""

import copy
import json
import math

import pytest

from vicky import qa
from vicky.model.context import sample_context
from vicky.model.figures import fmt_money, fmt_value
from vicky.viz import WidgetSpec, build_option, evaluate_widget
from vicky.viz.evaluate import _fmt
from vicky.viz.phrases import interpret


@pytest.fixture(scope="module")
def tidewell():
    return sample_context("tidewell")


def _spec(template="line", refs=("mrr",), **kw) -> WidgetSpec:
    return WidgetSpec.model_validate({"template": template, "title": kw.pop("title", "Test widget"),
                                      "series": [{"ref": r} if isinstance(r, str) else r for r in refs], **kw})


def _json_safe(ev, spec) -> None:
    """The evaluated widget and its option serialise as strict JSON (no inf or NaN)."""
    json.dumps(ev.model_dump(mode="json"), allow_nan=False)
    json.dumps(build_option(spec, ev), allow_nan=False)


# ---------------------------------------------------------------- VIZ-1 / VIZ-16: no value → missing, never a crash

@pytest.mark.parametrize("template,ref,window", [
    ("kpi", "sum(revenue)/0", None),
    ("kpi", "1/0", None),                                    # VIZ-16: was "ok" with display "n/a"
    ("kpi", "sum(revenue)", {"from": "2030-01"}),
    ("gauge_ring", "sum(revenue)/0", None),
    ("gauge_ring", "avg(gross_margin)", {"from": "2030-01"}),
])
def test_scalar_without_a_value_is_missing(template, ref, window, tidewell):
    spec = _spec(template, [ref], **({"window": window} if window else {}))
    ev = evaluate_widget(spec, tidewell)
    assert ev.status == "missing", (ev.status, ev.error)
    assert ev.missing is not None and "no value" in ev.missing.reason
    assert ev.kpi is not None and ev.kpi.primary.value is None and ev.kpi.primary.missing is not None
    _json_safe(ev, spec)


def test_mark_line_without_a_value_is_left_out(tidewell):
    spec = _spec("line", ["mrr"], presentation={"mark_lines": [{"label": "Nothing", "value_ref": "sum(revenue)/0"},
                                                               {"label": "Average", "value_ref": "avg(mrr)"}]})
    ev = evaluate_widget(spec, tidewell)
    assert ev.status == "ok", ev.error
    assert [m.label for m in ev.mark_lines] == ["Average"]


def test_secondary_kpi_without_a_value_is_missing(tidewell):
    ev = evaluate_widget(_spec("kpi", ["arr", "1/0"]), tidewell)
    assert ev.status == "ok"
    assert ev.kpi.secondary[0].missing is not None and ev.kpi.secondary[0].value is None


# ---------------------------------------------------------------- VIZ-2: non-finite values

HUGE = "revenue" + " * 1e15" * 20 + " * 1000"  # about 1e308: finite, but any sum of two overflows


@pytest.mark.parametrize("template,ref", [
    ("line", f"rolling({HUGE}, 3)"),
    ("line", f"cumsum({HUGE})"),
    ("line", f"sum({HUGE}, {HUGE})"),
    ("line", f"avg({HUGE}, {HUGE})"),
    ("line", f"mom({HUGE} * 1000) "),
    ("kpi", f"sum({HUGE})"),
    ("kpi", f"avg({HUGE})"),
    ("waterfall", HUGE),
])
def test_overflow_never_raises(template, ref, tidewell):
    spec = _spec(template, [ref])
    ev = evaluate_widget(spec, tidewell)  # used to raise OverflowError
    assert ev.status in ("ok", "missing", "error")
    assert all(math.isfinite(n) for n in ev.numbers())
    _json_safe(ev, spec)


def test_fmt_non_finite_is_na():
    assert _fmt(math.inf) == "n/a" and _fmt(-math.inf, "pct") == "n/a" and _fmt(math.nan) == "n/a"
    assert fmt_value(math.inf, "cad") == "n/a" and fmt_value(math.nan, "pct") == "n/a"


def test_non_finite_cell_is_a_gap(tidewell):
    ctx = copy.deepcopy(tidewell)
    p = ctx.model.periods[-3]
    ctx.model.cells["revenue.recurring"][p].value = math.inf
    for spec in (_spec("line", ["mrr"]), _spec("line", ["revenue.recurring"], group_by="quarter"),
                 _spec("kpi", ["sum(revenue.recurring)"])):
        ev = evaluate_widget(spec, ctx)
        assert ev.status in ("ok", "missing"), ev.error
        _json_safe(ev, spec)
    ev = evaluate_widget(_spec("line", ["mrr"]), ctx)
    pt = next(x for x in ev.series[0].points if x.period == p)
    assert pt.value is None and "out of range" in pt.formula


def test_non_finite_engine_figure_is_missing_in_a_kpi(tidewell):
    ctx = copy.deepcopy(tidewell)
    ctx.figures["arr"] = ctx.figures["arr"].model_copy(update={"value": math.inf})
    spec = _spec("kpi", ["arr", "mrr"])
    ev = evaluate_widget(spec, ctx)
    assert ev.status == "missing" and "out of range" in ev.missing.reason
    _json_safe(ev, spec)


# ---------------------------------------------------------------- VIZ-3: waterfall across zero

def test_waterfall_crossing_zero(tidewell):
    spec = _spec("waterfall", ["net_income + 60000"], window={"last_n": 6})
    ev = evaluate_widget(spec, tidewell)
    assert ev.status == "ok", ev.error
    base, up, down = ev.series
    assert [s.role for s in ev.series] == ["waterfall_base", "waterfall_up", "waterfall_down"]
    # the signed changes, straight from the model
    ni = {p: c.value for p, c in tidewell.model.cells["net_income"].items()}
    changes = [ni[p] + 60000 for p in ev.periods]
    assert any(c > 0 for c in changes) and any(c < 0 for c in changes)
    cum = 0.0
    for i, v in enumerate(changes):
        assert base.points[i].value == pytest.approx(cum)  # the bar starts at the running total before
        # the change split exactly: up = max(v, 0), down = min(v, 0), both defined (ECharts stacks "all" onto
        # the previous series even where it is empty, so a gap there would hide the bar)
        assert up.points[i].value == pytest.approx(max(v, 0)) and down.points[i].value == pytest.approx(min(v, 0))
        cum += v
    assert cum > 0 > min(changes)  # the running total crossed zero in the window

    opt = build_option(spec, ev)
    assert {s.get("stackStrategy") for s in opt["series"]} == {"all"}
    # stacking base + change lands on the running total after each step
    rows = opt["dataset"]["source"][1:]
    total = 0.0
    for row, v in zip(rows, changes, strict=True):
        b, u, d = row[1], row[2], row[3]
        total += v
        assert b + u + d == pytest.approx(total)
    # provenance carries the signed change, not a helper height
    for j, period in enumerate(ev.periods):
        sign_series = "1" if changes[j] >= 0 else "2"
        assert opt["_provenance"][sign_series][period]["value"] == pytest.approx(changes[j])
    assert "0" not in opt["_provenance"]


# ---------------------------------------------------------------- VIZ-4: phrase mapper picks the asked-for measure

@pytest.mark.parametrize("phrase,ref", [
    ("chart non-recurring revenue", "revenue.one_time"),
    ("chart non recurring revenue", "revenue.one_time"),
    ("chart one-time revenue", "revenue.one_time"),
    ("chart burn incl. credits", "burn"),
    ("chart burn ex. credits", "burn_ex_non_dilutive"),
    ("show burn multiple ex. credits", "burn_multiple_ex_credits"),
    ("chart other opex", "opex.other"),
    ("show net new arr", "net_new_arr_l12m"),
    ("chart recurring revenue", "revenue.recurring"),
])
def test_phrase_mapper_measure(phrase, ref, tidewell):
    it = interpret(phrase, tidewell)
    assert it.kind == "widget" and it.spec is not None
    assert [s.ref for s in it.spec.series] == [ref]


def test_phrase_mapper_rolling_window_matches_the_ask(tidewell):
    it = interpret("3 month rolling average of revenue by quarter", tidewell)
    assert it.spec is not None
    ev = evaluate_widget(it.spec, tidewell)
    assert ev.status == "ok", ev.error
    # a 3-month average: 3 monthly points, not 2 quarters (6 months)
    last = ev.series[0].points[-1]
    assert len({i.period for i in last.inputs}) == 3


def test_phrase_mapper_number_words_still_set_windows(tidewell):
    it = interpret("revenue over the last three months", tidewell)
    assert it.spec is not None and it.spec.window is not None and it.spec.window.last_n == 3
    it = interpret("revenue for the last twelve months", tidewell)
    assert it.spec is not None and it.spec.window is not None and it.spec.window.last_n == 12


def test_chart_it_matches_the_measure_asked_about(tidewell):
    a = qa.answer("one-time revenue by month?", tidewell)
    if a["chart"]:
        spec = interpret(a["chart"], tidewell).spec
        assert spec is not None and [s.ref for s in spec.series] == ["revenue.one_time"]
    # a request that would chart another measure is not offered
    assert qa.drawable("show revenue", tidewell, "revenue.one_time") is None
    assert qa.drawable("show one-time revenue by month", tidewell, "revenue.one_time") is not None
    assert qa.drawable("show arr", tidewell, "arr") == "show arr"


# ---------------------------------------------------------------- VIZ-5: chat answers the figure asked about

@pytest.mark.parametrize("question,want", [
    ("burn including credits?", "burn_incl_credits"),
    ("burn incl. credits?", "burn_incl_credits"),
    ("what is burn with credits", "burn_incl_credits"),
    ("burn excluding credits?", "burn"),
    ("burn ex. credits?", "burn"),
    ("net new ARR?", "net_new_arr_l12m"),
    ("what's our net new arr", "net_new_arr_l12m"),
    ("ARR?", "arr"),
])
def test_qa_answers_the_figure_asked_about(question, want, tidewell):
    a = qa.answer(question, tidewell)
    f = tidewell.figures[want]
    assert a["topic"] == want, a["reply"]
    assert a["reply"].startswith(f"{f.label} is {f.display}"), a["reply"]


# ---------------------------------------------------------------- VIZ-8: no running totals of balances

@pytest.mark.parametrize("ref", ["cumsum(cash_balance)", "cumsum(customers.count)", "cumsum(cash_balance * 2)"])
def test_cumsum_refuses_balances(ref, tidewell):
    ev = evaluate_widget(_spec("line", [ref]), tidewell)
    assert ev.status == "error" and "balance" in (ev.error or "")


def test_cumulative_cash_phrase_explains(tidewell):
    it = interpret("cumulative cash", tidewell)
    ev = evaluate_widget(it.spec, tidewell)
    assert ev.status == "error" and "balance" in (ev.error or "")
    assert evaluate_widget(_spec("line", ["cumsum(revenue)"]), tidewell).status == "ok"


# ---------------------------------------------------------------- VIZ-9: scatter

def test_scatter_needs_two_series(tidewell):
    spec = _spec("scatter", ["opex.s_and_m"])
    ev = evaluate_widget(spec, tidewell)
    assert ev.status == "error" and "two" in (ev.error or "")
    ok = evaluate_widget(_spec("scatter", ["opex.s_and_m", "revenue.recurring"]), tidewell)
    assert ok.status == "ok"


def test_scatter_with_compare_plots_the_two_measures(tidewell):
    spec = _spec("scatter", ["opex.s_and_m", "revenue.recurring"], compare="previous_period")
    ev = evaluate_widget(spec, tidewell)
    assert ev.status == "ok"
    opt = build_option(spec, ev)
    first = opt["dataset"]["source"][1]
    period = opt["_meta"]["periods"][0]
    prov = opt["_provenance"]["0"][period]
    assert first[1] == prov["x"]["value"] and first[2] == prov["y"]["value"]
    assert opt["_meta"]["units"] == {"x": ev.series[0].unit, "y": next(s for s in ev.series if s.ref == "revenue.recurring"
                                                                       and s.role == "value").unit}
    xs = {p.value for p in ev.series[0].points}
    ys = {p.value for s in ev.series if s.ref == "revenue.recurring" and s.role == "value" for p in s.points}
    assert first[1] in xs and first[2] in ys


# ---------------------------------------------------------------- VIZ-10: pct × 100

@pytest.mark.parametrize("ref", ["gross_margin * 100", "100 * gross_margin", "pct_of(cogs, revenue) * 100"])
def test_pct_times_100_is_rejected(ref, tidewell):
    ev = evaluate_widget(_spec("line", [ref]), tidewell)
    assert ev.status == "error" and "fraction" in (ev.error or "")
    assert evaluate_widget(_spec("line", ["revenue * 100"]), tidewell).status == "ok"


# ---------------------------------------------------------------- VIZ-11 / VIZ-14: display rounding

@pytest.mark.parametrize("value,unit,want", [
    (0.125, "pct", "13%"),        # half-up, as the frontend's toFixed does (Python's format gives "12%")
    (0.0125, "pct", "1.3%"),
    (0.92, "pct", "92%"),
    (0.0999, "pct", "10%"),       # rounds to 10%, so the whole-percent tier
    (0.0994, "pct", "9.9%"),
    (-0.0004, "pct", "0.0%"),
    (999.6, "cad", "$1,000"),
    (999.4, "cad", "$999"),
    (9_999.6, "cad", "$10.0K"),
    (999_999.9, "cad", "$1.00M"),
    (999_949, "cad", "$999.9K"),
    (-0.4, "cad", "$0"),
    (-1_500, "cad", "-$1,500"),
    (2.5, "cad", "$3"),
    (1_290_000, "cad", "$1.29M"),
    (8.25, "months", "8.3 mo"),
    (0.625, "x", "0.63x"),
])
def test_display_rounding(value, unit, want):
    assert fmt_value(value, unit) == want


def test_fmt_money_tiers():
    assert fmt_money(114_400) == "$114.4K"
    assert fmt_money(3_200) == "$3,200"


def test_engine_displays_unchanged(tidewell):
    """The established sample displays (FR-1) keep their text under half-up rounding."""
    f = tidewell.figures
    assert f["arr"].display == "$1.29M" and f["gross_margin"].display == "92%" and f["nrr"].display == "88%"
    assert f["cmgr_12m"].display == "9.0%" and f["cmgr_recent"].display == "5.0%" and f["burn"].display == "$58.4K"


# ---------------------------------------------------------------- dashboards service (Postgres + Redis)

async def _active(api_client) -> dict:
    from tests.helpers import load_and_confirm

    await api_client.post("/auth/access", json={"code": "vicky-demo"})
    r = await api_client.get("/dashboards/active")
    if r.status_code == 404:
        await load_and_confirm(api_client, "tidewell")
        r = await api_client.get("/dashboards/active")
    assert r.status_code == 200, r.text
    return r.json()


def _overlaps(boxes: list[tuple[int, int, int, int]]) -> list[tuple]:
    out = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]:
                out.append((a, b))
    return out


def _boxes(layout: list[dict]) -> list[tuple[int, int, int, int]]:
    from vicky.viz.defaults import RESERVED

    return [(x["x"], x["y"], x["w"], x["h"]) for x in layout] + [(r["x"], r["y"], r["w"], r["h"]) for r in RESERVED]


@pytest.mark.db
async def test_add_widget_rejects_specs_that_are_not_ok(api_client):
    d = await _active(api_client)
    for spec in ({"template": "kpi", "title": "Nothing", "series": [{"ref": "sum(revenue)/0"}]},
                 {"template": "kpi", "title": "Late", "series": [{"ref": "sum(revenue)"}], "window": {"from": "2030-01"}},
                 {"template": "line", "title": "Bad", "series": [{"ref": "gross_margin * 100"}]},
                 {"template": "kpi", "title": "Missing", "series": [{"ref": "revenue_churn_rate"}]}):
        r = await api_client.post(f"/dashboards/{d['id']}/widgets", json={"spec": spec, "version": d["version"]})
        assert r.status_code == 422, (spec, r.status_code, r.text)
        assert r.json()["detail"]
    after = (await api_client.get(f"/dashboards/{d['id']}")).json()
    assert len(after["widgets"]) == len(d["widgets"]) and after["version"] == d["version"]


@pytest.mark.db
async def test_one_broken_widget_does_not_break_the_dashboard(api_client, monkeypatch):
    from vicky import db
    from vicky.services import dashboards

    d = await _active(api_client)
    bad = {"template": "kpi", "title": "Explodes", "series": [{"ref": "sum(revenue)"}]}
    wid = await db.fetchval("""insert into widgets (dashboard_id, spec, spec_hash, created_by, "order", role)
                               values ($1::uuid, $2, 'test-explodes', 'founder', 999, 'custom') returning id::text""",
                            d["id"], bad)
    real = dashboards.evaluate_widget

    def boom(spec, ctx):
        if spec.title == "Explodes":
            raise OverflowError("cannot convert float infinity to integer")
        return real(spec, ctx)

    monkeypatch.setattr(dashboards, "evaluate_widget", boom)
    try:
        r = await api_client.get(f"/dashboards/{d['id']}")
        assert r.status_code == 200, r.text
        w = next(x for x in r.json()["widgets"] if x["id"] == wid)
        assert w["status"] == "error" and w["evaluated"]["status"] == "error" and w["evaluated"]["error"]
        assert all(x["status"] in ("ok", "missing") for x in r.json()["widgets"] if x["id"] != wid)
    finally:
        monkeypatch.undo()
        await db.execute("delete from widgets where id::text = $1", wid)


@pytest.mark.db
async def test_dismissed_default_widgets_stay_dismissed(api_client):
    from vicky import db
    from vicky.services import dashboards, engagements

    d = await _active(api_client)
    roles = {w["role"]: w for w in d["widgets"]}
    assert "opex_mix" in roles
    r = await api_client.delete(f"/dashboards/{d['id']}/widgets/{roles['opex_mix']['id']}")
    assert r.status_code == 200, r.text
    ctx = await engagements.context(d["engagement_id"])
    await dashboards.ensure_default(d["engagement_id"], ctx)  # what every re-confirm does
    after = (await api_client.get(f"/dashboards/{d['id']}")).json()
    assert "opex_mix" not in {w["role"] for w in after["widgets"]}

    # a default whose spec changed is updated in place, not added a second time
    trend = next(w for w in after["widgets"] if w["role"] == "trend")
    stale = {**trend["spec"], "title": "An older title"}
    await db.execute("update widgets set spec = $2, spec_hash = 'stale-trend' where id::text = $1", trend["id"], stale)
    await dashboards.ensure_default(d["engagement_id"], ctx)
    again = (await api_client.get(f"/dashboards/{d['id']}")).json()
    trends = [w for w in again["widgets"] if w["role"] == "trend"]
    assert len(trends) == 1 and trends[0]["id"] == trend["id"] and trends[0]["spec"]["title"] == trend["spec"]["title"]
    defaults = [w["role"] for w in again["widgets"] if w["role"] not in ("custom", "")]
    assert len(defaults) == len(set(defaults))


@pytest.mark.db
async def test_default_layout_is_stored_without_overlaps(api_client):
    from vicky import db
    from vicky.services import dashboards, engagements

    d = await _active(api_client)
    eid = d["engagement_id"]
    ctx = await engagements.context(eid)
    # build a second default dashboard for the same engagement from scratch, then put the real one back
    await db.execute("update dashboards set name = 'fixviz-moved' where engagement_id = $1::uuid and name = 'default'", eid)
    did = None
    try:
        did = await dashboards.ensure_default(eid, ctx)
        dash = await db.fetchrow("select * from dashboards where id::text = $1", did)
        assert dash["layout"] and not _overlaps(_boxes(dash["layout"]))
        # widgets unlocked on a later confirm go below everything already there
        await db.execute("delete from widgets where dashboard_id = $1::uuid and role in ('opex_mix', 'trend')", did)
        left = {r["id"] for r in await db.fetch("select id::text as id from widgets where dashboard_id = $1::uuid", did)}
        await db.execute("update dashboards set layout = $2 where id::text = $1", did,
                         [x for x in dash["layout"] if x["widget_id"] in left])
        await dashboards.ensure_default(eid, ctx)
        dash = await db.fetchrow("select * from dashboards where id::text = $1", did)
        assert not _overlaps(_boxes(dash["layout"]))
        assert len(dash["layout"]) == await db.fetchval("select count(*) from widgets where dashboard_id = $1::uuid", did)
    finally:
        if did:
            await db.execute("delete from dashboards where id::text = $1", did)
        await db.execute("update dashboards set name = 'default' where engagement_id = $1::uuid and name = 'fixviz-moved'", eid)


@pytest.mark.db
async def test_layout_save_drops_duplicates_and_clamps_x(api_client):
    d = await _active(api_client)
    first = d["layout"][0]
    layout = [{**first, "x": 11, "w": 6}, {**first, "x": 0, "y": 40}] + d["layout"][1:]
    r = await api_client.patch(f"/dashboards/{d['id']}/layout", json={"layout": layout, "version": d["version"]})
    assert r.status_code == 200, r.text
    saved = r.json()["layout"]
    ids = [x["widget_id"] for x in saved]
    assert len(ids) == len(set(ids))
    mine = next(x for x in saved if x["widget_id"] == first["widget_id"])
    assert mine["w"] == 6 and mine["x"] == 6 and mine["y"] == first["y"]
    assert all(0 <= x["x"] and x["x"] + x["w"] <= 12 for x in saved)
