"""Settings from the environment (see .env.example at the repo root)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql://vicky:vicky@localhost:5432/vicky"
    redis_url: str = "redis://localhost:6379"
    jobs_mode: Literal["inline", "worker"] = "inline"
    web_origin: str = "http://localhost:3000"

    access_code: str = "vicky-demo"
    cookie_secret: str = "dev-only-change-me"
    cookie_name: str = "vicky_access"
    cookie_max_age_s: int = 60 * 60 * 24 * 30
    cookie_secure: bool = False

    anthropic_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    # "auto" uses Claude when a key is set and the offline agents otherwise.
    llm_mode: Literal["auto", "live", "offline"] = "auto"
    llm_server_fallbacks: bool = True
    daily_usd_budget: float = 5.0

    model_deep: str = "claude-opus-5-5"
    model_fast: str = "claude-sonnet-5-5"
    model_tiny: str = "claude-haiku-5-5"

    rate_limit_per_min: int = 240
    access_attempts_per_min: int = 5
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
    chair_timeout_s: float = 1.5
    interrupt_veto_timeout_s: float = 1.0

    vicky_voice_id: str | None = Field(default=None)


@lru_cache
def get_settings() -> Settings:
    return Settings()
