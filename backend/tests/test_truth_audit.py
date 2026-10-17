"""Claim checks (FR-5), the attack list and the audit (FR-6)."""

from tests.helpers import sample_metrics
from vicky.audit import audit_text, extract_numbers
from vicky.model.figures import Figure
from vicky.model.truth import attack_list, check_claim, quick_claims


def figs(metrics):
    return [f for f in metrics.values() if isinstance(f, Figure)]


def test_check_claim_growth_contradicts():
    _, _, m = sample_metrics("tidewell")
    r = check_claim("growth", 0.10, "pct", m)
    assert r.status == "contradicts"
    assert r.figure_id in ("cmgr_recent", "cmgr_12m")


def test_check_claim_growth_matches_12m():
    _, _, m = sample_metrics("tidewell")
    assert check_claim("monthly growth", 0.09, "pct", m, period="L12M").status == "matches"


def test_check_claim_arr_and_mrr():
    _, _, m = sample_metrics("tidewell")
    assert check_claim("arr", 1_290_000, "money", m).status == "matches"
    assert check_claim("mrr", 80_000, "money", m).status == "contradicts"


def test_check_claim_missing_is_unsupported():
    _, _, m = sample_metrics("services-co")
    assert check_claim("nrr", 1.15, "pct", m).status == "unsupported"


def test_attack_list_covers_lenses():
    s, _, m = sample_metrics("tidewell")
    items = attack_list(m, s.facts, s.profile)
    lenses = {i.lens for i in items}
    assert {"forecast", "unit_economics", "terms_cap_table"} <= lenses
    assert items[0].severity >= items[-1].severity
    assert any(i.id == "growth_decel" for i in items)


def test_quick_claims():
    cs = quick_claims("We're growing 10% a month and churn is under 1%. ARR is $1.3M.")
    metrics = {c["metric"]: c["value"] for c in cs}
    assert metrics["growth"] == 0.10
    assert metrics["churn"] == 0.01
    assert metrics["arr"] == 1_300_000


def test_audit_passes_grounded_text():
    _, _, m = sample_metrics("tidewell")
    r = audit_text("ARR is $1.29M and growth slowed to 5.0% a month from 9.0% over 12 months.", figs(m))
    assert r.passed, r.feedback()
    assert [c.figure_id for c in r.citations][:1] == ["arr"]


def test_audit_flags_wrong_number():
    _, _, m = sample_metrics("tidewell")
    r = audit_text("Your NRR is 115%, which is great.", figs(m))
    assert not r.passed
    assert any(f.kind == "number" for f in r.findings)


def test_audit_blocks_valuation():
    _, _, m = sample_metrics("tidewell")
    r = audit_text("You should raise at a $20M valuation.", figs(m))
    assert any(f.kind == "valuation" for f in r.findings)


def test_audit_requires_benchmark_source():
    _, _, m = sample_metrics("tidewell")
    r = audit_text("Top-quartile seed companies grow faster than this.", figs(m))
    assert any(f.kind == "benchmark" for f in r.findings)


def test_audit_allows_founder_quotes_and_small_counts():
    _, _, m = sample_metrics("tidewell")
    r = audit_text('You said "we grow 10% a month". Give me 3 milestones for 2027.', figs(m),
                   founder_quotes=["we grow 10% a month"])
    assert r.passed, r.feedback()


def test_extract_numbers_units():
    ns = extract_numbers("Burn is $58.4K, runway 8 months, burn multiple 0.6x, 92% margin, 113 customers.")
    assert [n["unit"] for n in ns] == ["money", "months", "x", "pct", "plain"]
