"""Vik chairs the court: knowledge checks from the founder's notes, her review of every line, her scoring.

Pure tests first (verdicts, scheduling, review, referee), then one offline court over a real index build.
"""

import pytest

from tests.helpers import start_court
from tests.test_rag import _build, vault  # noqa: F401  (fixture)
from vik import db
from vik.areopagus import registry
from vik.court import knowledge, minds, referee
from vik.court import review as code_review
from vik.llm import minds as agents
from vik.llm.schemas import ProbeDraft, ProbeList
from vik.model.context import sample_context

PILOT = "The board approved the pilot with 40 stores and a minimum commitment from the partner."
PASSAGE = {
    "id": "c1",
    "note_id": "n1",
    "path": "company/Board",
    "title": "Board notes",
    "heading": "Partnerships",
    "text": f"## Partnerships\n\n{PILOT} Renewal terms come next quarter.",
    "cite": "[kb:company/Board]",
}


def _probe() -> dict:
    pr = knowledge.probe_from(PASSAGE, "plato", "governance", 1)
    assert pr is not None
    return pr


def test_a_probe_keys_on_a_verbatim_span_and_asks_without_numbers():
    pr = _probe()
    assert pr["expected"]["quote"] == PILOT and knowledge.verbatim_in(
        pr["expected"]["quote"], PASSAGE["text"]
    )
    assert "Partnerships" in pr["question"] and not any(ch.isdigit() for ch in pr["question"])


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [
        ("The board approved the pilot with the partner's stores and a minimum commitment.", "knows"),
        ("The board approved a pilot.", "partial"),
        ("The board approved a pilot with 25 stores.", "contradicts"),
        ("Honestly, I don't know.", "missed"),
    ],
)
def test_vik_verifies_a_knowledge_answer_against_the_note(answer, verdict):
    v = knowledge.verify(answer, _probe(), [PASSAGE])
    assert v["verdict"] == verdict, v
    assert f'"{PILOT}" [kb:company/Board]' in v["explanation"]  # the note, word for word, with its cite


def test_the_verdict_explanation_passes_the_audit_only_with_the_note():
    ctx = sample_context("tidewell")
    v = knowledge.verify("No idea.", _probe(), [PASSAGE])
    notes = {"company/Board": {"id": "n1", "title": "Board notes", "content": PASSAGE["text"]}}
    assert minds.audit_text(v["explanation"], ctx.available(), notes=notes).passed
    assert not minds.audit_text(v["explanation"], ctx.available(), notes={}).passed  # 40 is not a figure


def test_knowledge_scoring_follows_the_verdict():
    ctx = sample_context("tidewell")
    base = minds.judge("I don't know.", None, [], ctx, "q")
    missed = knowledge.adjust_score(
        base, {**knowledge.verify("I don't know.", _probe(), []), "expected": _probe()["expected"]}
    )
    assert missed["dims"]["evidence"] == 1.0 and missed["rationale"]["strong_answer"] == f'"{PILOT}"'


def _state(asked: int = 0, last: int | None = None) -> dict:
    probes = [{**_probe(), "id": f"k:plato.{i}", "asked": i < asked} for i in range(3)]
    s = {
        "vcs": {"plato": {"hyps": [], "last_spoke": 0}, "socrates": {"hyps": [], "last_spoke": 1}},
        "probes": probes,
    }
    if last is not None:
        s["last_knowledge_q"] = last
    return s


def test_vik_schedules_knowledge_checks_and_spaces_them():
    ranked = [referee.Candidate("socrates", "new_topic", "socrates.h1", 0.6)]
    assert knowledge.candidate(_state(), ranked, question_count=1, cap=8, weak=False) is None  # too early
    c = knowledge.candidate(_state(), ranked, question_count=2, cap=8, weak=False)
    assert c and c.intent == "knowledge" and c.vc_id == "plato" and c.score > ranked[0].score
    assert (
        knowledge.candidate(_state(), ranked, question_count=2, cap=8, weak=True) is None
    )  # follow-up first
    assert (
        knowledge.candidate(_state(1, last=2), ranked, question_count=4, cap=8, weak=False) is None
    )  # spacing
    assert knowledge.candidate(_state(1, last=2), ranked, question_count=5, cap=8, weak=False)
    assert (
        knowledge.candidate(_state(2, last=5), ranked, question_count=8, cap=8, weak=False) is None
    )  # cap // 3


def test_the_referee_only_allows_a_knowledge_pick_on_offer():
    ranked = [
        referee.Candidate("plato", "knowledge", "k:plato.1", 0.7),
        referee.Candidate("plato", "new_topic", "plato.h1", 0.5),
    ]
    assert referee.validate({"action": "call_on", "vc_id": "plato", "intent": "knowledge"}, ranked)[0]
    assert referee.pick({"vc_id": "plato", "intent": "new_topic"}, ranked).intent == "new_topic"
    ok, why = referee.validate({"action": "call_on", "vc_id": "plato", "intent": "knowledge"}, ranked[1:])
    assert not ok and "knowledge" in why


def test_vik_sends_back_repeats_giveaways_and_non_questions():
    asked = ["How do you calculate ARR, month by month?"]
    assert code_review.review("How do you calculate ARR, month by month?", asked=asked, intent="new_topic")[
        "issues"
    ]
    assert code_review.review("Tell me about churn.", asked=[], intent="new_topic")["verdict"] == "revise"
    give = code_review.review(
        f"Is it true that {PILOT.lower()}?", asked=[], intent="knowledge", answer_key=PILOT
    )
    assert "it gives the answer away" in give["issues"]
    assert (
        code_review.review(_probe()["question"], asked=[], intent="knowledge", answer_key=PILOT)["verdict"]
        == "approve"
    )


def test_drafted_probes_survive_only_with_a_verbatim_answer():
    ctx = sample_context("tidewell")
    panel = [registry.builtins()["plato"]]
    passages = {"plato": [("governance", PASSAGE)]}
    pl = ProbeList(
        probes=[
            ProbeDraft(
                vc_id="plato",
                passage_id="c1",
                question="What did the board approve?",
                answer_quote="the board said yes",
            ),
            ProbeDraft(
                vc_id="nobody", passage_id="c1", question="What did the board approve?", answer_quote=PILOT
            ),
            ProbeDraft(
                vc_id="plato",
                passage_id="c1",
                question="What did the board approve on partnerships?",
                answer_quote=PILOT,
            ),
        ]
    )
    out = agents.probes_from_llm(pl, panel, passages, ctx)
    assert [p["question"] for p in out] == ["What did the board approve on partnerships?"]
    assert out[0]["expected"]["quote"] == PILOT and out[0]["source"] == "llm"


def test_the_five_philosophers_are_the_roster():
    b = registry.builtins()
    assert sorted(b) == ["aristotle", "plato", "socrates", "thales", "xenophon"]
    assert {p.firm for p in b.values()} == {
        "Lead Seed Fund",
        "Angel Operator",
        "Strategic Investor",
        "Government-Backed Fund",
        "Skeptical Partner",
    }
    assert registry.DEFAULT_PANEL == ["aristotle", "thales", "xenophon", "plato", "socrates"]


# ---------------------------------------------------------------- a court over a real index


@pytest.mark.db
async def test_a_court_asks_a_knowledge_question_and_vik_verifies_it(vault, api_client, monkeypatch):  # noqa: F811
    from tests.test_llm_api import _login_and_confirm
    from vik.config import get_settings

    monkeypatch.setattr(get_settings(), "rag_conf_min", 0.0)  # plumbing, not calibration
    await _build()
    await _login_and_confirm(api_client)
    r = await start_court(question_cap=8)
    assert r.status_code == 200, r.text
    s = r.json()
    sid = s["id"]
    assert [p["id"] for p in s["panel"]] == registry.DEFAULT_PANEL
    assert s["knowledge_ready"]["probes"] > 0, "no knowledge question was written from the notes"

    knowledge_q = None
    for _ in range(6):
        last = s["turns"][-1]
        if last["kind"] == "question" and last["intent"] == "knowledge":
            knowledge_q = last
            break
        s = (
            await api_client.post(
                f"/court/{sid}/answer",
                json={"text": "Fair question; the weak spot is real and we plan to fix it next quarter."},
            )
        ).json()
        assert s["status"] == "live", "the session ended before any knowledge check"
    assert knowledge_q is not None, [t["intent"] for t in s["turns"]]
    assert all(
        t["review"] and t["review"]["verdict"] in ("approve", "revise")
        for t in s["turns"]
        if t["kind"] == "question"
    )  # Vik reviewed every line

    state = await db.fetchval("select state from sessions where id::text = $1", sid)
    pr = knowledge.probe(state, knowledge_q["hypothesis_id"])
    assert pr is not None and pr["asked"] and not any(ch.isdigit() for ch in knowledge_q["text"])
    s = (await api_client.post(f"/court/{sid}/answer", json={"text": pr["expected"]["quote"]})).json()

    (check,) = s["knowledge"]
    assert check["verdict"] == "knows" and check["question_seq"] == knowledge_q["seq"]
    assert check["retrieval"]["build_id"] and check["expected"]["cite"] in check["explanation"]
    assert any(c.get("kind") == "note" for c in check["citations"])
    score = next(x for x in s["scores"] if x["turn_seq"] == check["turn_seq"])
    assert score["dims"]["evidence"] == 4.5

    s = (await api_client.post(f"/court/{sid}/end")).json()
    rep = (await api_client.get(f"/reports/{s['report_id']}")).json()
    assert rep["knowledge"] and rep["knowledge"][0]["verdict"] == "knows"


@pytest.mark.db
async def test_vik_sends_a_line_back_and_the_investor_rewrites_it(api_client, live_llm):
    from tests.llm_fakes import json_reply, text_reply
    from tests.test_llm_api import SPOKEN, _login_and_confirm, scripted

    rewrite = "Which months does that growth rate cover, and what changed in the last quarter?"
    reviews: list[str] = []

    def respond(call):
        user = (
            next((m["content"] for m in reversed(call["body"]["messages"]) if m["role"] == "user"), "")
            if call["body"]
            else ""
        )
        if call["task"] == "review":
            reviews.append(user)
            if len(reviews) == 1:
                return json_reply(
                    {
                        "verdict": "revise",
                        "issues": ["off the investor's lens"],
                        "note": "Ask about the window behind the growth rate.",
                    },
                    model="gemini-3.5-flash-lite",
                )
        if call["task"] == "speak" and "sent that line back" in str(user):
            return text_reply(rewrite)
        return scripted(call)

    live_llm.install(respond)
    await _login_and_confirm(api_client)
    r = await start_court(["aristotle", "thales"], 4)
    assert r.status_code == 200, r.text
    q = r.json()["turns"][-1]
    assert q["text"] == rewrite and q["text"] != SPOKEN
    assert q["review"]["verdict"] == "revise" and q["review"]["revised"] and q["review"]["final"] == "approve"
    assert "off the investor's lens" in q["review"]["issues"]
