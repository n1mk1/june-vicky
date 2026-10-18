"""Metrics engine on the three fixtures (FR-1, FR-2, FR-3)."""

import pytest
import yaml

from tests.helpers import sample_metrics, sample_model
from vicky.model.figures import Figure, MissingFigure
from vicky.model.loader import parse_number, parse_period, parse_upload
from vicky.model.mapping import mapping_accuracy, propose_heuristic
from vicky.samples import SAMPLES_DIR


def approx(fig, value, rel=0.02):
    assert isinstance(fig, Figure), f"{fig.id} missing: {getattr(fig, 'reason', '')}"
    assert fig.value == pytest.approx(value, rel=rel), f"{fig.id}: {fig.value} != {value} ({fig.formula})"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1,234.00", 1234.0),
        ("-$57,492.00", -57492.0),
        ("(5,000)", -5000.0),
        ("$0.00", 0.0),
        ("12%", 0.12),
        ("1.2M", 1_200_000.0),
        ("", None),
        ("—", None),
        ("abc", None),
        ("£2,500", 2500.0),
    ],
)
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024-10", ("2024-10", "month")),
        ("Oct 2024", ("2024-10", "month")),
        ("Q1 2024", ("2024-Q1", "quarter")),
        ("2024-Q3", ("2024-Q3", "quarter")),
        ("Sep-26", ("2026-09", "month")),
        ("hello", None),
    ],
)
def test_parse_period(raw, expected):
    assert parse_period(raw) == expected


def test_tidewell_appendix_h():
    """FR-1: ARR $1.29M; CMGR ≈ 9% / ≈ 5%; margins 92% / 74–78%; burn ≈ $58K."""
    _, _, m = sample_metrics("tidewell")
    approx(m["mrr"], 107_189)
    approx(m["arr"], 1_286_268)
    approx(m["cmgr_12m"], 0.090, rel=0.03)
    approx(m["cmgr_recent"], 0.050, rel=0.04)
    approx(m["gross_margin"], 0.924, rel=0.01)
    approx(m["gross_margin_incl_cs"], 0.775, rel=0.01)
    approx(m["gross_margin_incl_cs_l12m"], 0.743, rel=0.01)
    approx(m["burn"], 58_421, rel=0.01)
    assert m["arr"].source.kind == "csv"
    assert "row" in m["arr"].source.ref


def test_harbor_labs_any_layout():
    """FR-2: quarterly wide layout maps ≥ 90%; metrics compute; cohort NRR/GRR; no tax credits."""
    d = SAMPLES_DIR / "harbor-labs"
    expected = yaml.safe_load((d / "expected.yaml").read_text(encoding="utf-8"))["metrics"]
    mapping = yaml.safe_load((d / "mapping.yaml").read_text(encoding="utf-8"))["mappings"]
    ds = parse_upload((d / "financials_quarterly.csv").read_bytes(), "financials_quarterly.csv")[0]
    assert ds.transposed and ds.granularity == "quarter"
    proposal = propose_heuristic(ds, "usd")
    exp = [
        {
            "source_column": e["source_column"] if e["canonical_field"] != "period" else "period",
            "canonical_field": e["canonical_field"],
        }
        for e in mapping
    ]
    assert mapping_accuracy(proposal, exp) >= 0.9

    _, model, m = sample_metrics("harbor-labs")
    approx(m["arr"], expected["arr"]["value"], rel=0.001)
    approx(m["mrr"], expected["mrr"]["value"], rel=0.001)
    approx(m["revenue_growth"], expected["revenue_growth_qoq"]["value"], rel=0.001)
    approx(m["gross_margin"], expected["gross_margin"]["value"], rel=0.001)
    approx(m["gross_margin_incl_cs"], expected["gross_margin_incl_cs"]["value"], rel=0.001)
    approx(m["nrr"], expected["nrr"]["value"], rel=0.002)
    approx(m["grr"], expected["grr"]["value"], rel=0.002)
    approx(m["top_customer_share"], expected["top_customer_share"]["value"], rel=0.002)
    approx(m["logo_churn_rate"], expected["logo_churn_rate"]["value"] / 3, rel=0.002)
    # burn = average monthly operating loss over the last two quarters (no credits to exclude)
    oi = model.series("operating_income")
    last2 = model.periods_with("operating_income")[-2:]
    approx(m["burn"], -sum(oi[p] for p in last2) / 6, rel=0.001)
    approx(m["cash_balance"], expected["runway_months"]["inputs"]["cash_balance[Q3 2026]"], rel=0.001)
    assert isinstance(m["burn_multiple_ex_credits"], MissingFigure)
    assert isinstance(m["burn_incl_credits"], MissingFigure)


def test_services_generic_only():
    """FR-3: non-recurring company → only the generic set; SaaS metrics are MissingFigures."""
    d = SAMPLES_DIR / "services-co"
    expected = yaml.safe_load((d / "expected.yaml").read_text(encoding="utf-8"))
    _, _, m = sample_metrics("services-co")
    for mid in ("arr", "mrr", "nrr", "grr", "cac_payback_months", "burn_multiple", "magic_number"):
        assert isinstance(m[mid], MissingFigure), mid
    assert isinstance(m["gross_margin"], Figure)
    exp = expected["metrics"]
    if "gross_margin" in exp:
        approx(m["gross_margin"], exp["gross_margin"]["value"], rel=0.002)


def test_model_derives_totals():
    _, model = sample_model("harbor-labs")
    p = model.periods[-1]
    assert model.value("net_income", p) == pytest.approx(model.value("operating_income", p))
