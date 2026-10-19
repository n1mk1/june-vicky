"""The offline phrase → WidgetSpec / time-range mapper (viz/phrases.py)."""

import pytest

from vik.model.context import sample_context
from vik.viz import evaluate_widget
from vik.viz.phrases import interpret, normalise


@pytest.fixture(scope="module")
def tidewell():
    return sample_context("tidewell")


@pytest.fixture(scope="module")
def services():
    return sample_context("services-co")


def test_normalise_handles_symbols_and_number_words():
    assert normalise("R&D as % of Revenue — last six months") == "r and d as pct of revenue last 6 months"
    assert normalise("SR&ED") == "sr and ed"


def test_fr12_burn_excluding_credits_as_share_of_revenue_by_quarter(tidewell):
    i = interpret("burn excluding SR&ED as % of revenue by quarter", tidewell)
    assert i.kind == "widget" and i.spec is not None
    s = i.spec
    assert s.group_by == "quarter" and s.template == "bar"
    assert [x.ref for x in s.series] == ["pct_of(burn_ex_non_dilutive, revenue)"]
    assert "% of revenue" in s.title and "quarter" in s.title
    ev = evaluate_widget(s, tidewell)
    assert ev.status == "ok" and ev.series[0].unit == "pct"
    # same spec whichever way the credits are named
    for phrase in (
        "burn excluding credits as % of revenue by quarter",
        "burn ex-credits as a percentage of revenue quarterly",
    ):
        assert interpret(phrase, tidewell).spec == s


def test_numbers_in_the_text_never_become_values(tidewell):
    s = interpret("show revenue for the last 9 months, it was 250000", tidewell).spec
    assert s is not None and s.window is not None and s.window.last_n == 9  # a window is structure
    assert [x.ref for x in s.series] == ["revenue"] and not s.presentation.mark_lines
    assert 250000 not in evaluate_widget(s, tidewell).numbers()


@pytest.mark.parametrize(
    "phrase,months",
    [
        ("zoom to the last 6 months", 6),
        ("Zoom to the last six months", 6),
        ("focus on the past 2 quarters", 6),
        ("last 12 months", 12),
        ("zoom to the last year", 12),
        ("just show the trailing 3 years", 36),
    ],
)
def test_zoom_phrases_set_a_time_range(tidewell, phrase, months):
    i = interpret(phrase, tidewell)
    assert i.kind == "time_range" and i.last_months == months and i.spec is None


@pytest.mark.parametrize("phrase", ["reset zoom", "zoom out", "show all", "clear the time range"])
def test_reset_phrases_clear_the_time_range(tidewell, phrase):
    i = interpret(phrase, tidewell)
    assert i.kind == "time_range" and i.last_months is None


@pytest.mark.parametrize(
    "phrase", ["why is burn falling?", "how fast are we growing", "What valuation should we raise at?"]
)
def test_questions_go_to_the_panel(tidewell, phrase):
    assert interpret(phrase, tidewell).kind == "question"


def test_unknown_requests_add_nothing(tidewell):
    assert interpret("hello there", tidewell).kind == "none"
    assert interpret("   ", tidewell).kind == "none"


def test_missing_data_evaluates_to_the_missing_reason(tidewell):
    i = interpret("cash balance by month", tidewell)
    assert i.kind == "widget" and [x.ref for x in i.spec.series] == ["cash_balance"]
    ev = evaluate_widget(i.spec, tidewell)
    assert ev.status == "missing" and ev.missing is not None and "cash balance" in ev.missing.reason.lower()


def test_recurring_metrics_are_missing_for_a_services_company(services):
    i = interpret("MRR by quarter", services)
    ev = evaluate_widget(i.spec, services)
    assert ev.status == "missing" and ev.missing.reason


def test_scalar_metrics_become_kpis(tidewell):
    s = interpret("runway and burn multiple", tidewell).spec
    assert s.template == "kpi" and [x.ref for x in s.series] == ["runway_months", "burn_multiple"]
    assert interpret("NRR", tidewell).spec.template == "kpi"


def test_mixed_units_get_a_combo_with_a_right_axis(tidewell):
    s = interpret("revenue and gross margin by quarter", tidewell).spec
    assert s.template == "combo_bar_line" and s.presentation.dual_axis
    assert [(x.ref, x.axis) for x in s.series] == [("revenue", "left"), ("gross_margin", "right")]
    assert evaluate_widget(s, tidewell).status == "ok"


def test_plain_burn_follows_the_engine_convention(tidewell, services):
    assert interpret("burn", tidewell).spec.series[0].ref == "burn_ex_non_dilutive"  # credits are not revenue
    assert interpret("burn including credits", tidewell).spec.series[0].ref == "burn"


def test_breakdowns_transforms_and_templates(tidewell):
    mix = interpret("opex breakdown by quarter", tidewell).spec
    assert mix.template == "stacked_bar" and mix.presentation.stack and len(mix.series) >= 3
    assert all(x.ref.startswith("opex.") for x in mix.series)
    assert interpret("cumulative revenue", tidewell).spec.series[0].ref == "cumsum(revenue)"
    assert (
        interpret("rolling 3 month average of revenue", tidewell).spec.series[0].ref == "rolling(revenue, 3)"
    )
    assert interpret("MRR growth year over year", tidewell).spec.series[0].ref == "yoy(mrr)"
    assert interpret("revenue as a table", tidewell).spec.template == "table"
    assert interpret("revenue by quarter vs last year", tidewell).spec.compare == "yoy"
    for p in (
        "opex breakdown by quarter",
        "cumulative revenue",
        "rolling 3 month average of revenue",
        "MRR growth year over year",
    ):
        assert evaluate_widget(interpret(p, tidewell).spec, tidewell).status == "ok", p


def test_sales_and_marketing_is_not_revenue(tidewell):
    s = interpret("sales & marketing as % of revenue", tidewell).spec
    assert [x.ref for x in s.series] == ["pct_of(opex.s_and_m, revenue)"]
