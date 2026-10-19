"""Retrieval over the knowledge base (docs/08-RAG.md): chunking, BM25, the cite-every-statement rule, index
builds on Fill dashboard (full rebuild, swap, discard), hybrid retrieval with a fake Voyage, the Ask Vik
ladder and the catch-all offer that never runs without the user's go-ahead."""

import hashlib
import json
import math
import re

import httpx
import pytest

from tests.helpers import start_court
from tests.llm_fakes import json_reply
from vik import db, jobs, kv
from vik.audit import audit_text
from vik.kb import ask, index, rag, store, voyage
from vik.kb.bm25 import BM25, stem, tokens
from vik.kb.chunk import MAX_CHARS, chunk_note
from vik.model.context import sample_context

DECK = """# Pitch deck

## Slide 1: Problem

Grocers throw away 9% of fresh stock every week.

## Slide 2: Traction

Our net revenue retention was strong last year. Pilot customers renewed.

## Page 3

The board approved the Zephyrine partnership pilot with 40 stores and a $250K minimum commitment.
"""
HIRING = "# Hiring plan\n\nWe will hire two engineers and one account executive before the next round.\n"


@pytest.fixture(scope="module")
def ctx():
    return sample_context("tidewell")


# ---------------------------------------------------------------- chunking


def test_every_chunk_is_a_span_of_its_note_and_never_crosses_a_heading():
    chunks = chunk_note(DECK)
    assert chunks
    for c in chunks:
        assert DECK[c.start : c.end] == c.text
    assert {c.heading for c in chunks} >= {"Slide 1: Problem", "Slide 2: Traction", "Page 3"}
    assert not any("Slide 1" in c.text and "Slide 2" in c.text for c in chunks)


def test_a_long_table_splits_by_rows_and_each_piece_carries_the_header():
    rows = "\n".join(
        f"| 2026-{m:02d} | {m * 1000} | note for month {m} with a little more text |" for m in range(1, 13)
    )
    table = "| Month | Revenue | Comment |\n|---|---|---|\n" + "\n".join([rows] * 4)
    content = "# Revenue\n\n" + table + "\n"
    chunks = chunk_note(content)
    assert len(chunks) > 1
    for c in chunks:
        assert content[c.start : c.end] == c.text and len(c.text) <= MAX_CHARS + 200
    assert all(c.header.startswith("| Month") for c in chunks[1:])


def test_a_short_table_stays_whole():
    content = "Intro paragraph.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    table = "| a | b |\n|---|---|\n| 1 | 2 |"
    assert any(table in c.text for c in chunk_note(content))


def test_a_csv_note_is_one_chunk_its_header_row():
    (c,) = chunk_note("month,revenue,cogs\n2026-01,100,40\n2026-02,120,44\n", "csv")
    assert c.text == "month,revenue,cogs"


# ---------------------------------------------------------------- BM25 and expansion


def test_stemmer_maps_word_forms_together():
    assert stem("churned") == stem("churn") == stem("churning")
    assert stem("rates") == stem("rate") and stem("taxes") == "tax" and stem("planned") == "plan"


def test_bm25_ranks_the_matching_doc_first():
    docs = [tokens("hiring plan for engineers"), tokens(DECK), tokens("customer churn rate fell")]
    hits = BM25(docs).search({t: 1.0 for t in tokens("who are we hiring")})
    assert hits[0][0] == 0


def test_glossary_expansion_adds_synonyms_at_half_weight():
    weighted, own = rag.expand("what is our NRR?")
    assert own == ["nrr"] and weighted["nrr"] == 1.0
    assert weighted[stem("retention")] == 0.5


# ---------------------------------------------------------------- the citation rule


def _notes(content: str = DECK, path: str = "company/Deck.md") -> dict:
    return {
        path: {
            "id": "00000000-0000-0000-0000-000000000002",
            "path": path,
            "title": "Pitch deck",
            "content": content,
        }
    }


def test_every_statement_must_cite_a_note_or_a_figure(ctx):
    quote = (
        "The board approved the Zephyrine partnership pilot with 40 stores and a $250K minimum commitment."
    )
    good = f"Your board pack says “{quote}” [kb:company/Deck.md]"
    assert audit_text(good, ctx.available(), notes=_notes(), require_citations=True).passed
    bad = good + " That partnership will transform the business."
    res = audit_text(bad, ctx.available(), notes=_notes(), require_citations=True)
    assert not res.passed and [f.kind for f in res.findings] == ["uncited"]
    # without the flag the old rules apply and the uncited prose passes
    assert audit_text(bad, ctx.available(), notes=_notes()).passed


def test_a_question_needs_no_citation(ctx):
    text = "“Pilot customers renewed.” [kb:company/Deck.md] Want me to look at churn next?"
    assert audit_text(text, ctx.available(), notes=_notes(), require_citations=True).passed


def test_a_figure_counts_as_a_citation(ctx):
    f = next(f for f in ctx.available() if f.unit in ("usd", "cad", "money"))
    res = audit_text(f"{f.label} is {f.display}.", ctx.available(), require_citations=True)
    assert res.passed, res.feedback()


def test_the_semantic_cache_guard_keeps_periods_apart():
    assert ask._guard("What was Q3 revenue?") != ask._guard("What was Q4 revenue?")
    assert ask._guard("what was our revenue in q3") == ask._guard("Q3 revenue?")


# ---------------------------------------------------------------- database: builds, retrieval, the ladder


def _fake_vec(text: str) -> list[float]:
    v = [0.0] * voyage.DIMS
    for t in tokens(text):
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        v[h % voyage.DIMS] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class FakeVoyage:
    def __init__(self):
        self.calls: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.calls.append({"path": request.url.path, "body": body})
        if request.url.path.endswith("/embeddings"):
            data = [
                {"object": "embedding", "embedding": _fake_vec(t), "index": i}
                for i, t in enumerate(body["input"])
            ]
            return httpx.Response(
                200,
                json={"object": "list", "data": data, "model": body["model"], "usage": {"total_tokens": 10}},
            )
        q = set(tokens(body["query"]))
        scored = [(i, len(q & set(tokens(d))) / (len(q) or 1)) for i, d in enumerate(body["documents"])]
        scored.sort(key=lambda x: -x[1])
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": body["model"],
                "usage": {"total_tokens": 10},
                "data": [{"index": i, "relevance_score": s} for i, s in scored],
            },
        )

    def embeds(self) -> int:
        return sum(
            len(c["body"]["input"])
            for c in self.calls
            if c["path"].endswith("/embeddings") and c["body"]["input_type"] == "document"
        )


@pytest.fixture
def fake_voyage():
    f = FakeVoyage()
    voyage.set_transport(httpx.MockTransport(f.handler))
    yield f
    voyage.set_transport(None)


@pytest.fixture
async def vault(api_client):
    """A clean index and two notes; afterwards no build is left active (other tests use the old search)."""
    await db.execute("delete from kb_index_builds")
    rag.drop_index()
    deck = await store.create_note({"title": "Pitch deck", "path": "company/Deck", "content": DECK})
    hiring = await store.create_note({"title": "Hiring plan", "path": "team/Hiring plan", "content": HIRING})
    yield {"deck": deck, "hiring": hiring}
    await db.execute("delete from kb_index_builds")
    await db.execute("delete from rag_misses")
    rag.drop_index()
    for n in (deck, hiring):
        try:
            await store.delete_note(n["id"])
        except Exception:
            pass
    try:
        async for k in kv.client().scan_iter(match="rag:*"):
            await kv.client().unlink(k)
    except Exception:
        pass


async def _build() -> str:
    b = await index.start_build()
    job = await db.fetchval("select job_id::text from kb_index_builds where id = $1::uuid", b["build_id"])
    await jobs.wait_for([job], 60)
    st = await db.fetchval("select status from kb_index_builds where id = $1::uuid", b["build_id"])
    assert st == "active", st
    return b["build_id"]


@pytest.mark.db
async def test_a_build_indexes_every_note_and_kb_search_uses_it(vault):
    bid = await _build()
    assert int(await db.fetchval("select count(*) from kb_chunks where build_id = $1::uuid", bid)) >= 4
    r = await rag.retrieve("Who are we hiring before the next round?")
    assert r.chunks and r.chunks[0]["path"] == vault["hiring"]["path"]
    from vik.kb.tools import Vault

    v = Vault()
    out = await v.search("Zephyrine partnership pilot")
    assert out["notes"][0]["path"] == vault["deck"]["path"]
    assert any("Zephyrine" in e for e in out["notes"][0]["excerpts"])
    assert vault["deck"]["path"] in v.notes()  # its quotes can be audited


@pytest.mark.db
async def test_a_rebuild_replaces_the_old_index_and_discards_its_state(vault):
    old = await _build()
    await kv.set_json(f"rag:ret:{old}:1:ask:8:x", {"stale": True}, 600)
    await db.execute(
        "update kb_notes set content = $2 where id = $1::uuid",
        vault["hiring"]["id"],
        HIRING + "\nWe also plan a head of sales.\n",
    )
    new = await _build()
    assert new != old
    statuses = dict(
        (r["id"], r["status"]) for r in await db.fetch("select id::text, status from kb_index_builds")
    )
    assert statuses[old] == "superseded" and statuses[new] == "active"
    assert not await db.fetchval("select count(*) from kb_chunks where build_id = $1::uuid", old)
    assert await kv.get_json(f"rag:ret:{old}:1:ask:8:x") is None
    r = await rag.retrieve("head of sales")
    assert any("head of sales" in c["text"] for c in r.chunks)


@pytest.mark.db
async def test_between_fills_edited_notes_old_chunks_are_skipped_and_new_notes_wait(vault):
    await _build()
    await store.update_note(vault["hiring"]["id"], {"content": "# Hiring plan\n\nNo hires this year.\n"})
    r = await rag.retrieve("hire engineers account executive")
    assert not any(c["note_id"] == vault["hiring"]["id"] for c in r.chunks)
    extra = await store.create_note(
        {"title": "Pricing", "path": "product/Pricing", "content": "Pricing tiers: basic and pro."}
    )
    try:
        r = await rag.retrieve("pricing tiers basic pro")
        assert not any(c["note_id"] == extra["id"] for c in r.chunks)
        st = await index.status()
        assert st["status"] == "ready" and st["changed_since"] >= 2
    finally:
        await store.delete_note(extra["id"])


@pytest.mark.db
async def test_a_new_fill_cancels_a_running_build_and_a_failed_build_keeps_the_old_one(vault, monkeypatch):
    first = await _build()
    from vik.kb import index as idx_mod

    def boom(*_a, **_k):
        raise RuntimeError("chunker exploded")

    monkeypatch.setattr(idx_mod, "chunk_note", boom)
    b = await index.start_build()
    job = await db.fetchval("select job_id::text from kb_index_builds where id = $1::uuid", b["build_id"])
    await jobs.wait_for([job], 30)
    assert (
        await db.fetchval("select status from kb_index_builds where id = $1::uuid", b["build_id"]) == "failed"
    )
    assert await index.active_build_id() == first
    monkeypatch.undo()
    a = await index.start_build()
    c = await index.start_build()  # the second Fill cancels the first
    assert (
        await db.fetchval("select status from kb_index_builds where id = $1::uuid", a["build_id"])
        == "cancelled"
    )
    job = await db.fetchval("select job_id::text from kb_index_builds where id = $1::uuid", c["build_id"])
    await jobs.wait_for([job], 60)
    assert await index.active_build_id() == c["build_id"]
    assert int(await db.fetchval("select count(*) from kb_index_builds where status = 'active'")) == 1


@pytest.mark.db
async def test_fill_drafts_and_confirm_knowledge_base_builds_search(vault, api_client):
    """Fill dashboard only drafts the intake; confirming the knowledge base rebuilds search, with the confirmed
    profile and mappings written into the vault as a note (docs/08-RAG.md §Indexing)."""
    await api_client.post("/auth/access", json={"code": "vik-demo"})
    table = await store.create_note(
        {
            "title": "KPIs",
            "path": "financials/KPIs",
            "format": "csv",
            "content": "month,mrr\n2025-01,100\n2025-02,120\n",
        }
    )
    active = await db.fetchval("select id::text from engagements where status = 'active'")
    before = await db.fetchval("select count(*) from kb_index_builds")
    r = await api_client.post("/kb/autofill")
    assert r.status_code == 200, r.text
    assert await db.fetchval("select count(*) from kb_index_builds") == before  # Fill builds nothing
    eid = r.json()["engagement"]["id"]
    c = await api_client.post(f"/engagements/{eid}/confirm")
    assert c.status_code == 200, c.text
    b = c.json()["index"]
    job = await db.fetchval("select job_id::text from kb_index_builds where id = $1::uuid", b["build_id"])
    await jobs.wait_for([job], 60)
    st = (await api_client.get("/kb/status")).json()["index"]
    assert st["status"] == "ready" and st["build_id"] == b["build_id"] and st["chunks"] > 0
    note = await db.fetchrow(
        "select path, content, meta from kb_notes where meta->>'generated' = 'confirmed_kb'"
    )
    assert note and note["path"] == "company/Confirmed knowledge base.md"
    indexed = await db.fetchval(
        "select count(*) from kb_chunks c join kb_notes n on n.id = c.note_id "
        "where c.build_id = $1::uuid and n.meta->>'generated' = 'confirmed_kb'",
        b["build_id"],
    )
    assert indexed > 0
    # A second Fill never sends the confirmed note back to the intake.
    again = (await api_client.post("/kb/autofill")).json()
    assert all(a["note"] != note["path"] for a in again["added"])
    await db.execute(
        "delete from engagements where id::text = any($1::text[])", [eid, again["engagement"]["id"]]
    )
    if active:  # the sample stays the source of truth for the tests after this one
        await db.execute("update engagements set status = 'active' where id::text = $1", active)
    await db.execute("delete from kb_notes where meta->>'generated' = 'confirmed_kb'")
    await store.delete_note(table["id"])


@pytest.mark.db
async def test_vectors_rerank_and_reuse_with_pgvector(vault, fake_voyage):
    if not await index.has_vector():
        pytest.skip("pgvector not available in this database")
    await _build()
    first = fake_voyage.embeds()
    assert first >= 4
    r = await rag.retrieve("Zephyrine partnership commitment")
    assert r.signals["vectors"] and r.signals["reranked"] and r.chunks[0]["path"] == vault["deck"]["path"]
    assert r.confidence >= 0.55
    await _build()  # nothing changed: every vector is copied, none sent again
    assert fake_voyage.embeds() == first
    assert await db.fetchval("select reused from kb_index_builds where status = 'active'") == first


# ---------------------------------------------------------------- Ask Vik over the index

QUOTE = "The board approved the Zephyrine partnership pilot with 40 stores and a $250K minimum commitment."


@pytest.mark.db
async def test_ask_vik_answers_from_passages_and_caches_it(vault, ctx, live_llm):
    await _build()
    reply = f"Your board pack says “{QUOTE}” [kb:{vault['deck']['path']}]"
    rec = live_llm.install(
        lambda call: json_reply({"answerable": True, "reply": reply}, model="gemini-3.5-flash-lite")
    )
    from vik.qa import answer_any

    q = "What did the board approve for the Zephyrine partnership?"
    out = await answer_any(q, ctx)
    assert out["reply"] == reply and out["rag"]["path"] in ("chunks", "recover")
    assert any(c["kind"] == "note" for c in out["citations"])
    assert rec.calls[0]["body"]["model"] == "gemini-3.5-flash-lite"
    n = len(rec.calls)
    again = await answer_any(q, ctx)
    assert again["reply"] == reply and again["rag"]["cache"] == "exact" and len(rec.calls) == n


@pytest.mark.db
async def test_an_uncited_sentence_is_regenerated_then_dropped(vault, ctx, live_llm):
    await _build()
    good = f"“{QUOTE}” [kb:{vault['deck']['path']}]"
    replies = [
        json_reply(
            {"answerable": True, "reply": good + " This will double revenue."}, model="gemini-3.5-flash-lite"
        ),
        json_reply({"answerable": True, "reply": good}, model="gemini-3.5-flash-lite"),
    ]
    rec = live_llm.install(lambda call: replies.pop(0))
    from vik.kb.ask import from_chunks
    from vik.qa import answer

    q = "What did the board approve for the Zephyrine partnership?"
    r = await rag.retrieve(q)
    out, ok = await from_chunks(q, ctx, answer(q, ctx), r, "chunks")
    assert ok and out["reply"] == good
    assert "citation audit" in json.dumps(rec.calls[1]["body"]["messages"][-1])


@pytest.mark.db
async def test_the_catch_all_is_offered_and_runs_only_after_accept(vault, ctx, live_llm, api_client):
    await _build()
    calls = []

    def respond(call):
        calls.append(call)
        system = json.dumps(call["body"].get("system"))
        if "holds every note" in system:
            return json_reply(
                {
                    "answerable": True,
                    "reply": f"“We will hire two engineers and one account executive "
                    f"before the next round.” [kb:{vault['hiring']['path']}]",
                },
                model="gemini-3.5-flash-lite",
            )
        return json_reply(
            {"answerable": False, "reply": "Not in the passages."}, model="gemini-3.5-flash-lite"
        )

    live_llm.install(respond)
    await api_client.post("/auth/access", json={"code": "vik-demo"})
    d = await api_client.get("/dashboards/active")
    if d.status_code == 404:
        from tests.helpers import load_and_confirm

        await load_and_confirm(api_client, "tidewell")
        d = await api_client.get("/dashboards/active")
    did = d.json()["id"]
    r = await api_client.post(
        f"/dashboards/{did}/chat", json={"text": "What does the plan say about the purple elephant?"}
    )
    assert r.status_code == 200, r.text
    offer = r.json().get("offer")
    assert offer and offer["kind"] == "catch_all"
    assert not any(
        "holds every note" in json.dumps(c["body"].get("system")) for c in calls
    )  # nothing ran yet
    assert await db.fetchval("select decision from rag_misses order by created_at desc limit 1") == "pending"

    other = await api_client.post(
        "/dashboards/00000000-0000-0000-0000-000000000000/chat/catch-all",
        json={"offer_id": offer["id"], "accept": True},
    )
    assert other.status_code == 410
    # the foreign attempt consumed nothing it shouldn't: a fresh offer for the real dashboard
    r = await api_client.post(
        f"/dashboards/{did}/chat", json={"text": "What does the plan say about the purple elephant?"}
    )
    offer = r.json()["offer"]
    ok = await api_client.post(
        f"/dashboards/{did}/chat/catch-all", json={"offer_id": offer["id"], "accept": True}
    )
    assert ok.status_code == 200, ok.text
    assert "account executive" in ok.json()["reply"] and ok.json()["citations"]
    assert sum("holds every note" in json.dumps(c["body"].get("system")) for c in calls) == 1
    again = await api_client.post(
        f"/dashboards/{did}/chat/catch-all", json={"offer_id": offer["id"], "accept": True}
    )
    assert again.status_code == 410
    row = await db.fetchrow(
        "select decision, passed, cited_notes from rag_misses order by created_at desc limit 1"
    )
    assert row["decision"] == "accepted" and row["passed"] and row["cited_notes"] == [vault["hiring"]["path"]]

    r = await api_client.post(f"/dashboards/{did}/chat", json={"text": "Anything about the green giraffe?"})
    no = await api_client.post(
        f"/dashboards/{did}/chat/catch-all", json={"offer_id": r.json()["offer"]["id"], "accept": False}
    )
    assert no.status_code == 204
    assert await db.fetchval("select decision from rag_misses order by created_at desc limit 1") == "declined"
    assert sum("holds every note" in json.dumps(c["body"].get("system")) for c in calls) == 1


@pytest.mark.db
async def test_no_offer_without_a_key_or_over_budget(vault, ctx, live_llm, monkeypatch):
    await _build()
    live_llm.install(
        lambda call: json_reply({"answerable": False, "reply": "no"}, model="gemini-3.5-flash-lite")
    )
    from vik.llm import client

    async def over() -> bool:
        return True

    monkeypatch.setattr(client, "over_budget", over)
    from vik.qa import answer_any

    out = await answer_any(
        "What does the plan say about the purple elephant?",
        ctx,
        dashboard_id="00000000-0000-0000-0000-000000000001",
    )
    assert "offer" not in out


@pytest.mark.db
async def test_offline_with_an_index_quotes_the_best_passage(vault, ctx):
    await _build()
    from vik.qa import answer_any

    out = await answer_any("Who will we hire before the next round?", ctx)
    assert out["topic"] == "notes" and "account executive" in out["reply"]
    assert re.search(r"\[kb:team/Hiring plan\.md\]", out["reply"])


# ---------------------------------------------------------------- the live court reads the notes

HIRE_QUOTE = "We will hire two engineers and one account executive before the next round."


@pytest.mark.db
async def test_the_court_reads_notes_each_turn_and_a_line_may_quote_one(
    vault, api_client, live_llm, monkeypatch
):
    from tests.test_llm_api import _login_and_confirm, scripted
    from vik.config import get_settings

    monkeypatch.setattr(
        get_settings(), "rag_conf_min", 0.0
    )  # plumbing, not calibration: always pass passages
    await _build()
    seen: dict[str, list[str]] = {"speak": [], "judge": [], "bid": []}

    def respond(call):
        task = call["task"]
        user = (
            next((m["content"] for m in reversed(call["body"]["messages"]) if m["role"] == "user"), "")
            if call["body"]
            else ""
        )
        if task in seen:
            seen[task].append(user if isinstance(user, str) else "")
        if task == "speak" and "<passage" in (user or "") and "hiring" in (user or "").lower():
            return {
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "gemini-3.8-flash",
                "content": [
                    {
                        "type": "text",
                        "text": f"Your plan says “{HIRE_QUOTE}” "
                        f"[kb:{vault['hiring']['path']}] How will you fund that?",
                    }
                ],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "stop_details": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            }
        return scripted(call)

    live_llm.install(respond)
    await _login_and_confirm(api_client)
    r = await start_court(["aristotle", "thales"], 4)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    state = await db.fetchval("select state from sessions where id::text = $1", sid)
    assert state["kb_build"] and any(h.get("kb") for vs in state["vcs"].values() for h in vs["hyps"])

    r = await api_client.post(
        f"/court/{sid}/answer", json={"text": "We're hiring engineers and an account executive."}
    )
    assert r.status_code == 200, r.text
    assert any("<passage" in u for u in seen["judge"]) and any("<passage" in u for u in seen["bid"])
    last = r.json()["turns"][-1]
    if last["kind"] == "question" and "[kb:" in last["text"]:
        assert any(c.get("kind") == "note" for c in last["citations"]), last
        audit = await db.fetchval(
            "select audit from turns where session_id::text = $1 order by seq desc limit 1", sid
        )
        assert audit["passed"], audit
    else:  # the chair may have picked a line without notes; the passages still reached the speaker
        assert any("<passage" in u for u in seen["speak"])


@pytest.mark.db
async def test_a_court_line_quoting_a_note_it_wasnt_given_fails_the_audit(vault, ctx):
    from vik.audit import audit_text as audit

    line = f"Your plan says “{HIRE_QUOTE}” [kb:{vault['hiring']['path']}] How will you fund that?"
    assert not audit(line, ctx.available(), notes={}).passed
