"""Referee, gap ownership, offline minds and the FR-4 grep test."""

import re
from pathlib import Path

from vicky.areopagus import registry
from vicky.court import minds, referee
from vicky.court.referee import Bid
from vicky.model.context import sample_context

REPO = Path(__file__).resolve().parents[2]


def test_highest_bid_speaks():
    ranked = referee.rank([Bid("a", 0.4, "new_topic", "a.h1"), Bid("b", 0.9, "new_topic", "b.h1")], answer_weak=False)
    assert ranked[0].vc_id == "b"


def test_follow_up_stops_at_depth_cap():
    owner = Bid("a", 0.6, "follow_up", "a.h1", is_current=True, depth=3, max_depth=3, turns_since_spoke=0)
    ranked = referee.rank([owner, Bid("b", 0.3, "new_topic", "b.h1")], answer_weak=True)
    assert all(c.intent != "follow_up" for c in ranked)


def test_weak_answer_gets_a_follow_up_bonus():
    owner = Bid("a", 0.5, "follow_up", "a.h1", is_current=True, depth=1, max_depth=3, turns_since_spoke=0)
    ranked = referee.rank([owner, Bid("b", 0.6, "new_topic", "b.h1", turns_since_spoke=3)], answer_weak=True)
    assert ranked[0].vc_id == "a" and ranked[0].intent == "follow_up"


def test_jump_in_needs_a_margin():
    ranked = referee.rank([Bid("a", 0.62, "jump_in", "a.h1", turns_since_spoke=5),
                           Bid("b", 0.6, "new_topic", "b.h1", turns_since_spoke=5)], answer_weak=False)
    assert ranked[0].vc_id == "b"


def test_chair_decision_outside_the_candidates_is_invalid():
    ranked = referee.rank([Bid("a", 0.5, "new_topic", "a.h1")], answer_weak=False)
    assert referee.validate({"action": "call_on", "vc_id": "zz"}, ranked)[0] is False
    assert referee.validate({"action": "call_on", "vc_id": "a", "intent": "follow_up"}, ranked)[0] is False
    assert referee.validate({"action": "call_on", "vc_id": "a", "intent": "new_topic"}, ranked)[0] is True


def test_five_seated_vcs_open_on_different_lenses():
    """FR-8 (offline): gap ownership splits the attack list so first questions don't overlap."""
    ctx = sample_context("tidewell")
    panel = [registry.builtins()[i] for i in ("aristotle", "thales", "xenophon", "plato", "socrates")]
    memos = minds.build_memos(panel, ctx)
    firsts = [memos[p.id]["hypotheses"][0] for p in panel]
    assert len({h["attack_id"] for h in firsts}) == 5
    assert len({h["lens"] for h in firsts}) >= 4


def test_questions_pass_the_audit_and_have_no_placeholders():
    ctx = sample_context("tidewell")
    for p in registry.builtins().values():
        memo = minds.build_memos([p], ctx)[p.id]
        q = memo["opening_question"]
        assert "{" not in q, (p.id, q)
        assert minds.passes(q, ctx, memo["hypotheses"][0].get("quotes")), (p.id, q)


def test_no_concession_without_a_matching_figure():
    ctx = sample_context("tidewell")
    p = registry.builtins()["aristotle"]
    state = {"hyps": [minds._hyp(next(a for a in ctx.attack if "cmgr_12m" in a.figure_ids), p, 1)]}
    h = state["hyps"][0]
    before = h["confidence"]
    minds.update_and_bid(p, state, [], weak=True, current_vc="aristotle", current_hyp=h["id"], turns_since=0)
    assert h["confidence"] >= before  # evasive answer: doubt can't drop
    match = [{"status": "matches", "figure_id": "cmgr_12m"}]
    minds.update_and_bid(p, state, match, weak=False, current_vc="aristotle", current_hyp=h["id"], turns_since=0)
    assert h["confidence"] < before


def test_fr4_no_sample_company_names_in_code():
    names = re.compile(r"tidewell|northern comfort", re.I)
    roots = [REPO / "backend" / "vicky", REPO / "frontend" / "app", REPO / "frontend" / "components", REPO / "frontend" / "lib"]
    hits = []
    for root in roots:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in (".py", ".ts", ".tsx", ".yaml", ".md", ".css") and names.search(
                    path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(path.relative_to(REPO)))
    assert not hits, hits
