"""End to end over the REST API (offline agents): FR-5, FR-10, FR-13 (fork), FR-14 and the Prepare loop.

Runs in definition order on one throwaway database; each test builds on the previous state.
"""

import re

import pytest

from vicky.samples import SAMPLES_DIR

pytestmark = pytest.mark.db


async def test_health_is_open(api_client):
    r = await api_client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"db": "ok", "kv": "ok"}


async def test_fr14_routes_need_the_access_cookie(api_client):
    for path in ("/samples", "/truth", "/dashboards/active", "/areopagus", "/reports", "/anything-else"):
        r = await api_client.get(path)
        assert r.status_code == 401, path
    assert (await api_client.post("/auth/access", json={"code": "wrong"})).status_code == 401
    assert (await api_client.post("/auth/access", json={"code": "é"})).status_code == 401  # non-ASCII must not 500
    r = await api_client.post("/auth/access", json={"code": "vicky-demo"})
    assert r.status_code == 200 and "vicky_access" in r.headers.get("set-cookie", "")
    assert (await api_client.get("/auth/session")).json() == {"ok": True}


async def test_fr10_gates_before_a_confirmed_truthpack(api_client):
    assert (await api_client.post("/pitch/start")).status_code == 409
    assert (await api_client.post("/court/start", json={})).status_code == 409
    assert (await api_client.get("/dashboards/active")).status_code == 404


async def test_upload_unfamiliar_layout_proposes_a_mapping(api_client):
    data = (SAMPLES_DIR / "harbor-labs" / "financials_quarterly.csv").read_bytes()
    r = await api_client.post("/uploads", files={"file": ("our_numbers.csv", data, "text/csv")})
    assert r.status_code == 200, r.text
    eng = r.json()
    assert eng["status"] == "draft" and eng["datasets"]
    ds = eng["datasets"][0]
    assert ds["granularity"] == "quarter" and ds["mapped"] >= 0.8 * ds["total"]
    m = (await api_client.get(f"/datasets/{ds['id']}/mapping")).json()
    assert m["confirmed"] is None and any(x["canonical_field"] == "revenue.recurring" for x in m["proposed"])
    bad = await api_client.put(f"/datasets/{ds['id']}/mapping",
                               json={"mapping": [{"source_column": "nope", "canonical_field": "cogs"}]})
    assert bad.status_code == 422
    assert (await api_client.post("/uploads", files={"file": ("deck.pptx", b"x", "application/octet-stream")})).status_code == 415


async def test_sample_load_confirm_and_figures(api_client):
    eng = (await api_client.post("/samples/tidewell/load")).json()
    assert eng["status"] == "draft" and eng["facts"] and all(f["status"] == "pending" for f in eng["facts"])
    r = await api_client.post(f"/engagements/{eng['id']}/confirm")
    assert r.status_code == 200 and r.json()["status"] == "active"
    truth = (await api_client.get("/truth")).json()
    figs = {f["id"]: f for f in truth["figures"]}
    assert abs(figs["arr"]["value"] - 1_286_268) < 1
    assert figs["arr"]["source"]["kind"] == "csv"
    assert truth["attack_list"][0]["severity"] >= truth["attack_list"][-1]["severity"]
    assert any(a["lens"] == "claims" and "deck" in a["detail"].lower() for a in truth["attack_list"])


async def test_fr5_claim_check(api_client):
    r = (await api_client.post("/claims/check", json={"metric": "churn", "value": 0.01, "unit": "pct"})).json()
    assert r["status"] == "contradicts" and r["figure_id"] == "logo_churn_rate"
    r = (await api_client.post("/claims/check", json={"metric": "arr", "value": 1_290_000, "unit": "money"})).json()
    assert r["status"] == "matches"


async def test_dashboard_widgets_are_evaluated_by_code(api_client):
    d = (await api_client.get("/dashboards/active")).json()
    roles = {w["role"]: w for w in d["widgets"]}
    assert {"margin_ring", "headline_kpi", "trend"} <= set(roles)
    assert all(w["status"] in ("ok", "missing") for w in d["widgets"])
    assert roles["trend"]["option"]["dataset"]
    spec = {"template": "bar", "title": "Burn ex credits % of revenue", "group_by": "quarter",
            "series": [{"ref": "pct_of(burn_ex_non_dilutive, revenue)"}]}
    p = await api_client.post(f"/dashboards/{d['id']}/widgets/preview", json={"spec": spec})
    assert p.status_code == 200 and p.json()["evaluated"]["status"] == "ok"
    evil = {**spec, "series": [{"ref": "mrr.__class__"}]}
    assert (await api_client.post(f"/dashboards/{d['id']}/widgets/preview", json={"spec": evil})).json()["evaluated"]["status"] == "error"
    stale = await api_client.post(f"/dashboards/{d['id']}/widgets", json={"spec": spec, "version": d["version"] - 1})
    assert stale.status_code == 409
    added = (await api_client.post(f"/dashboards/{d['id']}/widgets", json={"spec": spec, "version": d["version"]})).json()
    assert len(added["widgets"]) == len(d["widgets"]) + 1 and added["version"] > d["version"]


async def test_areopagus_builtins_and_fork(api_client):
    personas = (await api_client.get("/areopagus")).json()
    assert len([p for p in personas if p["builtin"]]) == 10
    assert (await api_client.put("/areopagus/mark", json={"name": "X"})).status_code == 403
    fork = (await api_client.post("/areopagus/mark/fork")).json()
    assert fork["builtin"] is False and fork["base_archetype"] == "skeptical_ic_partner"
    assert fork["signature_move"] == "Pre-mortem chain" and "pre-mortem" not in fork["id"]
    assert any(p["id"] == fork["id"] for p in (await api_client.get("/areopagus")).json())


async def test_prepare_court_round_trip(api_client):
    s = (await api_client.post("/court/start", json={"panel": ["james", "alex", "mark"], "question_cap": 5,
                                                         "coaching": "coached"})).json()
    assert s["status"] == "live" and s["awaiting"] == "founder"
    assert [t["kind"] for t in s["turns"]] == ["intro", "question"]
    first_q = s["turns"][-1]
    assert first_q["speaker"] in ("james", "alex", "mark") and first_q["citations"]

    s = (await api_client.post(f"/court/{s['id']}/answer", json={"text": "We're growing 10% a month."})).json()
    assert any(c["status"] == "contradicts" for c in s["claims"])
    follow = [t for t in s["turns"] if t["kind"] == "question"][-1]
    assert follow["speaker"] == first_q["speaker"] and follow["intent"] == "follow_up"  # weak answer → same VC digs in

    s = (await api_client.post(f"/court/{s['id']}/answer", json={"text": "It'll pick up, trust me."})).json()
    coach = [t for t in s["turns"] if t["kind"] == "coach"]
    assert coach and not re.search(r"\d", coach[-1]["text"])  # FR-9: the time-out adds no figure

    answers = ["ARR is $1.29M: September MRR of $107,189 times 12, so recurring only. You're right that growth slowed; "
               "we plan to hire next quarter.", "Runway is 8 months at $58.4K burn, so the round has to close by Q1.",
               "Our largest customer is about 10% of MRR; the risk is real and the plan doesn't count their expansion."]
    for a in answers:
        if s["status"] != "live":
            break
        s = (await api_client.post(f"/court/{s['id']}/answer", json={"text": a})).json()
    if s["status"] == "live":
        s = (await api_client.post(f"/court/{s['id']}/end")).json()
    assert s["status"] == "ended" and s["report_id"]
    questions = [t for t in s["turns"] if t["kind"] == "question"]
    assert len({t["text"] for t in questions}) == len(questions)  # nobody repeats a question

    rep = (await api_client.get(f"/reports/{s['report_id']}")).json()
    assert rep["verdict"]["questions"] >= 3 and 0 <= rep["verdict"]["overall"] <= 5
    assert rep["questions"][0]["strong_answer"] and rep["ledger"] and rep["sources"]
    assert "{" not in " ".join(q["strong_answer"] for q in rep["questions"])  # every placeholder filled
    md = await api_client.get(f"/reports/{s['report_id']}.md")
    assert md.status_code == 200 and md.text.startswith("# Practice report")
    assert (await api_client.post(f"/court/{s['id']}/answer", json={"text": "more"})).status_code == 409


async def test_fr10_pitch_after_confirm_is_not_a_gate_error(api_client):
    assert (await api_client.post("/pitch/start")).status_code == 501
