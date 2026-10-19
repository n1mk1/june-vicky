"""Agents reading the knowledge base: the note-quote rule in the audit, the kb_search / kb_read tools,
Ask Vik (offline keyword lookup and the Gemini tool loop) and the court memos, on recorded responses."""

import json

import pytest

from tests.llm_fakes import json_reply, queue, tool_use_reply
from vik.areopagus import registry
from vik.audit import audit_text
from vik.court import minds as offline
from vik.kb import store
from vik.kb.tools import Vault, excerpts, terms
from vik.llm import minds as agents
from vik.model.context import sample_context
from vik.qa import answer_any

BOARD = (
    "# Zephyrine partnership\n\nBoard update, 2026-09-14.\n\n"
    "The board approved the Zephyrine partnership pilot with 40 stores and a $250K minimum commitment.\n"
    "Next review in December.\n"
)
QUESTION = "What did the board say about the Zephyrine partnership?"
QUOTE = "The board approved the Zephyrine partnership pilot with 40 stores and a $250K minimum commitment."


@pytest.fixture(scope="module")
def ctx():
    return sample_context("tidewell")


def notes(path: str = "company/Zephyrine.md", content: str = BOARD) -> dict[str, dict]:
    return {
        path: {
            "id": "00000000-0000-0000-0000-000000000001",
            "path": path,
            "title": "Zephyrine partnership",
            "content": content,
        }
    }


# ---------------------------------------------------------------- the audit rule


def test_a_verbatim_note_quote_carries_its_numbers_and_cites_the_path(ctx):
    text = f"Your board minutes say “{QUOTE}” [kb:company/Zephyrine.md]"
    res = audit_text(text, ctx.available(), notes=notes())
    assert res.passed, res.feedback()
    (c,) = [c for c in res.citations if c.kind == "note"]
    assert c.display == "company/Zephyrine.md" and c.source["ref"] == "company/Zephyrine.md"
    assert text[c.start : c.end].startswith("“The board") and text[c.start : c.end].endswith(
        "[kb:company/Zephyrine.md]"
    )


def test_case_whitespace_and_markdown_marks_dont_break_a_quote(ctx):
    content = "The **board approved** the pilot with\n40 stores."
    assert audit_text(
        '"the board approved the pilot with 40 stores." [kb:a.md]',
        ctx.available(),
        notes=notes("a.md", content),
    ).passed


def test_a_restated_note_number_is_still_an_uncited_number(ctx):
    res = audit_text(
        "The board committed $250K to the pilot [kb:company/Zephyrine.md].", ctx.available(), notes=notes()
    )
    assert not res.passed
    assert {f.kind for f in res.findings} == {"note", "number"}


def test_a_number_beside_the_quote_needs_a_figure(ctx):
    res = audit_text(
        f"“{QUOTE}” [kb:company/Zephyrine.md] That is 4,321 stores more than last year.",
        ctx.available(),
        notes=notes(),
    )
    assert [f.kind for f in res.findings] == ["number"] and res.findings[0].text == "4,321"


def test_a_quote_the_note_doesnt_contain_is_blocked(ctx):
    res = audit_text(
        "“The board approved a $400K commitment.” [kb:company/Zephyrine.md]", ctx.available(), notes=notes()
    )
    assert not res.passed and "note" in {f.kind for f in res.findings}


def test_only_notes_the_tools_returned_can_be_cited(ctx):
    res = audit_text(f"“{QUOTE}” [kb:company/Other.md]", ctx.available(), notes=notes())
    assert not res.passed and res.findings[0].kind == "source"
    assert not audit_text(
        f"“{QUOTE}” [kb:company/Zephyrine.md]", ctx.available()
    ).passed  # no notes this turn


def test_a_note_quote_cant_carry_a_valuation(ctx):
    content = "Our pre-money valuation of $12M was agreed."
    assert not audit_text(f"“{content}” [kb:a.md]", ctx.available(), notes=notes("a.md", content)).passed


def test_excerpts_are_verbatim_lines_best_first():
    ts = terms(QUESTION)
    assert ts == ["board", "zephyrine", "partnership"]
    ex = excerpts(BOARD, ts)
    assert ex[0] == QUOTE and all(e in BOARD for e in ex)
    long = "intro " * 80 + "the zephyrine pilot starts in March " + "tail " * 80
    (cut,) = excerpts(long, ["zephyrine"])
    assert "zephyrine" in cut and cut in long and len(cut) <= 280


# ---------------------------------------------------------------- with the vault (throwaway database)


@pytest.fixture
async def board_note(api_client):
    """These tests cover the vault before the first Fill dashboard: no search index (docs/08-RAG.md);
    tests/test_rag.py covers search over a built index."""
    from vik import db
    from vik.kb import rag

    await db.execute("delete from kb_index_builds")
    rag.drop_index()
    note = await store.create_note(
        {"title": "Zephyrine partnership", "path": "company/Zephyrine", "content": BOARD}
    )
    yield note
    await store.delete_note(note["id"])


async def test_kb_search_and_read_return_excerpts_and_cite_tokens(board_note):
    v = Vault()
    found = await v.search("zephyrine partnership")
    hit = next(n for n in found["notes"] if n["id"] == board_note["id"])
    assert hit["path"] == board_note["path"] and hit["cite"] == f"[kb:{board_note['path']}]"
    assert QUOTE in hit["excerpts"] and "word for word" in found["how_to_cite"]
    assert board_note["path"] in v.notes()
    read = await Vault().read(board_note["path"].removesuffix(".md"))  # by path, extension optional
    assert read["id"] == board_note["id"] and read["content"] == BOARD and not read["truncated"]
    assert (await Vault().read(board_note["id"]))["path"] == board_note["path"]
    assert "error" in await Vault().read("no/such note")


async def test_offline_ask_vik_quotes_the_notes_when_the_data_cant_answer(board_note, ctx):
    out = await answer_any(QUESTION, ctx)
    assert out["topic"] == "notes" and out["audit"]["passed"]
    assert f"“{QUOTE}” [kb:{board_note['path']}]" in out["reply"]
    assert any(c["kind"] == "note" and c["source"]["ref"] == board_note["path"] for c in out["citations"])
    assert {"id": board_note["id"], "path": board_note["path"]} in out["notes"]
    assert (await answer_any("What is my ARR?", ctx))["topic"] != "notes"  # the data answers this one


async def test_gemini_reads_the_vault_and_quotes_it(board_note, ctx, live_llm):
    path = board_note["path"]
    reply = f"Your board minutes say “{QUOTE}” [kb:{path}]"
    rec = live_llm.install(
        queue(tool_use_reply("kb_search", {"query": "Zephyrine partnership"}), json_reply({"reply": reply}))
    )
    out = await answer_any(QUESTION, ctx)
    assert out["llm"] and out["reply"] == reply
    assert any(c["kind"] == "note" for c in out["citations"]) and out["notes"][0]["path"] == path
    assert {t["name"] for t in rec.calls[0]["body"]["tools"]} == {"kb_search", "kb_read"}
    result = next(
        b
        for m in rec.calls[1]["body"]["messages"]
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
        if b.get("type") == "tool_result"
    )
    hit = next(n for n in json.loads(result["content"])["notes"] if n["path"] == path)
    assert QUOTE in hit["excerpts"] and hit["cite"] == f"[kb:{path}]"


async def test_gemini_restating_a_note_number_falls_back_to_the_quote(board_note, ctx, live_llm):
    live_llm.install(
        queue(
            tool_use_reply("kb_read", {"note": board_note["path"]}),
            json_reply({"reply": f"The board committed $250K to Zephyrine [kb:{board_note['path']}]."}),
        )
    )
    out = await answer_any(QUESTION, ctx)
    assert "llm" not in out and out["topic"] == "notes" and "The board committed" not in out["reply"]
    assert f"“{QUOTE}”" in out["reply"]


async def test_memo_may_quote_a_note_it_read(board_note, ctx, live_llm):
    james = registry.builtins()["aristotle"]
    owned = offline.build_memos([james], ctx)["aristotle"]["hypotheses"][0]
    path = board_note["path"]
    thesis = f"Their board pack says “a $250K minimum commitment” [kb:{path}], so the pilot is small."
    memo = {
        "thesis": thesis,
        "hypotheses": [
            {
                "attack_id": owned["attack_id"],
                "claim": "Growth is decelerating",
                "lens": owned["lens"],
                "evidence": owned["evidence"],
                "severity": 0.8,
                "confidence": 0.7,
            }
        ],
        "mind_changers": [f"The signed terms behind “40 stores” [kb:{path}]"],
        "opening_question": "Why did the board only commit $250K to Zephyrine?",
    }  # restated: dropped
    rec = live_llm.install(
        queue(
            tool_use_reply("kb_read", {"note": path}, model="gemini-4-argon"),
            json_reply(memo, model="gemini-4-argon"),
        )
    )
    out = (await agents.build_memos([james], ctx))["aristotle"]
    assert out["source"] == "llm" and out["thesis"] == thesis and out["kb_notes"] == [path]
    assert out["mind_changers"] == memo["mind_changers"]
    assert out["opening_question"] != memo["opening_question"]
    assert {"kb_search", "kb_read"} <= {t["name"] for t in rec.calls[0]["body"]["tools"]}
