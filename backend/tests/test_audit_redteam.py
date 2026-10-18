"""Red-team corpus for the truth audit: every Phase 0 repro from docs/qa/QA-REPORT-2026-10-18.md.

Each `BLOCKED` line slipped past `audit_text` before the fix (LLM-1, LLM-2, MET-1, MET-6, MET-21, MET-22);
each `ALLOWED` line is a correctly cited figure or a founder quote that must keep passing. The claim
tolerance (MET-5), cross-currency claims (MET-21) and the autofill round size (KB-4) are checked directly.
"""

import pytest

from vicky.audit import audit_text
from vicky.kb.autofill import Evidence, verify
from vicky.model.figures import Figure, Source
from vicky.model.truth import _tolerance, check_claim


def fig(id_: str, value: float, unit: str) -> Figure:
    return Figure(id=id_, label=id_.replace("_", " "), value=value, unit=unit, formula="test",
                  source=Source(kind="derived", ref="test"))


FIGURES = [
    fig("arr", 1_286_268, "cad"),
    fig("burn", 48_200, "cad"),
    fig("runway_months", 8.0, "months"),
    fig("burn_multiple", 0.6, "x"),
    fig("cac_payback_months", 9.0, "months"),
    fig("gross_margin", 0.45, "pct"),
    fig("customers.count", 113, "count"),
]


# ---------------------------------------------------------------- blocked: (finding id, text, founder quotes, kind)

BLOCKED = [
    # LLM-1: a quote that merely contains a short founder answer is not the founder's words.
    ("LLM-1", 'You said "Yes, and our ARR is $7.3M". Is that real?', ["Yes"], "number"),
    ("LLM-1", 'You said "Yes, and our ARR is $7.3M". Is that real?', ["yes"], "number"),
    ("LLM-1", 'So "$7.3M" it is.', ["our ARR is $7.3M"], "number"),
    # LLM-2: numbers, valuations and advice in words.
    ("LLM-2", "You burn about sixty thousand dollars a month.", None, "number"),
    ("LLM-2", "At a ten million dollar valuation this is cheap.", None, "valuation"),
    ("LLM-2", "I would accept that term sheet if I were you.", None, "advice"),
    ("LLM-2", "you should take this term sheet now", None, "advice"),
    ("LLM-2", "A strong answer: we have nine point nine million dollars in ARR.", None, "number"),
    ("LLM-2", "I'd sign that term sheet today.", None, "advice"),
    ("LLM-2", "Founders should reject this offer.", None, "advice"),
    ("LLM-2", "The company is worth about twelve million.", None, "valuation"),
    # MET-1: valuations with C$, US$, CAD, a colon, or no currency at all.
    ("MET-1", "A pre-money valuation of C$1.3M would be fair.", None, "valuation"),
    ("MET-1", "Valuation: $1.3M.", None, "valuation"),
    ("MET-1", "A valuation of CAD 1.3M is fair.", None, "valuation"),
    ("MET-1", "The company is valued at 13M.", None, "valuation"),
    ("MET-1", "A valuation of US$1.3M is fair.", None, "valuation"),
    ("MET-1", "It's worth C$13M.", None, "valuation"),
    # MET-5: a round number is held to ±5% at most, not half its leading digit.
    ("MET-5", "Your ARR is $1M.", None, "number"),
    # MET-6: whole classes of numbers that skipped the audit.
    ("MET-6", "Your ARR is 4.2M and burn is 85K a month.", None, "number"),
    ("MET-6", "ARR is S$4.2M.", None, "number"),
    ("MET-6", "ARR is CHF 4.2M.", None, "number"),
    ("MET-6", "ARR is 4.2M CAD.", None, "number"),
    ("MET-6", "Net income was -850,000.", None, "number"),
    ("MET-6", "Your cash will last 40 months.", None, "number"),
    ("MET-6", "You have runway for the next 40 months.", None, "number"),
    ("MET-6", "CAC payback is 11 and the burn multiple is 3.", None, "number"),
    ("MET-6", "You have 2000 customers.", None, "number"),
    # MET-21: money in another currency is not the reporting-currency figure.
    ("MET-21", "ARR is US$1.29M.", None, "number"),
    ("MET-21", "ARR is USD 1.29M.", None, "number"),
    ("MET-21", "ARR is 1.29M USD.", None, "number"),
    ("MET-21", "ARR is $1.29M USD.", None, "number"),
    ("MET-21", "Burn is about forty-eight thousand euros a month.", None, "number"),
    # MET-22: a named metric that has no figure must not borrow another one.
    ("MET-22", "Churn is 45% a month.", None, "number"),
]


@pytest.mark.parametrize("finding,text,quotes,kind", BLOCKED, ids=[f"{b[0]}:{b[1][:40]}" for b in BLOCKED])
def test_redteam_blocked(finding, text, quotes, kind):
    r = audit_text(text, FIGURES, founder_quotes=quotes)
    assert not r.passed, f"{finding} slipped through: {text!r} → citations {[c.figure_id for c in r.citations]}"
    assert any(f.kind == kind for f in r.findings), r.feedback()


# ---------------------------------------------------------------- allowed: (text, founder quotes, cited figure ids)

ALLOWED = [
    ("ARR is $1.29M.", None, ["arr"]),
    ("ARR is $1.3M.", None, ["arr"]),
    ("ARR is C$1.29M.", None, ["arr"]),
    ("ARR is CAD 1.29M.", None, ["arr"]),
    ("ARR is 1.29M CAD.", None, ["arr"]),
    ("ARR is 1.29M.", None, ["arr"]),
    ("Burn is 48.2K a month.", None, ["burn"]),
    ("Burn is about forty-eight thousand dollars a month.", None, ["burn"]),
    ("Runway is 8 months and the burn multiple is 0.6x.", None, ["runway_months", "burn_multiple"]),
    ("CAC payback is 9 months.", None, ["cac_payback_months"]),
    ("CAC payback is 9.", None, ["cac_payback_months"]),
    ("You have 113 customers.", None, ["customers.count"]),
    ("Gross margin is 45%.", None, ["gross_margin"]),
    ("Give me 3 milestones for 2027.", None, []),
    ("In 2025 ARR was $1.29M.", None, ["arr"]),
    ("Over the next 12 months, focus on churn.", None, []),
    ("Monthly growth, last 12 months: ARR reached $1.29M.", None, ["arr"]),
    ("ARR is $1.29M CAD.", None, ["arr"]),
    ("Try 3 versions of the pitch.", None, []),
    ("Walk me through your top 3 customers.", None, []),
    ("Two of the five partners asked about churn.", None, []),
    ("That is one question I have.", None, []),
    ('You said "we grow 10% a month". Give me 3 milestones for 2027.', ["we grow 10% a month"], []),
    ('You said "Yes, and our ARR is $7.3M". Is that real?', ["Yes, and our ARR is $7.3M"], []),
    ('You said “our ARR is $7.3M”.', ["Honestly, our ARR is $7.3M and growing."], []),
    ("You should take the churn question seriously.", None, []),
    ("I'd take a hard look at churn before the raise.", None, []),
    ("Explain how a valuation cap converts in a SAFE.", None, []),
]


@pytest.mark.parametrize("text,quotes,cited", ALLOWED, ids=[a[0][:40] for a in ALLOWED])
def test_redteam_allowed(text, quotes, cited):
    r = audit_text(text, FIGURES, founder_quotes=quotes)
    assert r.passed, f"{text!r}: {r.feedback()}"
    assert [c.figure_id for c in r.citations] == cited


# ---------------------------------------------------------------- MET-5 · claim tolerance

@pytest.mark.parametrize("claimed,unit", [(1_000_000, "cad"), (2_000_000, "cad"), (80_000, "cad"), (5_000, "count")])
def test_tolerance_is_at_most_five_percent(claimed, unit):
    assert _tolerance(claimed, unit, 0.02) <= abs(claimed) * 0.05


def test_tolerance_keeps_stated_precision_and_two_percent():
    assert _tolerance(1_300_000, "cad", 0.02) == pytest.approx(50_000)  # "1.3M" → ±50K
    assert _tolerance(1_286_268, "cad", 0.02) == pytest.approx(1_286_268 * 0.02)
    assert _tolerance(0.05, "pct", 0.02) == pytest.approx(0.005)  # "5%" → ±0.5pp


def test_check_claim_round_overstatement_contradicts():
    r = check_claim("arr", 1_000_000, "money", {"arr": fig("arr", 550_000, "cad")})
    assert r.status == "contradicts"
    assert check_claim("arr", 1_000_000, "money", {"arr": fig("arr", 1_290_000, "cad")}).status == "contradicts"
    assert check_claim("arr", 1_300_000, "money", {"arr": fig("arr", 1_286_268, "cad")}).status == "matches"


# ---------------------------------------------------------------- MET-21 · currencies in claims

@pytest.mark.parametrize("unit,status", [("usd", "unsupported"), ("eur", "unsupported"), ("cad", "matches"),
                                         ("money", "matches"), ("$", "matches"), ("", "matches")])
def test_check_claim_currency(unit, status):
    figures = {"arr": fig("arr", 1_000_000, "cad")}
    assert check_claim("arr", 1_000_000, unit, figures).status == status


# ---------------------------------------------------------------- KB-4 · autofill round size

NOTES = {"deck.md": {"path": "deck.md", "title": "Deck", "content": "We are raising $2.5M to reach Series A."}}


@pytest.mark.parametrize("value", ["$2.51M", "$2.49M", "2,510,000", "$2.6M"])
def test_autofill_rejects_a_changed_round_size(value):
    assert verify("round_size", Evidence(value=value, note="deck.md", quote="We are raising $2.5M"), NOTES) is None


@pytest.mark.parametrize("value", ["$2.5M", "2,500,000", "2.5 million", "$2.50M"])
def test_autofill_stores_the_quoted_round_size(value):
    ok = verify("round_size", Evidence(value=value, note="deck.md", quote="We are raising $2.5M"), NOTES)
    assert ok and ok[0] == 2_500_000
