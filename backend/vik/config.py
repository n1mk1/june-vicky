"""Settings from the environment (see .env.example at the repo root)."""

from contextlib import suppress
from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql://vik:vik@localhost:5432/vik"
    redis_url: str = "redis://localhost:6379"
    jobs_mode: Literal["inline", "worker"] = "inline"
    web_origin: str = "http://localhost:3000"

    access_code: str = "vik-demo"
    cookie_secret: str = "dev-only-change-me"
    cookie_name: str = "vik_access"
    cookie_max_age_s: int = 60 * 60 * 24 * 30
    cookie_secure: bool = False

    # Gemini API key (Google AI Studio). GOOGLE_API_KEY is read too, as the Google SDKs do (see `gemini_key`).
    gemini_api_key: str | None = None
    google_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    # "auto" uses Gemini when a key is set and the offline agents otherwise.
    llm_mode: Literal["auto", "live", "offline"] = "auto"
    # The key's billing tier. "free": a free AI Studio key, whose calls cost nothing (the dollar budget is not
    # applied) but are rate limited per model, so calls are paced (`gemini_rpm`) and a 429 pauses that model.
    # "paid": calls are priced at list rates against DAILY_USD_BUDGET.
    gemini_tier: Literal["free", "paid"] = "free"
    daily_usd_budget: float = 5.0
    # Requests per minute per model on the free tier (0 = no pacing). Free quotas are per project and model.
    gemini_rpm: int = 10
    # How long a model rests after the API answers 429 (seconds), when the error doesn't say.
    gemini_cooldown_s: float = 60.0

    # Defaults are all on the free tier, spread over three models so each has its own quota. On a paid key,
    # MODEL_VIK / MODEL_DEEP = gemini-4-argon give the chair and document facts the flagship model.
    model_deep: str = "gemini-3.8-flash"
    model_fast: str = "gemini-3.8-flash"
    model_tiny: str = "gemini-3.5-flash-lite"
    # The court's agents: Vik orchestrates (chair, line review, scoring, knowledge checks); the investors
    # research the company and question the founder. Both run at low effort (llm/client.py ROUTES).
    model_vik: str = "gemini-3.8-flash"
    model_investor: str = "gemini-3.6-flash"

    rate_limit_per_min: int = 240
    access_attempts_per_min: int = 5
    # Wrong access codes per minute across every address before /auth/access answers 429 for everyone.
    access_failures_per_min: int = 60
    # Peers whose X-Forwarded-For is believed: Render's edge proxy and private network, docker, localhost.
    # The client is the rightmost forwarded address outside these ranges. Empty = never read the header.
    trusted_proxy_cidrs: str = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,::1/128,fc00::/7"
    # Largest request body; bigger ones get 413 before they are read. Unset = a full-size knowledge-base
    # file plus multipart framing (see max_request_bytes).
    request_max_bytes: int | None = None
    upload_max_bytes: int = 10 * 1024 * 1024
    # Knowledge base imports: per file (a zip counts as one file) and the most a zip may expand to.
    kb_upload_max_bytes: int = 50 * 1024 * 1024
    kb_unzip_max_bytes: int = 200 * 1024 * 1024
    # OCR: tesseract binary (blank = on PATH) and the most pages one PDF may send through it.
    tesseract_cmd: str | None = None
    ocr_max_pages: int = 80
    # Retrieval over the knowledge base (docs/08-RAG.md). Without a Voyage key search is BM25 only.
    voyage_api_key: str | None = None
    voyage_base_url: str = "https://api.voyageai.com/v1"
    embed_model: str = "voyage-4"
    rerank_model: str = "rerank-2.5"
    rerank_model_fast: str = "rerank-2.5-lite"
    rag_conf_min: float = 0.55
    rag_full_max_tokens: int = 300_000
    rag_reuse_embeddings: bool = True
    # Vik's pick of the next speaker; thinking can't be turned off, so this allows a short think.
    chair_timeout_s: float = 6.0
    interrupt_veto_timeout_s: float = 1.0

    # ElevenLabs voice for Vik (unset = a premade voice); investors use their persona's voice_id.
    vik_voice_id: str | None = Field(default=None)
    elevenlabs_tts_model: str = "eleven_flash_v2_5"

    def gemini_key(self) -> str | None:
        return self.gemini_api_key or self.google_api_key or None

    def max_request_bytes(self) -> int:
        if self.request_max_bytes:
            return self.request_max_bytes
        return max(self.kb_upload_max_bytes, self.upload_max_bytes) + 4 * 1024 * 1024


def parse_cidrs(cidrs: str) -> tuple[IPv4Network | IPv6Network, ...]:
    """`"10.0.0.0/8, ::1"` → networks; entries that aren't an address or a network are ignored."""
    out = []
    for raw in cidrs.split(","):
        with suppress(ValueError):
            if raw.strip():
                out.append(ip_network(raw.strip(), strict=False))
    return tuple(out)


@lru_cache
def get_settings() -> Settings:
    return Settings()
