"""The LLM path end to end over the REST API, on recorded responses (no network, no real key):
the Prepare court with Claude minds, FR-7 extraction from an uploaded PDF, and the 402 budget guard.
"""

import re

import pytest

from tests.helpers import load_and_confirm
from tests.llm_fakes import FILE_META, json_reply, make_pdf, message, page_cite, text_block, text_reply
from vicky import db, jobs

pytestmark = pytest.mark.db

SPOKEN = "Walk me through how you calculate that, month by month, and what changed last quarter."
JUDGED = {"evidence": 2.5, "clarity": 3.5, "composure": 4.0, "investor_fit": 3.0, "good": "Stayed calm.",
          "missing": "The figure itself and its window.", "strong_answer": "Name the figure, its window and the plan."}


def scripted(call):
    """One recorded answer per agent prompt, built from what the prompt offers (ids, candidates)."""
    task = call["task"]
    user = next((m["content"] for m in reversed(call["body"]["messages"]) if m["role"] == "user"), "") \
        if call["body"] else ""
    user = user if isinstance(user, str) else ""
    if task == "memo":
        aid = re.search(r"Doubts assigned to you:\n- (\S+) \| (\S+) \|", user)
        ev = re.search(r"evidence ([a-z0-9_.]+)", user)
        return json_reply({"thesis": "Reads the business through its own numbers.",
                           "hypotheses": [{"attack_id": aid.group(1), "claim": "The weak spot holds", "lens": aid.group(2),
                                           "evidence": [ev.group(1)] if ev else [], "severity": 0.8, "confidence": 0.7}],
                           "mind_changers": ["A cited answer"], "opening_question": SPOKEN}, model="claude-opus-5-5")
    if task == "speak":
        return text_reply(SPOKEN)
    if task == "chair":
        top = re.search(r"1\. (\S+) \(.*?\) \| (\S+) \| (\S+) \|", user)
        return json_reply({"action": "call_on", "vc_id": top.group(1), "intent": top.group(2),
                           "hypothesis_id": top.group(3), "note": "top of the list"})
    if task == "claims":
        return json_reply({"claims": []}, model="claude-haiku-5-5")
    if task == "judge":
        return json_reply(JUDGED, model="claude-opus-5-5")
    if task == "bid":
        hid = re.search(r"\n(\S+\.h\d+) \|", user)
        return json_reply({"deltas": [], "bid": 0.5, "intent": "new_topic", "target_hyp": hid.group(1) if hid else None})
    raise AssertionError(f"unexpected {task} call")


async def _login_and_confirm(api_client):
    await api_client.post("/auth/access", json={"code": "vicky-demo"})
    if (await api_client.get("/engagements/active")).status_code != 200:
        await load_and_confirm(api_client, "tidewell")


async def test_prepare_court_runs_on_the_llm_path(api_client, live_llm):
    await _login_and_confirm(api_client)
    rec = live_llm.install(scripted)
    r = await api_client.post("/court/start", json={"panel": ["james", "alex"], "question_cap": 4})
    assert r.status_code == 200, r.text
    s = r.json()
    assert [t["kind"] for t in s["turns"]] == ["intro", "question"] and s["turns"][1]["text"] == SPOKEN
    assert {"memo", "chair", "speak"} <= set(rec.tasks())
    memos = await db.fetch("select memo from memos where session_id::text = $1", s["id"])
    assert len(memos) == 2 and all(m["memo"].get("source") == "llm" for m in memos)

    r = await api_client.post(f"/court/{s['id']}/answer", json={"text": "We grew a lot and we're hiring for it."})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["scores"][0]["dims"] == {k: JUDGED[k] for k in ("evidence", "clarity", "composure", "investor_fit")}
    assert s["turns"][-1]["kind"] in ("question", "coach") and s["question_count"] == 2
    assert {"claims", "judge", "bid"} <= set(rec.tasks())
    decisions = await db.fetch("select valid, fallback, decision from chair_decisions where session_id::text = $1 "
                               "order by after_turn_seq", s["id"])
    assert decisions and all(d["valid"] and not d["fallback"] for d in decisions)
    assert decisions[0]["decision"]["note"] == "top of the list"
    assert live_llm.spend > 0


async def test_uploaded_pdf_becomes_pending_cited_facts(api_client, live_llm):
    lines = ["Cash at the end of September was $483,270.", "We had 41 paying customers."]
    pdf = make_pdf([["Monthly investor update"], lines])

    def respond(call):
        if call["method"] == "POST" and call["path"].endswith("/v1/files"):
            return FILE_META
        if call["method"] == "DELETE":
            return {"id": FILE_META["id"], "type": "file_deleted"}
        if call["task"] == "doc_facts":
            return message([text_block("Cash: $483,270 (Sep)", [page_cite(lines[0], 2)]),
                            text_block("\nCustomers: 41", [page_cite(lines[1], 1)])], model="claude-opus-5-5")
        if call["task"] == "doc_parse":
            return json_reply({"facts": [
                {"name": "cash_balance", "label": "Cash in the bank", "value": 483270, "unit": "money", "currency": None,
                 "period": "2026-09", "kind": "historical", "page": 2, "cited_text": lines[0]},
                {"name": "customers", "label": "Paying customers", "value": 41, "unit": "count", "currency": None,
                 "period": "2026-09", "kind": "historical", "page": 1, "cited_text": lines[1]}]}, model="claude-opus-5-5")
        raise AssertionError(call["task"])

    live_llm.install(respond)
    await api_client.post("/auth/access", json={"code": "vicky-demo"})
    r = await api_client.post("/uploads", files={"file": ("update.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    eng = r.json()
    (job,) = eng["extract_jobs"]
    await jobs.wait_for([job["id"]], timeout_s=20)
    eng = (await api_client.get(f"/engagements/{eng['id']}")).json()
    assert eng["uploads"][0]["status"] == "extracted" and eng["extract_jobs"][0]["status"] == "done"
    facts = {f["name"]: f for f in eng["facts"]}
    assert set(facts) == {"cash_balance", "customers"} and all(f["status"] == "pending" for f in facts.values())
    assert facts["cash_balance"]["source"] | {"verified": True} == facts["cash_balance"]["source"]
    assert facts["cash_balance"]["source"]["page"] == 2 and facts["cash_balance"]["unit"] == "usd"
    assert facts["customers"]["source"]["verified"] is False and facts["customers"]["note"].startswith("Check this")


async def test_offline_upload_of_a_pdf_runs_no_extraction(api_client):
    await api_client.post("/auth/access", json={"code": "vicky-demo"})
    r = await api_client.post("/uploads", files={"file": ("update.pdf", make_pdf([["Hello"]]), "application/pdf")})
    eng = r.json()
    assert r.status_code == 200 and eng["extract_jobs"] == [] and eng["uploads"][0]["status"] == "stored"


async def test_llm_routes_return_402_over_budget(api_client, live_llm):
    await _login_and_confirm(api_client)
    live_llm.install(scripted)
    live_llm.spend = 1e6
    r = await api_client.post("/court/start", json={})
    assert r.status_code == 402 and "budget" in r.json()["detail"].lower()
    assert (await api_client.get("/dashboards/active")).status_code == 200  # the rest of the product still works
