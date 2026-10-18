"""ElevenLabs voice for the simulation (docs/02-TRD.md §2, docs/04-APP-FLOW.md §5).

STT: the browser streams the mic straight to ElevenLabs realtime Scribe with a single-use token from
`POST /voice/stt-token` (POST /v1/single-use-token/realtime_scribe → {token}; 15 min, consumed on first use).
TTS: `GET /voice/tts` streams audio/mpeg from POST /v1/text-to-speech/{voice_id}/stream.
The API key stays on the server. Voices are configured, never listed at runtime: a restricted key may not
have voices_read. Vicky speaks with VICKY_VOICE_ID, each investor with its persona's `voice_id` (cast to fit its
archetype); a pitch casts its panel once (`cast`) so no two people in the room share a voice.
"""

import hashlib
import logging
import re

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from vicky.areopagus import registry
from vicky.areopagus.schema import VCPersona
from vicky.config import get_settings

log = logging.getLogger(__name__)

API_BASE = "https://api.elevenlabs.io"
STT_URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"
STT_MODEL = "scribe_v2_realtime"
STT_SAMPLE_RATE = 16_000
# Premade voices every account can use: Vicky's default, and the panel's when an investor has none.
DEFAULT_VICKY_VOICE = "21m00Tcm4TlvDq8ikWAM"
DEFAULT_PANEL_VOICE = "CwhRBWXzGAHq8TQ4Fs17"

# The premade voices the panel is cast from (ElevenLabs' default library; no voices_read needed to use them).
PREMADE = {
    "21m00Tcm4TlvDq8ikWAM": "Rachel: calm, clear narrator (F)",
    "JBFqnCBsd6RMkjVDRZzb": "George: warm, measured British (M)",
    "onwK4e9ZLuTAKqWW03F9": "Daniel: authoritative British broadcaster (M)",
    "2EiwWnXFnvU5JabPnv8n": "Clyde: gravelly, intense (M)",
    "iP95p4xoKVk53GoZ742B": "Chris: casual, down-to-earth American (M)",
    "cjVigY5qzO86Huf0OWal": "Eric: smooth, trustworthy American (M)",
    "XrExE9yKIg1WjnnlVkGX": "Matilda: knowledgeable, professional (F)",
    "pFZP5JQG7iQjIQuC4Bku": "Lily: velvety, composed British (F)",
    "cgSgspJ2msm6clMCkdW9": "Jessica: bright, quick American (F)",
    "SAz9YHcvj6GT2YYXdXww": "River: neutral, even (NB)",
    "CwhRBWXzGAHq8TQ4Fs17": "Roger: laid-back, confident (M)",
    "pqHfZKP75CvOlQylNhV4": "Bill: mature, balanced American (M)",
    "nPczCjzI2devNBz1zQrb": "Brian: deep, resonant American (M)",
    "N2lVS1w4EtoT3dr4eOWO": "Callum: husky, edgy (M)",
    "Xb7hH8MSUJpSbSDYk0k2": "Alice: clear, confident British (F)",
    "FGY2WhTYpPnrIDTdsKH5": "Laura: upbeat, direct American (F)",
    "IKne3meq5aSn9XLyUdCD": "Charlie: energetic Australian (M)",
    "EXAVITQu4vr4xnSDxMaL": "Sarah: mature, reassuring (F)",
    "XB0fDUnXU5powFXDhCwa": "Charlotte: poised, Swedish-accented (F)",
    "TX3LPaxmHKxFdv7VOQHJ": "Liam: energetic, young American (M)",
    "SOYHLrjzK2X1ezoPC6cr": "Harry: fierce, forceful (M)",
    "pNInz6obpgDQGcFmaJgB": "Adam: deep, firm American (M)",
    "bIHbv24MWmeRgasZH58o": "Will: friendly, relaxed (M)",
}
# Who sounds like each archetype, best first. A seat with no voice of its own (or one a panel-mate already has)
# takes the first of these nobody on the panel has, then a voice from the rest of the library.
ARCHETYPE_VOICES: dict[str, list[str]] = {
    "lead_seed_partner": ["JBFqnCBsd6RMkjVDRZzb", "nPczCjzI2devNBz1zQrb", "Xb7hH8MSUJpSbSDYk0k2"],
    "mandate_fund": ["onwK4e9ZLuTAKqWW03F9", "EXAVITQu4vr4xnSDxMaL", "pqHfZKP75CvOlQylNhV4"],
    "skeptical_ic_partner": ["2EiwWnXFnvU5JabPnv8n", "N2lVS1w4EtoT3dr4eOWO", "SOYHLrjzK2X1ezoPC6cr"],
    "angel_operator": ["iP95p4xoKVk53GoZ742B", "FGY2WhTYpPnrIDTdsKH5", "bIHbv24MWmeRgasZH58o"],
    "corporate_strategic_vc": ["cjVigY5qzO86Huf0OWal", "pNInz6obpgDQGcFmaJgB", "XB0fDUnXU5powFXDhCwa"],
    "impact_esg_fund": ["XrExE9yKIg1WjnnlVkGX", "EXAVITQu4vr4xnSDxMaL", "Xb7hH8MSUJpSbSDYk0k2"],
    "family_office": ["pFZP5JQG7iQjIQuC4Bku", "pqHfZKP75CvOlQylNhV4", "XB0fDUnXU5powFXDhCwa"],
    "accelerator_partner": ["cgSgspJ2msm6clMCkdW9", "TX3LPaxmHKxFdv7VOQHJ", "IKne3meq5aSn9XLyUdCD"],
    "revenue_based_lender": ["SAz9YHcvj6GT2YYXdXww", "pqHfZKP75CvOlQylNhV4", "pNInz6obpgDQGcFmaJgB"],
}
CHAIR = "vicky"
TTS_MAX_CHARS = 1200
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
VOICE_ID = re.compile(r"^[A-Za-z0-9]{10,40}$")

_transport: httpx.AsyncBaseTransport | None = None  # tests inject a MockTransport

router = APIRouter(prefix="/voice")


def set_transport(t: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = t


def enabled() -> bool:
    return bool(get_settings().elevenlabs_api_key)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=API_BASE,
        timeout=TIMEOUT,
        transport=_transport,
        headers={"xi-api-key": get_settings().elevenlabs_api_key or ""},
    )


def _require_key() -> None:
    if not enabled():
        raise HTTPException(
            503, "Voice is off: set ELEVENLABS_API_KEY on the API. Type your answers meanwhile."
        )


def _upstream(status: int, what: str) -> HTTPException:
    if status == 429:
        return HTTPException(503, f"ElevenLabs is busy ({what}). Try again in a moment, or type your answer.")
    return HTTPException(502, f"ElevenLabs refused the {what} request (HTTP {status}).")


def stt_config() -> dict:
    """What the browser needs to open realtime Scribe (the token comes separately)."""
    return {"url": STT_URL, "model_id": STT_MODEL, "sample_rate": STT_SAMPLE_RATE}


def chair_voice() -> str:
    return get_settings().vicky_voice_id or DEFAULT_VICKY_VOICE


def _candidates(p: VCPersona) -> list[str]:
    """The voices that fit this investor, best first: its own, its archetype's, then the whole library in an
    order fixed by its id (so a custom investor keeps sounding the same from one session to the next)."""
    fit = [*([p.voice_id] if p.voice_id else []), *ARCHETYPE_VOICES.get(p.archetype, [])]
    fit += ARCHETYPE_VOICES.get(p.base_archetype or "", [])
    pool = sorted(PREMADE, key=lambda v: hashlib.sha1(f"{p.id}:{v}".encode()).hexdigest())
    return list(dict.fromkeys([*fit, *pool]))


def cast(panel: list[VCPersona]) -> dict[str, str]:
    """Speaker id → voice for one sitting: Vicky's, then each investor's best fit that nobody else in the room
    has. Built-ins, then investors with a voice of their own, choose first, so a copied voice stays with its owner."""
    out = {CHAIR: chair_voice()}
    taken = {out[CHAIR]}
    for p in sorted(panel, key=lambda p: (p.voice_id is None, not p.builtin)):
        v = next((v for v in _candidates(p) if v not in taken), DEFAULT_PANEL_VOICE)
        out[p.id] = v
        taken.add(v)
    return out


async def voice_for(speaker: str | None) -> str:
    """Vicky (or no speaker) → VICKY_VOICE_ID; an investor → its own voice, else its archetype's (outside a
    sitting, so a panel-mate may share it: the pitch's `voices` cast is what the room plays)."""
    if not speaker or speaker == CHAIR:
        return chair_voice()
    persona = await registry.get(speaker)
    if persona is None:
        return DEFAULT_PANEL_VOICE
    return next((v for v in _candidates(persona) if v != chair_voice()), DEFAULT_PANEL_VOICE)


@router.post("/stt-token")
async def stt_token() -> dict:
    _require_key()
    try:
        async with _client() as c:
            r = await c.post("/v1/single-use-token/realtime_scribe")
    except httpx.HTTPError as e:
        log.warning("elevenlabs stt token: %s", e)
        raise HTTPException(502, "ElevenLabs is not reachable for transcription.") from e
    if r.status_code != 200:
        log.warning("elevenlabs stt token: HTTP %s %s", r.status_code, r.text[:200])
        raise _upstream(r.status_code, "transcription token")
    token = (r.json() or {}).get("token")
    if not token:
        raise HTTPException(502, "ElevenLabs sent no transcription token.")
    return {"token": token, **stt_config()}


@router.get("/tts")
async def tts(
    text: str = Query(min_length=1, max_length=TTS_MAX_CHARS),
    voice_id: str | None = Query(default=None, max_length=40),
    speaker: str | None = Query(default=None, max_length=80),
) -> StreamingResponse:
    """Streams the line as MP3. `voice_id` wins; otherwise the voice is `speaker`'s (a persona id or `vicky`)."""
    if not text.strip():
        raise HTTPException(422, "Nothing to say.")
    if voice_id is not None and not VOICE_ID.fullmatch(voice_id):
        raise HTTPException(422, "That is not an ElevenLabs voice id.")
    _require_key()
    vid = voice_id or await voice_for(speaker)
    body = {"text": text.strip(), "model_id": get_settings().elevenlabs_tts_model}

    client = _client()
    try:
        req = client.build_request(
            "POST",
            f"/v1/text-to-speech/{vid}/stream",
            params={"output_format": "mp3_44100_128"},
            json=body,
        )
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        log.warning("elevenlabs tts: %s", e)
        raise HTTPException(502, "ElevenLabs is not reachable for speech.") from e
    if upstream.status_code != 200:
        detail = (await upstream.aread())[:200]
        await upstream.aclose()
        await client.aclose()
        log.warning("elevenlabs tts %s: HTTP %s %s", vid, upstream.status_code, detail)
        raise _upstream(upstream.status_code, "speech")

    async def audio():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(audio(), media_type="audio/mpeg", headers={"cache-control": "no-store"})
