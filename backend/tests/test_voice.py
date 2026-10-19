"""Voice (docs/04-APP-FLOW.md §5): the STT token and TTS stream proxy ElevenLabs with the key kept on the
server, voices come from configuration, and both routes sit behind the access cookie. Every ElevenLabs call
goes to an httpx MockTransport; nothing reaches the network.
"""

import json
from types import SimpleNamespace

import httpx
import pytest

from vik.areopagus import registry
from vik.config import get_settings
from vik.pitch import voice

KEY = "xi-test-key-never-in-a-response"
AUDIO = b"ID3\x04fake-mp3-frames" * 64


@pytest.fixture
def eleven(monkeypatch):
    """Records each ElevenLabs request; `eleven.reply` picks the response."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", KEY)
    monkeypatch.delenv("VIK_VOICE_ID", raising=False)
    get_settings.cache_clear()
    state = SimpleNamespace(seen=[], reply=None)

    def handler(req: httpx.Request) -> httpx.Response:
        state.seen.append(req)
        return state.reply(req)

    def ok(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/single-use-token/realtime_scribe":
            return httpx.Response(200, json={"token": "sutkn_123"})
        return httpx.Response(200, content=AUDIO, headers={"content-type": "audio/mpeg"})

    state.reply = ok
    voice.set_transport(httpx.MockTransport(handler))
    yield state
    voice.set_transport(None)
    monkeypatch.undo()
    get_settings.cache_clear()


# ---------------------------------------------------------------- configuration (no database)


def test_every_builtin_investor_has_its_own_valid_voice():
    ids = {pid: p.voice_id for pid, p in registry.builtins().items()}
    assert all(v and voice.VOICE_ID.fullmatch(v) for v in ids.values()), ids
    assert len(set(ids.values())) == len(ids)  # nobody shares a voice
    assert voice.DEFAULT_VIK_VOICE not in ids.values()  # Vik's default is hers alone


def test_templates_have_their_own_archetype_voices():
    builtin = {p.voice_id for p in registry.builtins().values()}
    tvoices = {t.id: t.voice_id for t in registry.templates()}
    assert all(v and v in voice.PREMADE for v in tvoices.values()), tvoices
    assert len(set(tvoices.values())) == len(tvoices)
    assert not builtin & set(tvoices.values()) and voice.DEFAULT_VIK_VOICE not in tvoices.values()
    for t in registry.templates():
        assert voice.ARCHETYPE_VOICES[t.archetype][0] == t.voice_id, t.id


def test_the_casting_list_only_names_valid_premade_voices():
    for arch, vs in voice.ARCHETYPE_VOICES.items():
        assert vs and len(set(vs)) == len(vs), arch
        assert all(v in voice.PREMADE and voice.VOICE_ID.fullmatch(v) for v in vs), arch
    for p in registry.builtins().values():
        assert voice.ARCHETYPE_VOICES[p.archetype][0] == p.voice_id, p.id


def _custom(pid: str, archetype: str = "custom", voice_id: str | None = None):
    base = registry.builtins()["aristotle"]
    return base.model_copy(update={"id": pid, "archetype": archetype, "voice_id": voice_id, "builtin": False})


def test_cast_gives_every_seat_its_own_voice():
    b = registry.builtins()
    panel = [b["aristotle"], b["socrates"], b["thales"], b["plato"], b["xenophon"]]
    out = voice.cast(panel)
    assert out["vik"] == voice.DEFAULT_VIK_VOICE
    assert {pid: out[pid] for pid in b} == {pid: p.voice_id for pid, p in b.items()}
    assert len(set(out.values())) == len(out)


def test_cast_never_lets_two_investors_share_a_voice():
    b = registry.builtins()
    twins = [_custom("skeptic-a", "skeptical_ic_partner"), _custom("skeptic-b", "skeptical_ic_partner")]
    # A custom investor copying Socrates' voice gives way to him, whatever the seat order.
    copycat = _custom("copycat", voice_id=b["socrates"].voice_id)
    out = voice.cast([*twins, copycat, b["socrates"], _custom("blank")])
    assert out["socrates"] == b["socrates"].voice_id
    assert len(set(out.values())) == len(out)
    # The twins sound like their archetype (its next-best voices, Socrates having the first).
    assert {out["skeptic-a"], out["skeptic-b"]} <= set(voice.ARCHETYPE_VOICES["skeptical_ic_partner"])
    assert all(v in voice.PREMADE for v in out.values())
    # Same investor, same panel → same voices next time.
    assert voice.cast([*twins, copycat, b["socrates"], _custom("blank")]) == out


def test_cast_keeps_viks_configured_voice_to_herself(monkeypatch):
    monkeypatch.setenv("VIK_VOICE_ID", registry.builtins()["aristotle"].voice_id)
    get_settings.cache_clear()
    try:
        out = voice.cast([registry.builtins()["aristotle"]])
        assert out["vik"] == registry.builtins()["aristotle"].voice_id
        assert (
            out["aristotle"] != out["vik"] and out["aristotle"] in voice.ARCHETYPE_VOICES["lead_seed_partner"]
        )
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


async def test_voice_for_vik_uses_the_configured_voice_then_a_premade_one(monkeypatch):
    monkeypatch.delenv("VIK_VOICE_ID", raising=False)
    get_settings.cache_clear()
    assert await voice.voice_for("vik") == voice.DEFAULT_VIK_VOICE
    assert await voice.voice_for(None) == voice.DEFAULT_VIK_VOICE
    monkeypatch.setenv("VIK_VOICE_ID", "abcdefghij1234567890")
    get_settings.cache_clear()
    assert await voice.voice_for("vik") == "abcdefghij1234567890"
    get_settings.cache_clear()


async def test_voice_for_an_investor_uses_the_persona_then_the_archetype(monkeypatch):
    aristotle = registry.builtins()["aristotle"]
    assert await voice.voice_for("aristotle") == aristotle.voice_id

    async def no_one(pid):
        return None

    async def voiceless(pid):
        return aristotle.model_copy(update={"voice_id": None, "archetype": "family_office"})

    monkeypatch.setattr(registry, "get", no_one)
    assert await voice.voice_for("deleted-investor") == voice.DEFAULT_PANEL_VOICE
    monkeypatch.setattr(registry, "get", voiceless)
    assert await voice.voice_for("custom-investor") == voice.ARCHETYPE_VOICES["family_office"][0]


# ---------------------------------------------------------------- routes

db = pytest.mark.db


async def _login(api_client) -> None:
    if (await api_client.get("/auth/session")).json().get("ok"):
        return
    r = await api_client.post("/auth/access", json={"code": get_settings().access_code})
    assert r.status_code == 200, r.text


@db
async def test_voice_routes_need_the_access_cookie(api_client, eleven):
    cookies = dict(api_client.cookies)
    api_client.cookies.clear()
    try:
        assert (await api_client.post("/voice/stt-token")).status_code == 401
        assert (await api_client.get("/voice/tts", params={"text": "Hello"})).status_code == 401
    finally:
        api_client.cookies.update(cookies)
    assert not eleven.seen


@db
async def test_stt_token_is_single_use_and_keeps_the_key_on_the_server(api_client, eleven):
    await _login(api_client)
    r = await api_client.post("/voice/stt-token")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "token": "sutkn_123",
        "url": "wss://api.elevenlabs.io/v1/speech-to-text/realtime",
        "model_id": "scribe_v2_realtime",
        "sample_rate": 16000,
    }
    assert KEY not in r.text
    (req,) = eleven.seen
    assert req.method == "POST" and req.url.path == "/v1/single-use-token/realtime_scribe"
    assert req.headers["xi-api-key"] == KEY


@db
async def test_tts_streams_mp3_in_the_speakers_voice(api_client, eleven):
    await _login(api_client)
    r = await api_client.get("/voice/tts", params={"text": "  What is your churn?  ", "speaker": "socrates"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "audio/mpeg" and r.content == AUDIO
    (req,) = eleven.seen
    socrates = registry.builtins()["socrates"].voice_id
    assert req.url.path == f"/v1/text-to-speech/{socrates}/stream"
    assert req.url.params["output_format"] == "mp3_44100_128"
    assert req.headers["xi-api-key"] == KEY
    assert json.loads(req.content) == {"text": "What is your churn?", "model_id": "eleven_flash_v2_5"}


@db
async def test_tts_voice_id_wins_and_no_speaker_means_vik(api_client, eleven):
    await _login(api_client)
    assert (
        await api_client.get("/voice/tts", params={"text": "Hi", "voice_id": "abcdefghij1234567890"})
    ).status_code == 200
    assert (await api_client.get("/voice/tts", params={"text": "Hi"})).status_code == 200
    assert [r.url.path for r in eleven.seen] == [
        "/v1/text-to-speech/abcdefghij1234567890/stream",
        f"/v1/text-to-speech/{voice.DEFAULT_VIK_VOICE}/stream",
    ]


@db
async def test_tts_refuses_bad_input_before_calling_elevenlabs(api_client, eleven):
    await _login(api_client)
    for params in (
        {"text": ""},
        {"text": "   "},
        {"text": "x" * (voice.TTS_MAX_CHARS + 1)},
        {"text": "Hi", "voice_id": "../../v1/user"},
    ):
        assert (await api_client.get("/voice/tts", params=params)).status_code == 422, params
    assert not eleven.seen


@db
async def test_upstream_failures_are_502_or_503_without_the_key(api_client, eleven):
    await _login(api_client)
    eleven.reply = lambda req: httpx.Response(401, json={"detail": {"status": "missing_permissions"}})
    for r in (
        await api_client.post("/voice/stt-token"),
        await api_client.get("/voice/tts", params={"text": "Hi"}),
    ):
        assert r.status_code == 502 and KEY not in r.text, r.text
    eleven.reply = lambda req: httpx.Response(429, json={"detail": "busy"})
    assert (await api_client.get("/voice/tts", params={"text": "Hi"})).status_code == 503

    def down(req):
        raise httpx.ConnectError("no route")

    eleven.reply = down
    assert (await api_client.post("/voice/stt-token")).status_code == 502
    assert (await api_client.get("/voice/tts", params={"text": "Hi"})).status_code == 502


@db
async def test_voice_is_off_without_a_key(api_client, monkeypatch):
    await _login(api_client)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    get_settings.cache_clear()
    try:
        assert (await api_client.post("/voice/stt-token")).status_code == 503
        assert (await api_client.get("/voice/tts", params={"text": "Hi"})).status_code == 503
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
