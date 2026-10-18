"""Voyage AI embeddings and reranking over HTTP (docs/08-RAG.md). Without `VOYAGE_API_KEY` both are off and
search runs on BM25 alone; a failed call raises `VoyageError`, which callers treat as "no vectors this time".

API: POST /v1/embeddings {input, model, input_type, output_dimension} → {data: [{embedding, index}], usage};
POST /v1/rerank {query, documents, model, top_k} → {data: [{index, relevance_score}], usage}.
"""

import logging
from typing import Literal

import httpx

from vicky.config import get_settings

log = logging.getLogger(__name__)
DIMS = 1024
BATCH = 128  # inputs per embeddings request (the API allows 1000)
BATCH_CHARS = 400_000  # ~100K tokens, well under the 320K-token request limit
TIMEOUT_S = 30.0

_transport: httpx.AsyncBaseTransport | None = None  # tests inject a MockTransport


class VoyageError(Exception):
    pass


def enabled() -> bool:
    return bool(get_settings().voyage_api_key) or _transport is not None


def set_transport(t: httpx.AsyncBaseTransport | None) -> None:
    global _transport
    _transport = t


def _client(timeout: float) -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(
        base_url=s.voyage_base_url,
        timeout=timeout,
        transport=_transport,
        headers={"Authorization": f"Bearer {s.voyage_api_key or 'test'}"},
    )


async def _post(path: str, body: dict, timeout_s: float) -> dict:
    try:
        async with _client(timeout_s) as c:
            r = await c.post(path, json=body)
    except httpx.HTTPError as e:
        raise VoyageError(f"voyage {path}: {e}") from e
    if r.status_code != 200:
        raise VoyageError(f"voyage {path}: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


async def embed(
    texts: list[str],
    input_type: Literal["query", "document"],
    *,
    model: str | None = None,
    timeout_s: float = TIMEOUT_S,
) -> list[list[float]]:
    """One vector per text, in order."""
    if not texts:
        return []
    model = model or get_settings().embed_model
    out: list[list[float]] = []
    batch: list[str] = []
    size = 0

    async def send() -> None:
        data = await _post(
            "/embeddings",
            {"input": batch, "model": model, "input_type": input_type, "output_dimension": DIMS},
            timeout_s,
        )
        vecs = sorted(data.get("data") or [], key=lambda d: d["index"])
        if len(vecs) != len(batch) or any(len(v["embedding"]) != DIMS for v in vecs):
            raise VoyageError("voyage /embeddings: wrong number or size of vectors")
        out.extend(v["embedding"] for v in vecs)

    for t in texts:
        if batch and (len(batch) >= BATCH or size + len(t) > BATCH_CHARS):
            await send()
            batch, size = [], 0
        batch.append(t[:32_000])
        size += len(t)
    if batch:
        await send()
    return out


async def rerank(
    query: str, documents: list[str], *, model: str, top_k: int | None = None, timeout_s: float = 10.0
) -> list[tuple[int, float]]:
    """(document index, relevance 0–1), best first."""
    if not documents:
        return []
    body: dict = {"query": query[:8000], "documents": [d[:16_000] for d in documents], "model": model}
    if top_k:
        body["top_k"] = top_k
    data = await _post("/rerank", body, timeout_s)
    return [(int(d["index"]), float(d["relevance_score"])) for d in data.get("data") or []]


def to_pg(vec: list[float]) -> str:
    """A vector as pgvector text input ('[0.1,0.2,…]'), cast to halfvec in SQL."""
    return "[" + ",".join(f"{x:.6g}" for x in vec) + "]"


def from_pg(text: str) -> list[float]:
    return [float(x) for x in text.strip("[]").split(",") if x]
