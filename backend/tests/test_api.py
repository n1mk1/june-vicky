"""End to end over the REST API (offline agents): FR-5, FR-10, FR-13 (fork), FR-14 and the court loop.

Runs in definition order on one throwaway database; each test builds on the previous state.
"""

import re

import pytest

from tests.helpers import load_sample_engagement, start_court
from vik.samples import SAMPLES_DIR

pytestmark = pytest.mark.db


async def test_health_is_open(api_client):
    r = await api_client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"db": "ok", "kv": "ok"}


async def test_fr14_routes_need_the_access_cookie(api_client):
    for path in ("/engagements", "/truth", "/dashboards/active", "/areopagus", "/reports", "/anything-else"):
        r = await api_client.get(path)
        assert r.status_code == 401, path
    assert (await api_client.post("/auth/access", json={"code": "wrong"})).status_code == 401
    assert (
        await api_client.post("/auth/access", json={"code": "é"})
    ).status_code == 401  # non-ASCII must not 500
    r = await api_client.post("/auth/access", json={"code": "vik-demo"})
    assert r.status_code == 200 and "vik_access" in r.headers.get("set-cookie", "")
    assert (await api_client.get("/auth/session")).json() == {"ok": True}


async def test_fr10_gates_before_a_confirmed_truthpack(api_client):
    assert (await api_client.post("/pitch/start")).status_code == 409
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
    bad = await api_client.put(
        f"/datasets/{ds['id']}/mapping",
        json={"mapping": [{"source_column": "nope", "canonical_field": "cogs"}]},
    )
    assert bad.status_code == 422
    assert (
        await api_client.post("/uploads", files={"file": ("deck.pptx", b"x", "application/octet-stream")})
    ).status_code == 415


async def test_sample_load_confirm_and_figures(api_client):
    assert (await api_client.get("/samples")).status_code == 404  # the app offers no samples
    eng = (await api_client.get(f"/engagements/{await load_sample_engagement('tidewell')}")).json()
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
    r = (
        await api_client.post("/claims/check", json={"metric": "churn", "value": 0.01, "unit": "pct"})
    ).json()
    assert r["status"] == "contradicts" and r["figure_id"] == "logo_churn_rate"
    r = (
        await api_client.post("/claims/check", json={"metric": "arr", "value": 1_290_000, "unit": "money"})
    ).json()
    assert r["status"] == "matches"


async def test_dashboard_widgets_are_evaluated_by_code(api_client):
    d = (await api_client.get("/dashboards/active")).json()
    roles = {w["role"]: w for w in d["widgets"]}
    assert {"margin_ring", "headline_kpi", "trend"} <= set(roles)
    assert all(w["status"] in ("ok", "missing") for w in d["widgets"])
    assert roles["trend"]["option"]["dataset"]
    spec = {
        "template": "bar",
        "title": "Burn ex credits % of revenue",
        "group_by": "quarter",
        "series": [{"ref": "pct_of(burn_ex_non_dilutive, revenue)"}],
    }
    p = await api_client.post(f"/dashboards/{d['id']}/widgets/preview", json={"spec": spec})
    assert p.status_code == 200 and p.json()["evaluated"]["status"] == "ok"
    evil = {**spec, "series": [{"ref": "mrr.__class__"}]}
    assert (await api_client.post(f"/dashboards/{d['id']}/widgets/preview", json={"spec": evil})).json()[
        "evaluated"
    ]["status"] == "error"
    stale = await api_client.post(
        f"/dashboards/{d['id']}/widgets", json={"spec": spec, "version": d["version"] - 1}
    )
    assert stale.status_code == 409
    added = (
        await api_client.post(f"/dashboards/{d['id']}/widgets", json={"spec": spec, "version": d["version"]})
    ).json()
    assert len(added["widgets"]) == len(d["widgets"]) + 1 and added["version"] > d["version"]


async def test_areopagus_builtins_and_fork(api_client):
    personas = (await api_client.get("/areopagus")).json()
    assert len([p for p in personas if p["builtin"]]) == 5
    assert (await api_client.put("/areopagus/socrates", json={"name": "X"})).status_code == 403
    fork = (await api_client.post("/areopagus/socrates/fork")).json()
    assert fork["builtin"] is False and fork["base_archetype"] == "skeptical_ic_partner"
    assert fork["signature_move"] == "Pre-mortem chain" and "pre-mortem" not in fork["id"]
    assert any(p["id"] == fork["id"] for p in (await api_client.get("/areopagus")).json())


async def test_fr13_builder_generate_create_edit(api_client):
    o = (await api_client.get("/areopagus/options")).json()
    assert len(o["lenses"]) == 12 and o["glyphs"] and o["cheque_roles"]
    assert (await api_client.post("/areopagus/generate", json={"description": "x" * 2001})).status_code == 422
    r = (
        await api_client.post(
            "/areopagus/generate",
            json={"description": "A skeptical partner named Rhea who is obsessed with NRR"},
        )
    ).json()
    assert r["source"] == "heuristic" and r["persona"]["name"] == "Rhea"
    made = (await api_client.post("/areopagus", json=r["persona"])).json()
    assert made["id"].startswith("rhea-") and made["builtin"] is False
    assert any(p["id"] == made["id"] for p in (await api_client.get("/areopagus")).json())
    edited = (
        await api_client.put(
            f"/areopagus/{made['id']}",
            json={"signature_move": "Cohorts first", "question_seeds": ["Only this one?"]},
        )
    ).json()
    assert edited["version"] == 2 and edited["question_seeds"] == ["Only this one?"]
    assert edited["signature_move"] == "Cohorts first" and edited["name"] == "Rhea"


async def test_session_survives_a_deleted_custom_investor(api_client):
    made = (await api_client.post("/areopagus", json={"name": "Temp"})).json()
    s = (await start_court(["aristotle", made["id"]], 4)).json()
    assert (await api_client.delete(f"/areopagus/{made['id']}")).status_code == 200
    view = await api_client.get(f"/court/{s['id']}")
    assert view.status_code == 200 and [p["id"] for p in view.json()["panel"]] == ["aristotle"]
    assert (await api_client.post(f"/court/{s['id']}/end")).status_code == 200


async def test_court_round_trip(api_client):
    s = (await start_court(["aristotle", "thales", "socrates"], 5)).json()
    assert s["status"] == "live" and s["awaiting"] == "founder"
    assert [t["kind"] for t in s["turns"]] == ["intro", "question"]
    first_q = s["turns"][-1]
    assert first_q["speaker"] in ("aristotle", "thales", "socrates") and first_q["citations"]

    s = (
        await api_client.post(f"/court/{s['id']}/answer", json={"text": "We're growing 10% a month."})
    ).json()
    assert any(c["status"] == "contradicts" for c in s["claims"])
    follow = [t for t in s["turns"] if t["kind"] == "question"][-1]
    assert (
        follow["speaker"] == first_q["speaker"] and follow["intent"] == "follow_up"
    )  # weak answer → same VC digs in

    s = (await api_client.post(f"/court/{s['id']}/answer", json={"text": "It'll pick up, trust me."})).json()
    coach = [t for t in s["turns"] if t["kind"] == "coach"]
    assert coach and not re.search(r"\d", coach[-1]["text"])  # FR-9: the time-out adds no figure

    answers = [
        "ARR is $1.29M: September MRR of $107,189 times 12, so recurring only. You're right that growth slowed; "
        "we plan to hire next quarter.",
        "Runway is 8 months at $58.4K burn, so the round has to close by Q1.",
        "Our largest customer is about 10% of MRR; the risk is real and the plan doesn't count their expansion.",
    ]
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
    r = await api_client.post("/pitch/start")
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["voice"], bool) and r.json()["stt"]["model_id"] == "scribe_v2_realtime"


def _blank_deck(pages: int) -> bytes:
    import io

    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=960, height=540)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


async def test_fr11_live_pitch_interrupts_on_a_contradiction(api_client):
    deck = await api_client.post(
        "/pitch/deck", files={"file": ("deck.pdf", _blank_deck(3), "application/pdf")}
    )
    assert deck.status_code == 200, deck.text
    d = deck.json()
    assert len(d["slides"]) == 3 and d["slides"][0]["image"].startswith("data:image/jpeg")
    assert (
        await api_client.post("/pitch/deck", files={"file": ("deck.txt", b"hello", "text/plain")})
    ).status_code == 415

    r = await api_client.post(
        "/pitch/start", json={"mode": "live", "panel": ["aristotle", "socrates"], "deck_id": d["id"]}
    )
    assert r.status_code == 200, r.text
    p = r.json()["pitch"]
    assert p["status"] == "presenting" and p["say"][0]["speaker"] == "vik"
    # Everyone in the room has a voice for this sitting, and nobody shares one.
    assert set(p["voices"]) == {"vik", "aristotle", "socrates"} and len(set(p["voices"].values())) == 3

    seg = (
        await api_client.post(
            f"/pitch/{p['id']}/segment",
            json={"text": "We're growing 10% a month.", "slide": 2, "t_ms": 40_000},
        )
    ).json()
    assert seg["claims"][0]["status"] == "contradicts" and seg["claims"][0]["truth"]
    it = seg["interrupt"]
    assert it and it["speaker"] in ("aristotle", "socrates") and seg["claims"][0]["truth"] in it["text"]
    assert seg["pitch"]["status"] == "answering"
    # One interrupt per slide, and none inside the cooldown, even while the answer is open.
    again = (
        await api_client.post(
            f"/pitch/{p['id']}/segment", json={"text": "Growing 10% a month.", "slide": 3, "t_ms": 45_000}
        )
    ).json()
    assert again["interrupt"] is None

    back = (
        await api_client.post(f"/pitch/{p['id']}/reply", json={"text": "Fair, it's closer to 3%."})
    ).json()
    assert back["say"][0]["speaker"] == it["speaker"] and back["pitch"]["status"] == "presenting"
    assert not re.search(r"\d", back["say"][0]["text"])
    assert (await api_client.post(f"/pitch/{p['id']}/reply", json={"text": "again"})).status_code == 409

    end = (await api_client.post(f"/pitch/{p['id']}/end")).json()
    assert end["court"] is None and end["pitch"]["status"] == "ended" and end["pitch"]["stats"]["words"] > 0
    assert (
        await api_client.post(f"/pitch/{p['id']}/segment", json={"text": "more", "slide": 1, "t_ms": 1})
    ).status_code == 409


async def test_after_pitch_qa_asks_about_what_was_said(api_client):
    p = (
        await api_client.post("/pitch/start", json={"mode": "after", "panel": ["aristotle", "thales"]})
    ).json()["pitch"]
    seg = (
        await api_client.post(
            f"/pitch/{p['id']}/segment",
            json={"text": "We're growing 10% a month.", "slide": None, "t_ms": 5_000},
        )
    ).json()
    assert seg["interrupt"] is None  # questions wait for the end
    end = (await api_client.post(f"/pitch/{p['id']}/end")).json()
    s = end["court"]
    assert end["pitch"]["status"] == "qa" and s["mode"] == "simulate" and s["status"] == "live"
    assert [t["kind"] for t in s["turns"]] == ["intro", "question"]
    assert s["turns"][0]["text"].startswith("That was the pitch.")
    # The Q&A is spoken in the voices the pitch cast: every panel line has its speaker's.
    assert all(t["speaker"] in p["voices"] for t in s["turns"] if t["speaker"] != "founder")
    assert len(set(p["voices"].values())) == len(p["voices"]) == 3
    assert (await api_client.post(f"/court/{s['id']}/end")).status_code == 200
    # The spoken claim stays on the TruthPack as a deck claim until the next deck replaces it.
    await api_client.post("/pitch/deck", files={"file": ("deck.pdf", _blank_deck(1), "application/pdf")})
