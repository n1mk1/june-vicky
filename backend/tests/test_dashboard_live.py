"""Live dashboards over the API (FR-12, FR-16): versioning, layout, time range, chat and realtime fan-out."""

import asyncio
import json

import pytest

from tests.helpers import load_and_confirm
from vicky import realtime

pytestmark = pytest.mark.db


async def _active(api_client) -> dict:
    await api_client.post("/auth/access", json={"code": "vicky-demo"})
    r = await api_client.get("/dashboards/active")
    if r.status_code == 404:
        await load_and_confirm(api_client, "tidewell")
        r = await api_client.get("/dashboards/active")
    assert r.status_code == 200, r.text
    return r.json()


class _FakeSocket:
    """Stands in for a browser tab's WebSocket on the hub."""

    def __init__(self) -> None:
        self.got: list[dict] = []

    async def send_text(self, data: str) -> None:
        self.got.append(json.loads(data))


async def _wait_for(sock: _FakeSocket, n: int, seconds: float = 3.0) -> list[dict]:
    for _ in range(int(seconds / 0.05)):
        if len(sock.got) >= n:
            break
        await asyncio.sleep(0.05)
    return sock.got


async def test_layout_versioning_rejects_stale_writes(api_client):
    d = await _active(api_client)
    layout = [{**li, "x": 0, "w": 12} for li in d["layout"]]
    ok = await api_client.patch(
        f"/dashboards/{d['id']}/layout", json={"layout": layout, "version": d["version"]}
    )
    assert ok.status_code == 200 and ok.json()["version"] == d["version"] + 1
    assert all(li["w"] == 12 for li in ok.json()["layout"])
    stale = await api_client.patch(
        f"/dashboards/{d['id']}/layout", json={"layout": d["layout"], "version": d["version"]}
    )
    assert stale.status_code == 409 and "changed" in stale.json()["detail"]
    bad = await api_client.patch(
        f"/dashboards/{d['id']}/layout", json={"layout": [{"x": 1}], "version": ok.json()["version"]}
    )
    assert bad.status_code == 422


async def test_time_range_is_validated_resolved_and_versioned(api_client):
    d = await _active(api_client)
    r = await api_client.patch(
        f"/dashboards/{d['id']}/time-range", json={"time_range": {"last_months": 6}, "version": d["version"]}
    )
    assert r.status_code == 200
    tr = r.json()["time_range"]
    assert tr["last_months"] == 6 and tr["from"] < tr["to"] and tr["label"].startswith("Last 6 months")
    y0, m0 = map(int, tr["from"].split("-"))
    y1, m1 = map(int, tr["to"].split("-"))
    assert (y1 * 12 + m1) - (y0 * 12 + m0) == 5
    assert r.json()["version"] == d["version"] + 1
    assert (
        await api_client.patch(
            f"/dashboards/{d['id']}/time-range",
            json={"time_range": {"last_months": 6}, "version": d["version"]},
        )
    ).status_code == 409
    for bad in (
        {"last_months": 0},
        {"last_months": "x"},
        {"from": "2026-13", "to": "2026-01"},
        {"from": "2026-01"},
    ):
        assert (
            await api_client.patch(f"/dashboards/{d['id']}/time-range", json={"time_range": bad})
        ).status_code == 422
    cleared = (await api_client.patch(f"/dashboards/{d['id']}/time-range", json={"time_range": None})).json()
    assert cleared["time_range"] is None


async def test_fr12_chat_adds_a_widget_once_and_zooms(api_client):
    d = await _active(api_client)
    r = (
        await api_client.post(
            f"/dashboards/{d['id']}/chat", json={"text": "burn excluding SR&ED as % of revenue by quarter"}
        )
    ).json()
    assert r["kind"] == "widget_added" and r["widget_id"], r
    w = next(w for w in r["dashboard"]["widgets"] if w["id"] == r["widget_id"])
    assert w["created_by"] == "vicky" and w["status"] == "ok" and w["spec"]["group_by"] == "quarter"
    assert (
        w["option"]["dataset"]["source"][1][1] == w["evaluated"]["series"][0]["points"][0]["value"]
    )  # code-computed
    assert any(li["widget_id"] == w["id"] for li in r["dashboard"]["layout"])
    assert not any(ch.isdigit() for ch in r["reply"].replace("&", ""))  # replies carry no figures

    again = (
        await api_client.post(
            f"/dashboards/{d['id']}/chat", json={"text": "burn ex credits as % of revenue by quarter"}
        )
    ).json()
    assert again["kind"] == "exists" and again["widget_id"] == w["id"] and again["dashboard"] is None

    z = (
        await api_client.post(f"/dashboards/{d['id']}/chat", json={"text": "zoom to the last 6 months"})
    ).json()
    assert z["kind"] == "time_range" and z["time_range"]["last_months"] == 6
    assert (await api_client.get(f"/dashboards/{d['id']}")).json()["time_range"]["last_months"] == 6
    out = (await api_client.post(f"/dashboards/{d['id']}/chat", json={"text": "reset zoom"})).json()
    assert out["kind"] == "time_range" and out["time_range"] is None


async def test_chat_missing_data_answers_with_the_reason_and_adds_nothing(api_client):
    d = await _active(api_client)
    before = len(d["widgets"])
    r = (await api_client.post(f"/dashboards/{d['id']}/chat", json={"text": "cash balance by month"})).json()
    assert r["kind"] == "missing" and r["missing"]["reason"] and r["reply"] == r["missing"]["reason"]
    assert r["widget_id"] is None and r["dashboard"] is None
    assert len((await api_client.get(f"/dashboards/{d['id']}")).json()["widgets"]) == before
    # Questions about the data are answered in place, with every number footnoted; nothing is added.
    q = (await api_client.post(f"/dashboards/{d['id']}/chat", json={"text": "why is burn falling?"})).json()
    assert q["kind"] == "answer" and q["dashboard"] is None and q["citations"]
    assert len((await api_client.get(f"/dashboards/{d['id']}")).json()["widgets"]) == before
    v = (
        await api_client.post(
            f"/dashboards/{d['id']}/chat", json={"text": "what valuation should we raise at?"}
        )
    ).json()
    assert v["kind"] == "answer" and "won't put a number" in v["reply"]
    assert (await api_client.post(f"/dashboards/{d['id']}/chat", json={"text": ""})).status_code == 422


async def test_remove_bumps_the_version(api_client):
    d = await _active(api_client)
    custom = next(w for w in d["widgets"] if w["created_by"] != "system")
    r = await api_client.delete(f"/dashboards/{d['id']}/widgets/{custom['id']}")
    assert r.status_code == 200 and r.json()["version"] == d["version"] + 1
    assert all(w["id"] != custom["id"] for w in r.json()["widgets"])
    assert all(li["widget_id"] != custom["id"] for li in r.json()["layout"])
    assert (await api_client.delete(f"/dashboards/{d['id']}/widgets/{custom['id']}")).status_code == 404


async def test_fr16_changes_fan_out_to_every_tab_in_version_order(api_client):
    d = await _active(api_client)
    channel = f"dashboard:{d['id']}"
    tab_a, tab_b = _FakeSocket(), _FakeSocket()
    realtime.hub.add(channel, tab_a)  # type: ignore[arg-type]
    realtime.hub.add(channel, tab_b)  # type: ignore[arg-type]
    try:
        added = (
            await api_client.post(
                f"/dashboards/{d['id']}/chat", json={"text": "R&D as % of revenue by quarter"}
            )
        ).json()
        assert added["kind"] == "widget_added"
        dash = added["dashboard"]
        moved = [
            {**li, "y": li["y"] + 1} if li["widget_id"] == added["widget_id"] else li for li in dash["layout"]
        ]
        await api_client.patch(
            f"/dashboards/{d['id']}/layout", json={"layout": moved, "version": dash["version"]}
        )
        for tab in (tab_a, tab_b):
            got = await _wait_for(tab, 2)
            assert [e["type"] for e in got[:2]] == ["widget.diff", "layout.diff"]
            assert got[0]["payload"]["op"] == "add" and got[0]["payload"]["by"] == "vicky"
            assert got[0]["channel"] == channel and got[0]["version"] < got[1]["version"]  # dedupe key
            assert got[0]["payload"]["version"] < got[1]["payload"]["version"]  # dashboard version
    finally:
        realtime.hub.remove(tab_a)  # type: ignore[arg-type]
        realtime.hub.remove(tab_b)  # type: ignore[arg-type]
    assert channel not in realtime.hub.sockets  # no empty channel entries left behind


async def test_realtime_token_is_gated_and_signed(api_client):
    await _active(api_client)
    tok = (await api_client.get("/realtime/token")).json()["token"]
    assert tok and realtime._ws_signer().unsign(tok, max_age=60) == b"ws"
