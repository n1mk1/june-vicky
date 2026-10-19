"""Ask Vik: questions about the ingested data, answered by code and held to the citation audit."""

import pytest

from vik.model.context import sample_context
from vik.qa import answer, parse_when


@pytest.fixture(scope="module")
def ctx():
    return sample_context("tidewell")


CASES = [
    # (question, substrings the reply must contain)
    ("What is my ARR?", ["$1.29M"]),
    ("what was revenue in March 2026?", ["$96.5K", "Mar 2026"]),
    ("which month had the highest burn?", ["highest", "Sep 2025"]),
    ("lowest revenue month", ["lowest", "Nov 2024"]),
    ("total sales and marketing spend in 2025", ["$331.5K", "in total"]),
    ("how is ARR calculated?", ["$1.29M", "× 12"]),
    ("how did revenue change over the last 12 months?", ["Oct 2025", "Sep 2026", "up"]),
    ("compare revenue Q1 2025 vs Q1 2026", ["Q1 2025", "Q1 2026"]),
    ("list subscription revenue by month", ["Sep 2026 $107.2K"]),
    ("what does NRR mean?", ["88%"]),
    ("what's my runway?", ["8.3 mo"]),
    ("how much cash do we have?", ["$483.3K"]),
    ("how many customers do we have?", ["211"]),
    ("what are my weak spots?", ["Growth is slowing"]),
    ("what data is missing?", ["can't be computed"]),
    ("what data do you have?", ["Oct 2024", "Sep 2026"]),
    ("summarise my key metrics", ["ARR $1.29M", "Runway"]),
    ("what is hosting cost in sep 2026", ["Sep 2026"]),
    ("why is burn falling?", ["down", "$58.4K"]),
    ("what was net income in July 2026", ["Jul 2026"]),
    ("how much SR&ED did we get in 2026?", ["$182.3K"]),
    ("what's the burn multiple", ["0.62x"]),
    ("which quarter had the highest revenue", ["Q3 2026"]),
    ("how fast are we growing", ["9.0%", "5.0%"]),
    ("customer success spend last quarter", ["$51.0K"]),
    ("how much cash did we have in jun 2026", ["Jun 2026"]),
]


@pytest.mark.parametrize("question,expect", CASES)
def test_answers_are_correct_and_cited(ctx, question, expect):
    r = answer(question, ctx)
    assert r["audit"]["passed"], (question, r["audit"]["findings"])
    assert "couldn't" not in r["reply"].lower(), (question, r["reply"])
    for s in expect:
        assert s in r["reply"], (question, s, r["reply"])
    if r["topic"] not in ("missing", "inventory") and any(
        ch.isdigit() for ch in r["reply"].replace("2024", "").replace("2025", "").replace("2026", "")
    ):
        assert r["citations"], (question, "numbers without footnotes")


def test_valuation_is_declined_with_mechanics(ctx):
    r = answer("What valuation should we raise at?", ctx)
    assert r["topic"] == "valuation" and "won't put a number" in r["reply"]
    assert not any(ch.isdigit() for ch in r["reply"])


def test_unknown_question_says_so(ctx):
    r = answer("tell me about unicorns on mars", ctx)
    assert r["topic"] == "not_found" and r["suggestions"]


def test_period_parsing():
    w = parse_when("revenue in march 2026 vs q1 2025 and fy 2024", ["2026-03"])
    assert w.periods == ["2024", "2025-Q1", "2026-03"]
    assert parse_when("over the last 6 months", []).last == 6
    assert parse_when("last quarter", []).last == 3
