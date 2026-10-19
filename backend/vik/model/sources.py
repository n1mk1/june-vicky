"""Benchmark library (data/sources.yaml), glossary and Appendix D question anchors.

Benchmarks exist only through `cite_source`; when nothing matches the company's model and
stage, callers say no sourced benchmark exists instead of inventing one.
"""

from functools import lru_cache
from typing import Any

import yaml

from vik import DATA_DIR


def _load_list(name: str, key: str) -> list[dict]:
    path = DATA_DIR / name
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if isinstance(raw, dict):
        raw = raw.get(key, [])
    return [r for r in raw if isinstance(r, dict)]


@lru_cache
def sources() -> list[dict]:
    return _load_list("sources.yaml", "sources")


@lru_cache
def glossary() -> list[dict]:
    return _load_list("glossary.yaml", "terms")


@lru_cache
def questions() -> list[dict]:
    return _load_list("questions.yaml", "questions")


def source_by_id(source_id: str) -> dict | None:
    return next((s for s in sources() if s.get("id") == source_id), None)


def _matches(values: list[str] | None, wanted: str | None) -> bool:
    vals = [str(v) for v in (values or [])]
    return not vals or "any" in vals or wanted is None or wanted in vals


def cite_source(topic: str, profile: dict[str, Any] | None = None, verified_only: bool = False) -> list[dict]:
    """Sources whose topic matches, filtered by the company's business model and stage."""
    profile = profile or {}
    t = topic.lower().strip()
    out = []
    for s in sources():
        topics = [str(x).lower() for x in s.get("topic") or []]
        if t not in topics and not any(t in x or x in t for x in topics):
            continue
        if not _matches(s.get("business_model"), profile.get("business_model")):
            continue
        if not _matches(s.get("stage"), profile.get("stage")):
            continue
        if verified_only and not s.get("verified"):
            continue
        out.append(s)
    out.sort(key=lambda s: (not s.get("verified"), str(s.get("id"))))
    return out


def define_term(term: str) -> dict | None:
    t = term.lower().strip()
    for g in glossary():
        names = [str(g.get("term", "")).lower()] + [str(a).lower() for a in g.get("aliases") or []]
        if t in names:
            return g
    for g in glossary():
        if t in str(g.get("term", "")).lower():
            return g
    return None


def fill(text: str, profile: dict[str, Any] | None) -> str:
    profile = profile or {}
    return (text or "").replace("{company}", profile.get("name") or "the company")
