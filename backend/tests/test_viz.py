"""Dashboard visualisation engine: DSL, evaluator, ECharts builder, defaults."""

import csv
import re
from collections import defaultdict
from pathlib import Path

import pytest

from vicky.model.context import sample_context
from vicky.model.figures import Figure
from vicky.model.loader import parse_number, quarter_of
from vicky.samples import SAMPLES_DIR
from vicky.viz import (
    DSLError,
    WidgetSpec,
    build_option,
    default_dashboard,
    default_widgets,
    evaluate_widget,
    parse,
    spec_hash,
)
from vicky.viz.dsl import to_source

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def tidewell():
    return sample_context("tidewell")


@pytest.fixture(scope="module")
def harbor():
    return sample_context("harbor-labs")


@pytest.fixture(scope="module")
def services():
    return sample_context("services-co")


def _csv_rows(sample: str, filename: str) -> list[dict]:
    with open(SAMPLES_DIR / sample / filename, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _spec(template="line", refs=("mrr",), **kw) -> WidgetSpec:
    return WidgetSpec.model_validate({"template": template, "title": kw.pop("title", "Test widget"),
                                      "series": [{"ref": r} if isinstance(r, str) else r for r in refs], **kw})


# ---------------------------------------------------------------- DSL

def test_pct_of_burn_ex_credits_by_quarter_matches_csv(tidewell):
    ev = evaluate_widget(_spec("bar", ["pct_of(burn_ex_non_dilutive, revenue)"], group_by="quarter"), tidewell)
    assert ev.status == "ok", ev.error
    assert ev.series[0].unit == "pct"

    sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: dict[str, int] = defaultdict(int)
    for row in _csv_rows("tidewell", "income_statement_monthly.csv"):
        q = quarter_of(row["month"])
        counts[q] += 1
        for col in ("net_income", "other_income_srred_credit", "total_revenue"):
            sums[q][col] += parse_number(row[col])
    expected = {q: -(s["net_income"] - s["other_income_srred_credit"]) / s["total_revenue"]
                for q, s in sums.items() if counts[q] == 3}

    assert ev.periods == sorted(expected)
    got = {p.period: p.value for p in ev.series[0].points}
    for q, v in expected.items():
        assert got[q] == pytest.approx(v, rel=1e-12)
    # Q3 2026 includes the SR&ED credit month: burn ex-credits removes it
    last = ev.series[0].points[-1]
    assert "182,300" in last.formula and "Q3 2026" in last.formula
    assert {i.period for i in last.inputs} >= {"2026-07", "2026-08", "2026-09"}
    assert last.source and last.source.kind == "csv" and "rows 23–25" in last.source.ref


def test_cmgr_matches_engine_figure(tidewell, harbor):
    for ctx in (tidewell, harbor):
        ev = evaluate_widget(_spec("line", ["cmgr(revenue.recurring, 12)"]), ctx)
        assert ev.status == "ok", ev.error
        fig = ctx.figures["cmgr_12m"]
        assert isinstance(fig, Figure)
        assert ev.series[0].points[-1].value == pytest.approx(fig.value, rel=1e-12)
        # leading periods without 12 months of history are trimmed
        assert ev.series[0].points[0].value is not None


def test_mrr_and_burn_match_frontend_sample(tidewell):
    ts = REPO / "frontend" / "lib" / "tidewell.ts"
    if not ts.exists():
        pytest.skip("frontend not checked out")
    rows = re.findall(r'\{ month: "(\d{4}-\d{2})", subscription: (-?\d+), services: -?\d+, cogs: -?\d+, cs: -?\d+, '
                      r"opex: -?\d+, srred: (-?\d+), net: (-?\d+) \}", ts.read_text(encoding="utf-8"))
    assert len(rows) == 24
    mrr = {m: float(sub) for m, sub, _, _ in rows}
    burn = {m: -(float(net) - float(srred)) for m, _, srred, net in rows}

    trend = next(w for w in default_widgets(tidewell) if w.template == "line")
    ev = evaluate_widget(trend, tidewell)
    assert ev.status == "ok"
    assert ev.periods == [m for m, *_ in rows]
    by_label = {s.label: {p.period: p.value for p in s.points} for s in ev.series}
    assert by_label["MRR"] == mrr
    assert by_label["Burn ex-credits"] == burn
    burn_series = next(s for s in ev.series if s.label == "Burn ex-credits")
    assert burn_series.axis == "right" and burn_series.style == "dashed"
    # plain DSL `burn` is −net income (credits included)
    ev2 = evaluate_widget(_spec("line", ["burn"], title="x"), tidewell)
    ev3 = evaluate_widget(_spec("line", ["-net_income"]), tidewell)
    assert [p.value for p in ev3.series[0].points] == [-float(net) for *_, net in rows]
    assert ev2.series[0].points[-1].value == burn["2026-09"]


@pytest.mark.parametrize("expr", [
    '__import__("os")',
    "a.b.c",
    "foo(1)",
    "x[0]",
    "lambda: 1",
    "lambda x: x",
    "revenue.total.__class__",
    "revenue.recurring.real",
    "(revenue).total",
    'eval("1")',
    'open("x")',
    "net_income if 1 else 0",
    '"text"',
    "unknown_metric + 1",
    "revenue ** 2",
    "rolling(revenue, n)",
    "lag(revenue, 1.5)",
    "pct_of(revenue)",
    "revenue revenue",
    "",
    "1 +",
    "a; b",
    "x = 1",
])
def test_dsl_rejects_unsafe_and_unknown(expr, tidewell):
    with pytest.raises(DSLError) as exc:
        parse(expr)
    assert exc.value.message
    ev = evaluate_widget(_spec("line", [expr]) if expr else _spec("line", ["mrr"]), tidewell)
    if expr:
        assert ev.status == "error" and ev.error == exc.value.message


def test_dsl_rejection_messages_are_specific():
    msgs = {}
    for expr in ['__import__("os")', "a.b.c", "foo(1)", "x[0]", "lambda: 1", '"s"']:
        with pytest.raises(DSLError) as exc:
            parse(expr)
        msgs[expr] = exc.value.message
    assert "double-underscore" in msgs['__import__("os")']
    assert "attribute access" in msgs["a.b.c"]
    assert "unknown function 'foo'" in msgs["foo(1)"]
    assert "subscripts" in msgs["x[0]"]
    assert "keyword" in msgs["lambda: 1"]
    assert "raw(" in msgs['"s"']


def test_dsl_grammar_and_unicode_operators(tidewell):
    a = parse("revenue.total × 2 − cogs ÷ 4")
    b = parse("revenue.total * 2 - cogs / 4")
    assert a == b
    assert to_source(parse("-(revenue - cogs) * 2")) == "-(revenue - cogs) * 2"
    assert to_source(parse("revenue - (cogs - net_income)")) == "revenue - (cogs - net_income)"
    assert parse('raw("income_statement_monthly:cogs_hosting")')
    # raw columns evaluate from the model's unmapped columns
    ev = evaluate_widget(_spec("line", ['raw("income_statement_monthly:cogs_hosting")']), tidewell)
    assert ev.status == "ok"
    first = _csv_rows("tidewell", "income_statement_monthly.csv")[0]
    assert ev.series[0].points[0].value == parse_number(first["cogs_hosting"])
    # unicode ops evaluate the same as ASCII
    e1 = evaluate_widget(_spec("line", ["revenue.total × 2 − cogs ÷ 4"]), tidewell)
    e2 = evaluate_widget(_spec("line", ["revenue.total * 2 - cogs / 4"]), tidewell)
    assert [p.value for p in e1.series[0].points] == [p.value for p in e2.series[0].points]


def test_dsl_functions(tidewell):
    m = tidewell.model
    rec = [m.value("revenue.recurring", p) for p in m.periods]
    ev = evaluate_widget(_spec("line", ["lag(revenue.recurring, 1)", "rolling(revenue.recurring, 3)",
                                        "mom(revenue.recurring)", "yoy(revenue.recurring)", "cumsum(revenue.recurring)",
                                        "abs(net_income)", "max(cogs, opex.customer_success)"]), tidewell)
    assert ev.status == "ok", ev.error
    s = {i: [p.value for p in x.points] for i, x in enumerate(ev.series)}
    assert ev.periods == m.periods
    assert s[0][1:] == rec[:-1] and s[0][0] is None
    assert s[1][-1] == pytest.approx(sum(rec[-3:]) / 3)
    assert s[2][-1] == pytest.approx(rec[-1] / rec[-2] - 1)
    assert s[3][-1] == pytest.approx(rec[-1] / rec[-13] - 1)
    assert s[4][-1] == pytest.approx(sum(rec))
    assert s[5][-1] == 48531
    # reductions give one number over the window
    k = evaluate_widget(_spec("kpi", ["sum(revenue.recurring)"], window={"last_n": 3}), tidewell)
    assert k.kpi.primary.value == pytest.approx(sum(rec[-3:]))
    assert "Jul 26–Sep 26" in k.kpi.primary.formula


# ---------------------------------------------------------------- evaluator

def test_windows(tidewell):
    ev = evaluate_widget(_spec("line", ["mrr"], window={"from": "2025-01", "to": "2025-06"}), tidewell)
    assert ev.periods == ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06"]
    ev = evaluate_widget(_spec("line", ["mrr"], window={"last_n": 6}), tidewell)
    assert ev.periods[0] == "2026-04" and len(ev.periods) == 6
    ev = evaluate_widget(_spec("bar", ["revenue"], group_by="quarter", window={"from": "2025-Q3"}), tidewell)
    assert ev.periods[0] == "2025-Q3" and ev.period_labels[0] == "Q3 2025"
    ev = evaluate_widget(_spec("line", ["mrr"], window={"from": "2030-01"}), tidewell)
    assert ev.status == "error"


def test_year_grouping_skips_partial_years(tidewell):
    ev = evaluate_widget(_spec("bar", ["revenue"], group_by="year"), tidewell)
    assert ev.status == "ok"
    assert ev.periods == ["2025"]
    total = sum(parse_number(r["total_revenue"]) for r in _csv_rows("tidewell", "income_statement_monthly.csv")
                if r["month"].startswith("2025"))
    assert ev.series[0].points[0].value == total
    assert any("Partial" in n for n in ev.notes)


def test_provenance_points_to_rows(tidewell):
    ev = evaluate_widget(_spec("line", ["mrr"]), tidewell)
    last = ev.series[0].points[-1]
    assert last.value == 107189
    assert last.inputs[0].field == "revenue.recurring" and last.inputs[0].period == "2026-09"
    assert last.inputs[0].dataset_id and "row 25" in (last.inputs[0].ref or "")
    assert last.source.kind == "csv" and "subscription_revenue" in last.source.ref
    assert "107,189" in last.formula and "Sep 26" in last.formula


def test_missing_data_returns_missing(services, harbor):
    ev = evaluate_widget(_spec("kpi", ["nrr"]), services)
    assert ev.status == "missing" and ev.missing is not None and ev.missing.id == "nrr"
    assert evaluate_widget(_spec("line", ["nrr"]), services).status == "missing"
    ev = evaluate_widget(_spec("line", ["mrr"]), services)
    assert ev.status == "missing" and "revenue.recurring" in ev.missing.needs
    ev = evaluate_widget(_spec("bar", [{"ref": "pct_of(burn_ex_non_dilutive, revenue)", "label": "Burn excluding credits"}],
                               group_by="quarter"), harbor)
    assert ev.status == "missing"
    assert ev.missing.needs == ["non_dilutive_income"]
    assert ev.missing.reason.startswith("Burn excluding credits needs non-dilutive income")
    # a missing secondary series is left out with a note, the rest still renders
    ev = evaluate_widget(_spec("line", ["mrr", "burn_ex_non_dilutive"]), harbor)
    assert ev.status == "ok" and len(ev.series) == 1 and ev.missing_series and ev.notes


def test_harbor_quarterly(harbor):
    ev = evaluate_widget(_spec("line", ["mrr", "revenue"], group_by="quarter"), harbor)
    assert ev.status == "ok" and ev.granularity == "quarter"
    assert ev.periods == harbor.model.periods and ev.period_labels[-1] == "Q3 2026"
    assert ev.series[0].points[-1].value == pytest.approx(harbor.figures["mrr"].value)
    rows = _csv_rows("harbor-labs", "financials_quarterly.csv")
    total = next(r for r in rows if r["Line item"] == "Total Revenue")
    assert ev.series[1].points[-1].value == parse_number(total["Q3 2026"])
    # finer than the data: falls back to quarters with a note
    ev = evaluate_widget(_spec("line", ["mrr"], group_by="month"), harbor)
    assert ev.status == "ok" and ev.granularity == "quarter" and ev.notes
    ev = evaluate_widget(_spec("line", ["cmgr(revenue.recurring, 2)"]), harbor)
    assert ev.status == "error" and "multiple of 3" in ev.error
    ev = evaluate_widget(_spec("heatmap", ["cohort_retention"]), harbor)
    assert ev.status == "ok" and ev.series and ev.series[0].points[0].value == pytest.approx(1.0)


def test_kpi_uses_engine_figures(tidewell):
    ev = evaluate_widget(_spec("kpi", ["arr", "cmgr_12m", "burn"]), tidewell)
    assert ev.status == "ok"
    assert ev.kpi.primary.value == tidewell.figures["arr"].value
    assert ev.kpi.primary.source.kind == "csv"
    assert [k.value for k in ev.kpi.secondary] == [tidewell.figures["cmgr_12m"].value, tidewell.figures["burn"].value]


# ---------------------------------------------------------------- ECharts

def _walk_numbers(obj) -> list[float]:
    if isinstance(obj, bool) or obj is None:
        return []
    if isinstance(obj, int | float):
        return [obj]
    if isinstance(obj, list):
        return [n for x in obj for n in _walk_numbers(x)]
    if isinstance(obj, dict):
        return [n for x in obj.values() for n in _walk_numbers(x)]
    return []


def _walk_strings(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        return [s for x in obj for s in _walk_strings(x)]
    if isinstance(obj, dict):
        return [s for x in obj.values() for s in _walk_strings(x)]
    return []


def test_echarts_option_numbers_come_only_from_evaluator(tidewell):
    spec = WidgetSpec.model_validate({
        "template": "combo_bar_line", "title": "Burn ex-credits as % of revenue (spec title)",
        "series": [{"ref": "burn_ex_non_dilutive", "label": "Spec label burn"},
                   {"ref": "pct_of(burn_ex_non_dilutive, revenue.total)", "label": "Spec label pct", "axis": "right"}],
        "window": {"from": "2024-Q4", "to": "2026-Q3"}, "group_by": "quarter",
        "presentation": {"labels": True, "unit": None,
                         "mark_lines": [{"label": "Spec mark line", "value_ref": "avg(burn_ex_non_dilutive)"}]},
    })
    ev = evaluate_widget(spec, tidewell)
    assert ev.status == "ok"
    opt = build_option(spec, ev, "vicky-dark")
    allowed = ev.numbers()

    source = opt["dataset"]["source"]
    nums = _walk_numbers(source)
    assert nums and all(n in allowed for n in nums)
    assert len(source) == len(ev.periods) + 1
    data_strings = set(_walk_strings(source))
    assert data_strings <= set(ev.period_labels) | {"period", "s0", "s1"}
    spec_strings = {spec.title, *(s.ref for s in spec.series), *(s.label for s in spec.series),
                    *(m.label for m in spec.presentation.mark_lines), *(m.value_ref for m in spec.presentation.mark_lines)}
    assert not data_strings & spec_strings
    assert opt["title"]["text"] == spec.title
    for s in opt["series"]:
        assert all(n in allowed for n in _walk_numbers(s.get("markLine", {}).get("data", [])))

    # structure: bars left, line right, axis-triggered tooltip, zoom, brush, theme name only, aria
    assert [s["type"] for s in opt["series"]] == ["bar", "line"]
    assert [s["yAxisIndex"] for s in opt["series"]] == [0, 1]
    assert len(opt["yAxis"]) == 2
    assert opt["xAxis"]["type"] == "category"
    assert opt["tooltip"]["trigger"] == "axis"
    assert {d["type"] for d in opt["dataZoom"]} == {"inside", "slider"}
    assert "brush" in opt and "axisPointer" in opt and "legend" in opt
    assert opt["theme"] == "vicky-dark" and opt["aria"]["enabled"] is True
    assert not any(isinstance(s, str) and s.startswith("#") for s in _walk_strings(opt))
    # click-to-explain provenance per option series and period
    prov = opt["_provenance"]["1"]["2026-Q3"]
    assert prov["value"] == ev.series[1].points[-1].value
    assert prov["formula"] and prov["inputs"] and prov["source"]["kind"] == "csv"


def test_echarts_line_dashed_and_dual_axis(tidewell):
    trend = next(w for w in default_widgets(tidewell) if w.template == "line")
    opt = build_option(trend, evaluate_widget(trend, tidewell), "vicky-light")
    assert opt["theme"] == "vicky-light"
    mrr, burn = opt["series"]
    assert mrr["type"] == burn["type"] == "line"
    assert mrr["yAxisIndex"] == 0 and burn["yAxisIndex"] == 1
    assert burn["lineStyle"]["type"] == "dashed" and "lineStyle" not in mrr
    assert opt["dataset"]["source"][-1][0] == "Sep 26"


@pytest.mark.parametrize("template,refs", [
    ("waterfall", ["net_income"]),
    ("stacked_bar", ["opex.r_and_d", "opex.s_and_m"]),
    ("area", ["revenue.recurring", "revenue.one_time"]),
    ("scatter", ["opex.s_and_m", "revenue.recurring"]),
    ("table", ["revenue", "gross_margin"]),
    ("gauge_ring", ["gross_margin", "gross_margin_incl_cs"]),
    ("kpi", ["arr"]),
])
def test_echarts_templates_build(template, refs, tidewell):
    spec = _spec(template, refs, group_by="quarter", compare="previous_period" if template == "area" else None)
    ev = evaluate_widget(spec, tidewell)
    assert ev.status == "ok", ev.error
    opt = build_option(spec, ev)
    allowed = ev.numbers()
    assert all(n in allowed for n in _walk_numbers(opt["dataset"]["source"]))
    if template == "waterfall":
        assert {s["stack"] for s in opt["series"]} == {"waterfall"}
        assert opt["series"][0]["itemStyle"]["color"] == "transparent"
    if template == "gauge_ring":
        assert [s["type"] for s in opt["series"]] == ["gauge", "gauge"]
    if template == "area":
        assert any(s.get("lineStyle", {}).get("type") == "dashed" for s in opt["series"])


def test_echarts_missing_widget(services):
    spec = _spec("kpi", ["nrr"])
    opt = build_option(spec, evaluate_widget(spec, services))
    assert opt["_meta"]["status"] == "missing" and opt["_meta"]["missing"]["id"] == "nrr"
    assert "dataset" not in opt


# ---------------------------------------------------------------- spec + defaults

def test_spec_hash_stable():
    a = {"template": "line", "title": "T", "series": [{"ref": "mrr", "label": "MRR", "axis": "left"}],
         "window": {"from": "2025-01", "last_n": 6}, "group_by": None, "presentation": {"smooth": True, "labels": False}}
    b = {"presentation": {"labels": False, "smooth": True}, "window": {"last_n": 6, "from": "2025-01"},
         "series": [{"axis": "left", "label": "MRR", "ref": "mrr"}], "title": "T", "template": "line"}
    assert spec_hash(a) == spec_hash(b) == spec_hash(WidgetSpec.model_validate(b))
    assert len(spec_hash(a)) == 64
    assert spec_hash({**a, "title": "U"}) != spec_hash(a)
    with pytest.raises(ValueError):
        WidgetSpec.model_validate({**a, "values": [1, 2, 3]})
    with pytest.raises(ValueError):
        WidgetSpec.model_validate({**a, "window": {"from": "last year"}})


@pytest.mark.parametrize("sample", ["tidewell", "harbor-labs", "services-co"])
def test_default_dashboard(sample):
    ctx = sample_context(sample)
    d = default_dashboard(ctx)
    assert len(d.widgets) == len(d.layout) == len(d.roles)
    assert d.roles[:3] == ["margin_ring", "headline_kpi", "trend"]
    assert d.widgets[0].template == "gauge_ring" and d.widgets[1].template == "kpi"
    boxes = [(li.x, li.y, li.w, li.h) for li in d.layout] + [(r["x"], r["y"], r["w"], r["h"]) for r in d.reserved]
    for x, _y, w, h in boxes:
        assert 0 <= x and x + w <= 12 and w > 0 and h > 0
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            overlap = a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
            assert not overlap, (a, b)
    for w in d.widgets:
        ev = evaluate_widget(w, ctx)
        assert ev.status in ("ok", "missing"), (w.title, ev.error)
        build_option(w, ev)
    recurring = isinstance(ctx.figures.get("arr"), Figure)
    assert d.widgets[1].series[0].ref == ("arr" if recurring else "revenue")
    has_credits = ctx.model.has("non_dilutive_income")
    assert ("burn_ex_credits" in d.roles) == has_credits
    assert ("cohort_retention" in d.roles) == bool(ctx.model.cohort_mrr)
    for role, w in zip(d.roles, d.widgets, strict=True):
        if role.startswith("missing:"):
            assert evaluate_widget(w, ctx).status == "missing"


def test_missing_tiles_for_key_metrics(tidewell):
    from vicky.model.figures import MissingFigure
    from vicky.viz.defaults import KEY_MISSING

    d = default_dashboard(tidewell)
    expected = [f for f in KEY_MISSING if isinstance(tidewell.figures.get(f), MissingFigure)]
    assert [r.split(":", 1)[1] for r in d.roles if r.startswith("missing:")] == expected


def test_no_eval_in_engine():
    src = "".join((REPO / "backend" / "vicky" / "viz" / f).read_text(encoding="utf-8")
                  for f in ("dsl.py", "evaluate.py", "echarts.py"))
    assert not re.search(r"(?<![.\w])(eval|exec|compile)\s*\(", src)
