"""The LLM path on recorded responses: client, minds, mapper and FR-7 extraction. No live calls."""

import asyncio
import io
import json

import pytest
from fastapi import HTTPException

from tests.llm_fakes import (
    FILE_META,
    char_cite,
    json_reply,
    make_pdf,
    message,
    page_cite,
    queue,
    text_block,
    text_reply,
    tool_use_reply,
)
from vicky import auth, llm
from vicky.areopagus import registry
from vicky.audit import audit_text
from vicky.config import get_settings
from vicky.court import minds as offline
from vicky.court import referee
from vicky.llm import docs, mapper
from vicky.llm import minds as agents
from vicky.llm.client import (
    FALLBACK_BETA,
    BudgetExceeded,
    LLMError,
    LLMRefusal,
    LLMUnavailable,
    get_llm,
    usage_usd,
)
from vicky.llm.schemas import ChairDecision, ClaimList, DocFact, DocFactList
from vicky.model.context import sample_context
from vicky.model.loader import parse_upload

INVENTED = "Your ARR is $9.9M, so why is growth stalling?"


@pytest.fixture(scope="module")
def ctx():
    return sample_context("tidewell")


@pytest.fixture
def james():
    return registry.builtins()["james"]


def by_task(**handlers):
    """Responder that dispatches on the agent prompt a call carries; each value is a list (queue) or a callable."""
    pending = {k: (list(v) if isinstance(v, list) else v) for k, v in handlers.items()}

    def respond(call):
        h = pending.get(call["task"])
        if h is None:
            raise AssertionError(f"unexpected {call['task']} call")
        if isinstance(h, list):
            if not h:
                raise AssertionError(f"too many {call['task']} calls")
            return h.pop(0)
        return h(call)

    return respond


# ---------------------------------------------------------------- client

async def test_parse_sends_route_settings_and_records_spend(live_llm):
    rec = live_llm.install(queue(json_reply({"claims": []}, model="claude-haiku-5-5")))
    out = await get_llm().parse("claims", ClaimList, system="Task: list claims", messages=[{"role": "user", "content": "hi"}])
    assert out.claims == []
    body = rec.calls[0]["body"]
    assert body["model"] == "claude-haiku-5-5" and body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert "fallbacks" not in body  # no server-side fallback for Haiku
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert live_llm.spend == pytest.approx((1000 * 0.10 + 200 * 0.50) / 1e6)


async def test_sonnet_routes_opt_into_fallbacks_and_the_chair_skips_thinking(live_llm):
    decision = {"action": "call_on", "vc_id": "a", "intent": "new_topic", "hypothesis_id": "a.h1", "note": None}
    rec = live_llm.install(queue(json_reply(decision)))
    await get_llm().parse("chair", ChairDecision, system="chair", messages=[{"role": "user", "content": "x"}])
    call = rec.calls[0]
    assert call["body"]["fallbacks"] == "default" and FALLBACK_BETA in call["headers"].get("anthropic-beta", "")
    assert call["body"]["thinking"] == {"type": "between_tools"} and call["body"]["model"] == "claude-sonnet-5-5"


async def test_refusal_is_checked_before_content(live_llm):
    live_llm.install(queue(message([], stop_reason="refusal",
                                   stop_details={"type": "refusal", "category": "cyber", "explanation": "no"})))
    with pytest.raises(LLMRefusal) as e:
        await get_llm().parse("claims", ClaimList, system="s", messages=[{"role": "user", "content": "x"}])
    assert e.value.category == "cyber"
    assert live_llm.spend > 0  # the declined call is still accounted


async def test_truncated_output_and_server_errors_are_llm_errors(live_llm):
    live_llm.install(queue(message([text_block('{"claims": [')], stop_reason="max_tokens"),
                           (529, {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})))
    with pytest.raises(LLMError):
        await get_llm().parse("claims", ClaimList, system="s", messages=[{"role": "user", "content": "x"}])
    with pytest.raises(LLMUnavailable):
        await get_llm().parse("claims", ClaimList, system="s", messages=[{"role": "user", "content": "x"}])


async def test_budget_blocks_calls_and_routes(live_llm, monkeypatch):
    rec = live_llm.install(queue())
    live_llm.spend = get_settings().daily_usd_budget + 1
    with pytest.raises(BudgetExceeded):
        await get_llm().text("speak", system="s", messages=[{"role": "user", "content": "x"}])
    assert rec.calls == []
    with pytest.raises(HTTPException) as e:
        await auth.require_budget()
    assert e.value.status_code == 402
    monkeypatch.setenv("LLM_MODE", "offline")
    get_settings.cache_clear()
    await auth.require_budget()  # the offline path costs nothing and is never blocked


def test_enabled_needs_a_key_and_respects_offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MODE", "auto")
    get_settings.cache_clear()
    assert llm.enabled() is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    get_settings.cache_clear()
    assert llm.enabled() is True
    monkeypatch.setenv("LLM_MODE", "offline")
    get_settings.cache_clear()
    assert llm.enabled() is False
    monkeypatch.undo()
    get_settings.cache_clear()


def test_usage_is_priced_at_list_rates():
    from types import SimpleNamespace

    u = SimpleNamespace(input_tokens=1_000_000, output_tokens=1_000_000, cache_read_input_tokens=1_000_000,
                        cache_creation_input_tokens=0)
    assert usage_usd("claude-opus-5-5", u) == pytest.approx(4 + 20 + 0.2)
    assert usage_usd("claude-sonnet-5-5", u) == pytest.approx(2 + 10 + 0.2)
    assert usage_usd("some-new-model", u) > usage_usd("claude-opus-5-5", u)  # unknown → dearest


# ---------------------------------------------------------------- minds: offline passthrough

async def test_without_a_key_the_minds_are_the_offline_minds(ctx, james, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "offline")
    get_settings.cache_clear()
    try:
        assert await agents.build_memos([james], ctx) == offline.build_memos([james], ctx)
        hyp = offline.build_memos([james], ctx)["james"]["hypotheses"][0]
        spoken = await agents.speak(james, hyp, ctx, "new_topic", set())
        assert spoken.text == offline.question_for(james, hyp, ctx, set()) and spoken.source == "offline"
        answer = "Our ARR is $1.29M and churn is about 1%."
        assert await agents.extract_claims(answer) == offline_claims(answer)
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def offline_claims(answer):
    from vicky.model.truth import quick_claims

    return quick_claims(answer)


# ---------------------------------------------------------------- memos

async def test_memo_uses_kit_tools_and_code_keeps_only_anchored_hypotheses(live_llm, ctx, james):
    base = offline.build_memos([james], ctx)["james"]
    owned = base["hypotheses"][0]
    real_fig = next(f.id for f in ctx.available() if f.id not in owned["evidence"])
    memo = {"thesis": "Growth is slowing and the plan assumes it won't.",
            "hypotheses": [
                {"attack_id": owned["attack_id"], "claim": "Growth is decelerating", "lens": owned["lens"],
                 "evidence": owned["evidence"], "severity": 0.9, "confidence": 0.99},
                {"attack_id": None, "claim": "Hidden doubt with no data", "lens": "market", "evidence": ["not_a_figure"],
                 "severity": 0.9, "confidence": 0.9},
                {"attack_id": None, "claim": "The plan leans on one line", "lens": "forecast", "evidence": [real_fig],
                 "severity": 0.99, "confidence": 0.95}],
            "mind_changers": ["Cohort data by month"], "opening_question": INVENTED}
    rec = live_llm.install(by_task(memo=[tool_use_reply("get_metric", {"id": "arr"}, model="claude-opus-5-5"),
                                         json_reply(memo, model="claude-opus-5-5")]))
    out = (await agents.build_memos([james], ctx))["james"]
    assert out["source"] == "llm"
    assert [h["id"] for h in out["hypotheses"]] == ["james.h1", "james.h2"]
    first, new = out["hypotheses"]
    assert first["attack_id"] == owned["attack_id"] and first["confidence"] == 0.9  # clamped
    assert new["evidence"] == [real_fig] and new["severity"] == 0.7  # a model-only doubt can't outrank code's
    assert out["opening_question"] != INVENTED and audit_text(out["opening_question"], ctx.available(),
                                                              first.get("quotes")).passed
    # the kit tool ran in code and its Figure went back to the model
    second = rec.calls[1]["body"]["messages"]
    result = next(b for m in second if m["role"] == "user" and isinstance(m["content"], list)
                  for b in m["content"] if b.get("type") == "tool_result")
    assert json.loads(result["content"])["id"] == "arr"


async def test_memo_failure_falls_back_per_investor(live_llm, ctx, james):
    live_llm.install(by_task(memo=[(500, {"type": "error", "error": {"type": "api_error", "message": "x"}})]))
    assert (await agents.build_memos([james], ctx))["james"] == offline.build_memos([james], ctx)["james"]


# ---------------------------------------------------------------- speaking

async def test_a_line_that_fails_the_audit_is_regenerated_once(live_llm, ctx, james):
    hyp = offline.build_memos([james], ctx)["james"]["hypotheses"][0]
    good = "Walk me through which months that growth rate covers and how you calculate it."
    rec = live_llm.install(by_task(speak=[text_reply(INVENTED), text_reply(good)]))
    spoken = await agents.speak(james, hyp, ctx, "new_topic", set())
    assert (spoken.text, spoken.regenerated, spoken.source) == (good, True, "llm")
    retry = rec.calls[1]["body"]["messages"]
    assert retry[-1]["role"] == "user" and "failed the fact audit" in retry[-1]["content"]


async def test_two_failed_lines_fall_back_to_the_offline_line(live_llm, ctx, james):
    hyp = offline.build_memos([james], ctx)["james"]["hypotheses"][0]
    live_llm.install(by_task(speak=[text_reply(INVENTED), text_reply("We value you at $20M pre-money.")]))
    spoken = await agents.speak(james, hyp, ctx, "new_topic", set())
    assert spoken.source == "offline" and spoken.regenerated is True
    assert spoken.text == offline.question_for(james, hyp, ctx, set())


# ---------------------------------------------------------------- chair

def _ranked():
    return referee.rank([referee.Bid("james", 0.8, "new_topic", "james.h1", turns_since_spoke=5),
                         referee.Bid("alex", 0.6, "new_topic", "alex.h1", turns_since_spoke=5)], answer_weak=False)


def _state():
    return {"vcs": {v: {"hyps": [{"id": f"{v}.h1", "claim": "doubt", "lens": "forecast", "confidence": 0.7, "asked": 0,
                                  "status": "open"}]} for v in ("james", "alex")}}


async def test_chair_can_pick_any_ranked_candidate(live_llm):
    panel = {p: registry.builtins()[p] for p in ("james", "alex")}
    live_llm.install(by_task(chair=[json_reply({"action": "call_on", "vc_id": "alex", "intent": "new_topic",
                                                "hypothesis_id": "alex.h9", "note": "fresh lens"}),
                                    json_reply({"action": "call_on", "vc_id": "alex", "intent": "follow_up",
                                                "hypothesis_id": "alex.h1", "note": None})]))
    pick = await agents.chair(_ranked(), _state(), panel)
    assert pick.candidate.vc_id == "alex" and not pick.fallback and pick.valid
    assert pick.decision["hypothesis_id"] == "alex.h1"  # an unknown hypothesis becomes the candidate's own
    pick = await agents.chair(_ranked(), _state(), panel)
    assert pick.fallback and pick.candidate.vc_id == "james"  # a follow-up the referee didn't allow is invalid


async def test_invalid_or_late_chair_falls_back_to_the_top_candidate(live_llm, monkeypatch):
    panel = {p: registry.builtins()[p] for p in ("james", "alex")}
    live_llm.install(by_task(chair=[json_reply({"action": "call_on", "vc_id": "zed", "intent": "new_topic",
                                                "hypothesis_id": None, "note": None})]))
    pick = await agents.chair(_ranked(), _state(), panel)
    assert pick.fallback and pick.candidate.vc_id == "james" and "not an eligible" in pick.reason

    async def slow(_call):
        await asyncio.sleep(0.5)
        return json_reply({"action": "call_on", "vc_id": "alex", "intent": "new_topic", "hypothesis_id": "alex.h1",
                           "note": None})

    monkeypatch.setenv("CHAIR_TIMEOUT_S", "0.05")
    get_settings.cache_clear()
    live_llm.install(slow)
    pick = await agents.chair(_ranked(), _state(), panel)
    assert pick.fallback and pick.candidate.vc_id == "james"


# ---------------------------------------------------------------- beliefs

def _vc_state():
    return {"hyps": [{"id": "james.h1", "attack_id": "growth_decel", "claim": "Growth is slowing", "lens": "forecast",
                      "evidence": ["cmgr_12m"], "confidence": 0.7, "severity": 0.8, "status": "open", "asked": 1,
                      "weak_answers": 0, "quotes": []}], "last_spoke": 0}


async def test_no_concession_without_a_matching_figure_holds_on_the_llm_path(live_llm, ctx, james):
    drop = {"deltas": [{"hyp_id": "james.h1", "new_confidence": 0.1, "why": "They sounded confident"}], "bid": 0.4,
            "intent": "follow_up", "target_hyp": "james.h1"}
    live_llm.install(by_task(bid=[json_reply(drop), json_reply(drop)]))
    state = _vc_state()
    out = await agents.update_and_bid(james, state, [], False, "alex", "alex.h1", 2, set(), ctx=ctx, answer="Trust me.")
    assert state["hyps"][0]["confidence"] == 0.7 and out["deltas"] == []
    assert out["intent"] != "follow_up"  # not this investor's thread
    match = [{"status": "matches", "figure_id": "cmgr_12m", "text": "growth"}]
    out = await agents.update_and_bid(james, state, match, False, "james", "james.h1", 0, set(), ctx=ctx)
    assert state["hyps"][0]["confidence"] == pytest.approx(0.35)  # accepted, but at most MAX_DELTA per answer
    assert out["deltas"][0]["hyp_id"] == "james.h1"


# ---------------------------------------------------------------- judge and claims

async def test_judge_scores_are_clamped_and_rewrites_audited(live_llm, ctx, james):
    hyp = offline.build_memos([james], ctx)["james"]["hypotheses"][0]
    answer = "We grew fast last year and we're fixing the pipeline."
    js = {"evidence": 7, "clarity": 3.04, "composure": -1, "investor_fit": 4, "good": "Owned the slowdown.",
          "missing": "The growth figure and its window.", "strong_answer": "Our ARR is $9.9M and growing 40% a month."}
    live_llm.install(by_task(judge=[json_reply(js, model="claude-opus-5-5")]))
    base = offline.judge(answer, hyp, [], ctx, "q")
    out = await agents.judge(answer, hyp, [], ctx, "q")
    assert out["dims"] == {"evidence": 5.0, "clarity": 3.0, "composure": 0.0, "investor_fit": 4.0}
    assert out["rationale"]["good"] == "Owned the slowdown."
    assert out["rationale"]["strong_answer"] == base["rationale"]["strong_answer"]  # invented numbers rejected
    assert out["accuracy"] == base["accuracy"] and out["rationale"]["correct_figure"] == base["rationale"]["correct_figure"]


async def test_claims_must_quote_the_founder_with_the_number(live_llm):
    answer = "Honestly our ARR is $1.29M. We sign about 14 new logos a month."
    claims = {"claims": [
        {"text": "our ARR is $1.29M", "metric": "arr", "value": 1290000, "unit": "money", "period": None, "is_forecast": False},
        {"text": "NRR is 130%", "metric": "nrr", "value": 130, "unit": "pct", "period": None, "is_forecast": False},
        {"text": "We sign about 14 new logos", "metric": "new customers", "value": 40, "unit": "count", "period": None,
         "is_forecast": False},
        {"text": "We sign about 14 new logos a month", "metric": "new customers", "value": 14, "unit": "count",
         "period": "month", "is_forecast": False}]}
    live_llm.install(by_task(claims=[json_reply(claims, model="claude-haiku-5-5")]))
    out = await agents.extract_claims(answer)
    assert out[: len(offline_claims(answer))] == offline_claims(answer)  # code's own extraction comes first
    assert [c["metric"] for c in out].count("arr") == 1  # no duplicate of what code found
    assert "nrr" not in [c["metric"] for c in out]  # not in the answer
    added = [c for c in out if c["metric"] == "new customers"]
    assert [c["value"] for c in added] == [14]  # the 40 isn't in its quote


# ---------------------------------------------------------------- column mapper

CSV = (b"Month,Total Revenue,Subscription revenue,Hosting,Mystery Col\n"
       b"2025-01,100,90,10,5\n2025-02,110,99,11,6\n2025-03,120,108,12,7\n")


async def test_mapper_merges_claude_with_the_heuristic(live_llm):
    ds = parse_upload(CSV, "numbers.csv")[0]
    proposal = {"columns": [
        {"source_column": "Mystery Col", "canonical_field": "opex.g_and_a", "unit": "usd", "confidence": 0.8,
         "note": "office costs"},
        {"source_column": "Subscription revenue", "canonical_field": "revenue.total", "unit": "", "confidence": 0.9,
         "note": "x"},
        {"source_column": "Hosting", "canonical_field": "made.up", "unit": "", "confidence": 0.99, "note": "x"},
        {"source_column": "Not a column", "canonical_field": "cogs", "unit": "", "confidence": 0.99, "note": "x"}]}
    rec = live_llm.install(by_task(mapper=[json_reply(proposal)]))
    out, proposer = await mapper.propose(ds, "cad")
    by = {m.source_column: m for m in out}
    assert proposer == "claude" and rec.calls[0]["body"]["model"] == "claude-sonnet-5-5"
    assert by["Mystery Col"].canonical_field == "opex.g_and_a" and by["Mystery Col"].unit == "cad"  # unit set by code
    assert by["Subscription revenue"].canonical_field != "revenue.total"  # the total column keeps its field
    assert by["Hosting"].canonical_field != "made.up" and by["Total Revenue"].canonical_field == "revenue.total"


async def test_mapper_without_a_key_is_the_heuristic():
    from vicky.model.mapping import propose_heuristic

    ds = parse_upload(CSV, "numbers.csv")[0]
    out, proposer = await mapper.propose(ds, "cad")
    assert proposer == "heuristic" and out == propose_heuristic(ds, "cad")


# ---------------------------------------------------------------- FR-7 document facts

PAGE2 = ["ARR reached $1.2M in December 2025.", "Monthly burn was $85,000.", "We plan 40% growth in 2026."]


def _doc_responder(pass1: dict, facts: list[dict]):
    def respond(call):
        if call["path"].endswith("/v1/files") and call["method"] == "POST":
            return FILE_META
        if call["method"] == "DELETE":
            return {"id": FILE_META["id"], "type": "file_deleted"}
        if call["task"] == "doc_facts":
            return pass1
        if call["task"] == "doc_parse":
            return json_reply({"facts": facts}, model="claude-opus-5-5")
        raise AssertionError(call["task"])

    return respond


def _fact(name, value, unit, cited, kind="historical", page=None, currency=None, period=None):
    return {"name": name, "label": name.replace("_", " "), "value": value, "unit": unit, "currency": currency,
            "period": period, "kind": kind, "page": page, "cited_text": cited}


async def test_pdf_facts_are_cited_verified_on_the_page_and_pending(live_llm):
    pdf = make_pdf([["Board update"], PAGE2])
    pass1 = message([text_block("ARR: $1.2M, December 2025", [page_cite(PAGE2[0], 2)]),
                     text_block("\nBurn: $85,000 a month", [page_cite(PAGE2[1], 1)]),  # cites the wrong page
                     text_block("\nPlan: 40% growth in 2026", [page_cite(PAGE2[2], 2)]),
                     text_block("\nCustomers: 75", [page_cite(PAGE2[0], 2)]),
                     text_block("\nNo citation here: 12 things")], model="claude-opus-5-5")
    facts = [_fact("arr", 1200000, "money", PAGE2[0], page=2, currency="CAD", period="2025-12"),
             _fact("burn", 85000, "money", PAGE2[1], page=2),  # the model's page is ignored; the citation says 1
             _fact("growth", 40, "pct", PAGE2[2], kind="forecast", period="2026"),
             _fact("customers", 75, "count", PAGE2[0])]  # 75 isn't in the cited text: model-supplied, dropped
    rec = live_llm.install(_doc_responder(pass1, facts))
    out = await docs.extract_facts(pdf, "board.pdf", "pdf", upload_id="u1", currency="cad")
    got = {f.name: f for f in out["facts"]}
    assert set(got) == {"arr", "burn", "plan.growth"} and out["dropped"] == 1 and out["lines"] == 4
    arr = got["arr"]
    assert arr.status == "pending" and arr.unit == "cad" and arr.value == 1200000
    assert arr.source.kind == "pdf" and arr.source.page == 2 and arr.source.verified is True
    assert arr.source.ref == "board.pdf, p. 2" and arr.source.cited_text == PAGE2[0]
    assert got["burn"].source.verified is False and "page 1" in got["burn"].note
    assert got["plan.growth"].value == pytest.approx(0.4) and got["plan.growth"].kind == "forecast"
    paths = [(c["method"], c["path"]) for c in rec.calls]
    assert paths[0] == ("POST", "/v1/files") and paths[2] == ("DELETE", f"/v1/files/{FILE_META['id']}")  # after pass 1
    doc = rec.calls[1]["body"]["messages"][0]["content"][0]
    assert rec.calls[1]["task"] == "doc_facts" and rec.calls[3]["task"] == "doc_parse"
    assert doc["source"] == {"type": "file", "file_id": FILE_META["id"]} and doc["citations"] == {"enabled": True}
    assert "format" not in rec.calls[1]["body"]["output_config"]  # citations can't use structured outputs
    assert rec.calls[3]["body"]["output_config"]["format"]["type"] == "json_schema"


async def test_docx_facts_use_char_citations(live_llm):
    import docx

    d = docx.Document()
    d.add_paragraph("Quarterly letter")
    d.add_paragraph("Cash in the bank was $483,000 at the end of September 2026.")
    buf = io.BytesIO()
    d.save(buf)
    data = buf.getvalue()
    text = docs.document_text(data, "docx")
    cited = "Cash in the bank was $483,000 at the end of September 2026."
    pass1 = message([text_block("Cash: $483,000 (Sep 2026)", [char_cite(cited, text.index(cited))])])
    rec = live_llm.install(_doc_responder(pass1, [_fact("cash_balance", 483000, "money", cited, period="2026-09")]))
    out = await docs.extract_facts(data, "letter.docx", "docx", upload_id="u2", currency="usd")
    (f,) = out["facts"]
    assert f.unit == "usd" and f.source.kind == "docx" and f.source.verified is True and f.source.page is None
    assert rec.calls[0]["body"]["messages"][0]["content"][0]["source"]["type"] == "text"  # no Files API for text


def test_cited_lines_and_merge_pending():
    msg = type("M", (), {"content": [type("B", (), {"type": "text", "text": "a 1\nb 2", "citations": None})()]})()
    assert docs.cited_lines(msg) == []  # lines without citations are not facts
    f = docs.to_fact(DocFact(**_fact("arr", 1, "money", "ARR 1")), docs.CitedSpan("ARR 1", 1, 2), True, "",
                     upload_id="u", filename="x.pdf", kind="pdf", currency="usd")
    merged, added = docs.merge_pending([], [f])
    again, added2 = docs.merge_pending(merged, [f])
    assert added == 1 and added2 == 0 and again == merged
    assert DocFactList(facts=[]).facts == []
