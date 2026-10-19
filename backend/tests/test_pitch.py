"""Pitch room (offline): the deck reader, the live-interrupt policy and Vik's wrap-up."""

import io
import re

import pytest
from pypdf import PdfWriter

from vik.areopagus import registry
from vik.model.context import sample_context
from vik.model.truth import check_claim
from vik.pitch import session as pitch


def _pdf(pages: int) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=960, height=540)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _check(ctx, text: str, metric: str, value: float, unit: str) -> dict:
    r = check_claim(metric, value, unit, ctx.figures, facts=ctx.facts)
    return {**r.model_dump(mode="json"), "text": text}


def test_deck_pages_render_as_slide_images():
    slides = pitch.read_deck(_pdf(3))
    assert [s["n"] for s in slides] == [1, 2, 3]
    assert all(s["image"].startswith("data:image/jpeg;base64,") for s in slides)


def test_deck_reader_refuses_what_it_cant_present():
    with pytest.raises(pitch.PitchError):
        pitch.read_deck(b"%PDF-1.4 not really")
    with pytest.raises(pitch.PitchError):
        pitch.read_deck(_pdf(pitch.MAX_PAGES + 1))


def test_a_contradiction_brings_an_interrupt_quoting_the_engine():
    """FR-11 (offline): "growing 10% a month" contradicts the data; the line quotes the engine's figure."""
    ctx = sample_context("tidewell")
    panel = [registry.builtins()[i] for i in ("aristotle", "thales", "socrates")]
    c = _check(ctx, "growing 10% a month", "mom growth", 0.10, "pct")
    assert c["status"] == "contradicts"
    p, chosen, score = pitch._candidate(panel, [c])
    assert chosen is c and score >= pitch.INTERRUPT_BAR
    line = pitch._interrupt_line(p, c, "We're growing 10% a month.", ctx)
    assert c["figure"]["display"] in line and '"growing 10% a month"' in line
    assert len(re.findall(r"[.?!](?:\s|$)", line)) <= 2  # at most two sentences


def test_a_matching_claim_never_interrupts():
    ctx = sample_context("tidewell")
    panel = [registry.builtins()["socrates"]]
    arr = ctx.figures["arr"]
    c = _check(ctx, "ARR is 1.29M", "arr", arr.value, "money")
    assert c["status"] == "matches"
    assert pitch._candidate(panel, [c]) is None


def test_hand_back_and_wrap_up_add_no_figure():
    assert not re.search(r"\d", pitch._hand_back([{"status": "contradicts"}]))
    st = {
        "ledger": [
            {"source": "spoken", "status": "contradicts"},
            {"source": "spoken", "status": "matches"},
            {"source": "deck", "status": "contradicts"},
        ],
        "interrupts": [{}],
        "segments": [{"text": "Um, we basically grow, you know, fast."}],
    }
    line = pitch._wrap_up(st)
    assert "1 of the 2 figures" in line and "stopped once" in line
    assert pitch.delivery(st) == {"words": 7, "fillers": 3}
