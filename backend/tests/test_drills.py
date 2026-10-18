"""Founder memory: drills the founder marked open the next session, and a report's weak spots carry over."""

import copy

import pytest

from vicky import db, memory
from vicky.areopagus import registry
from vicky.court import minds, referee
from vicky.model.context import sample_context


@pytest.fixture(scope="module")
def court():
    ctx = sample_context("tidewell")
    panel = [registry.builtins()[i] for i in registry.DEFAULT_PANEL]
    return ctx, panel, minds.build_memos(panel, ctx)


def _hyps(memos: dict) -> list[tuple[str, dict]]:
    return [(vc, h) for vc, m in memos.items() for h in m["hypotheses"]]


def _row(h: dict, kind: str = "drill", mark: str = "repeat", **pl) -> dict:
    return {
        "id": f"m-{h['id']}-{kind}",
        "lens": h["lens"],
        "topic": h["claim"],
        "severity": h["severity"],
        "payload": {
            "attack_id": h["attack_id"],
            "vc_id": h["id"].split(".")[0],
            "mark": mark,
            "question": "Old question?",
            **pl,
        },
    }


def test_drilled_topics_lead_the_agenda_repeat_before_study(court):
    ctx, panel, base = court
    memos = copy.deepcopy(base)
    (_, last), (_, second_last) = _hyps(memos)[-1], _hyps(memos)[-2]
    sev = {last["id"]: last["severity"], second_last["id"]: second_last["severity"]}
    carried, queue = memory.carry_over(
        memos, panel, ctx, {"drills": [_row(second_last, mark="study"), _row(last)], "weaknesses": []}, cap=8
    )
    assert queue == [last["id"], second_last["id"]]  # repeat first
    hs = dict((h["id"], h) for _, h in _hyps(memos))
    assert hs[last["id"]]["severity"] == round(min(1.0, sev[last["id"]] + memory.DRILL_BOOST["repeat"]), 2)
    assert hs[second_last["id"]]["drill"] == "study"
    assert [e["hypothesis_id"] for e in carried] == [second_last["id"], last["id"]]


def test_a_weak_spot_raises_severity_and_never_lowers_the_doubt(court):
    ctx, panel, base = court
    memos = copy.deepcopy(base)
    _, h = _hyps(memos)[0]
    before = dict(h)
    row = _row(h, kind="weakness", confidence=0.95) | {"severity": 0.5}
    carried, queue = memory.carry_over(memos, panel, ctx, {"drills": [], "weaknesses": [row]}, cap=8)
    assert queue == [] and carried[0]["kind"] == "weakness"
    assert h["severity"] >= before["severity"] and h["confidence"] == 0.95 and h["carried"] == "weakness"
    # A remembered lower confidence doesn't concede the doubt.
    memos = copy.deepcopy(base)
    _, h = _hyps(memos)[0]
    memory.carry_over(
        memos, panel, ctx, {"drills": [], "weaknesses": [_row(h, kind="weakness", confidence=0.1)]}, cap=8
    )
    assert h["confidence"] == before["confidence"]


def test_a_drilled_topic_nobody_owns_is_seated_with_the_best_lens(court):
    ctx, panel, base = court
    memos = copy.deepcopy(base)
    vc, h = _hyps(memos)[0]
    memos[vc]["hypotheses"].remove(h)
    _, queue = memory.carry_over(memos, panel, ctx, {"drills": [_row(h)], "weaknesses": []}, cap=8)
    (seated,) = [x for _, x in _hyps(memos) if x["attack_id"] == h["attack_id"]]
    assert queue == [seated["id"]] and seated["drill"] == "repeat"


def test_vicky_offers_the_next_drill_unless_the_answer_was_weak(court):
    ctx, panel, base = court
    memos = copy.deepcopy(base)
    _, h = _hyps(memos)[-1]
    _, queue = memory.carry_over(memos, panel, ctx, {"drills": [_row(h)], "weaknesses": []}, cap=8)
    state = {"vcs": {vc: {"hyps": m["hypotheses"]} for vc, m in memos.items()}, "drill_agenda": queue}
    ranked = [referee.Candidate("aristotle", "new_topic", "aristotle.h1", 0.9)]
    c = memory.agenda_candidate(state, ranked, weak=False)
    assert c is not None and c.target_hyp == h["id"] and c.score > 0.9 and c.intent == "new_topic"
    assert memory.agenda_candidate(state, ranked, weak=True) is None  # the follow-up comes first
    h["asked"] = 1
    assert memory.agenda_candidate(state, ranked, weak=False) is None


def test_the_view_says_which_drills_came_back():
    state = {
        "carried": [
            {"memory_id": "a", "kind": "drill", "mark": "repeat", "hypothesis_id": "x.h1"},
            {"memory_id": "b", "kind": "drill", "mark": "study", "hypothesis_id": "y.h2"},
            {"memory_id": "c", "kind": "drill", "mark": "study", "hypothesis_id": None},
        ]
    }
    turns = [
        {"kind": "intro", "hypothesis_id": None, "seq": 1},
        {"kind": "question", "hypothesis_id": "x.h1", "seq": 2},
    ]
    v = memory.carried_view(state, turns, live=True)
    assert [(e["status"], e["asked_seq"]) for e in v] == [("asked", 2), ("queued", None), ("unmatched", None)]
    assert memory.carried_view(state, turns, live=False)[1]["status"] == "not_reached"


# ---------------------------------------------------------------- end to end

ANSWER = "Fair question; the weak spot is real and we plan to fix it next quarter."


@pytest.mark.db
async def test_drilled_questions_open_the_next_session_and_weak_spots_carry_over(api_client):
    from tests.test_llm_api import _login_and_confirm

    await _login_and_confirm(api_client)
    await db.execute(
        "update founder_memory set payload = payload || '{\"used_by\": \"old\"}' where kind = 'drill'"
    )
    s = (await api_client.post("/court/start", json={"question_cap": 6, "knowledge": False})).json()
    for _ in range(3):
        s = (await api_client.post(f"/court/{s['id']}/answer", json={"text": ANSWER})).json()
    qs = [t for t in s["turns"] if t["kind"] == "question" and t["intent"] != "follow_up"]
    assert len(qs) >= 2
    marked = qs[-2:]  # not the opener, so the drill is what moves them to the top
    r = await api_client.post(
        f"/court/{s['id']}/drills",
        json={
            "items": [{"seq": marked[0]["seq"], "mark": "repeat"}, {"seq": marked[1]["seq"], "mark": "study"}]
        },
    )
    assert r.status_code == 200, r.text
    drills = r.json()["drills"]
    assert [d["mark"] for d in drills] == ["repeat", "study"]
    state1 = await db.fetchval("select state from sessions where id::text = $1", s["id"])
    attack = {h["id"]: h["attack_id"] for v in state1["vcs"].values() for h in v["hyps"]}
    want = [attack[q["hypothesis_id"]] for q in marked]

    s2 = (
        await api_client.post(
            "/court/start", json={"question_cap": 6, "knowledge": False, "drills": [d["id"] for d in drills]}
        )
    ).json()
    state2 = await db.fetchval("select state from sessions where id::text = $1", s2["id"])
    attack2 = {h["id"]: h["attack_id"] for v in state2["vcs"].values() for h in v["hyps"]}
    first = next(t for t in s2["turns"] if t["kind"] == "question")
    assert attack2[first["hypothesis_id"]] == want[0], "the repeat drill didn't open the session"
    came_back = [e for e in s2["carried"] if e["kind"] == "drill"]
    assert [e["mark"] for e in came_back] == ["repeat", "study"] and came_back[0]["status"] == "asked"
    for _ in range(3):  # the study drill follows once the answer isn't weak enough for a follow-up
        if all(e["status"] == "asked" for e in came_back):
            break
        s2 = (await api_client.post(f"/court/{s2['id']}/answer", json={"text": ANSWER})).json()
        came_back = [e for e in s2["carried"] if e["kind"] == "drill"]
    assert all(e["status"] == "asked" for e in came_back), came_back
    assert {attack2[e["hypothesis_id"]] for e in came_back} == set(want)
    agenda = await db.fetchval("select agenda from sessions where id::text = $1", s2["id"])
    assert [a["carried"] for a in agenda[:2]] == ["drill_repeat", "drill_study"]
    used = await db.fetch(
        "select payload from founder_memory where id::text = any($1::text[])", [d["id"] for d in drills]
    )
    assert all(u["payload"]["used_by"] == s2["id"] for u in used)

    # The report's open doubts are weak spots; the next session starts with them, without any drill.
    s2 = (await api_client.post(f"/court/{s2['id']}/end")).json()
    weak = await db.fetch(
        "select id::text, topic, payload, severity from founder_memory where kind = 'weakness' "
        "and payload->>'session_id' = $1",
        s2["id"],
    )
    assert weak and all(w["payload"]["attack_id"] for w in weak)
    s3 = (await api_client.post("/court/start", json={"question_cap": 6, "knowledge": False})).json()
    carried = s3["carried"]
    assert not [e for e in carried if e["kind"] == "drill"], "used drills came back"
    assert {e["topic"] for e in carried if e["kind"] == "weakness"} >= {w["topic"] for w in weak} & {
        h["claim"]
        for v in (await db.fetchval("select state from sessions where id::text = $1", s3["id"]))[
            "vcs"
        ].values()
        for h in v["hyps"]
    }
    state3 = await db.fetchval("select state from sessions where id::text = $1", s3["id"])
    for e in (e for e in carried if e["kind"] == "weakness" and e["memory_id"] in {w["id"] for w in weak}):
        h = next(h for v in state3["vcs"].values() for h in v["hyps"] if h["id"] == e["hypothesis_id"])
        w = next(w for w in weak if w["id"] == e["memory_id"])
        assert h["severity"] >= min(1.0, float(w["severity"]) + memory.WEAK_BOOST) - 1e-9
        assert h["confidence"] >= w["payload"]["confidence"]


@pytest.mark.db
async def test_drills_need_questions_from_that_session(api_client):
    from tests.test_llm_api import _login_and_confirm

    await _login_and_confirm(api_client)
    s = (await api_client.post("/court/start", json={"question_cap": 4, "knowledge": False})).json()
    r = await api_client.post(f"/court/{s['id']}/drills", json={"items": [{"seq": 999, "mark": "repeat"}]})
    assert r.status_code == 422
    r = await api_client.post(f"/court/{s['id']}/drills", json={"items": [{"seq": 2, "mark": "later"}]})
    assert r.status_code == 422
