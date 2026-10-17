"""Persona registry: built-ins and builder templates from the repo, custom VCs from Postgres."""

import re
import uuid
from functools import lru_cache
from pathlib import Path

import yaml

from vicky import db
from vicky.areopagus.schema import VCPersona

HERE = Path(__file__).resolve().parent
DEFAULT_PANEL = ["james", "alex", "mark"]
MAX_PANEL = 5


class PersonaError(Exception):
    pass


@lru_cache
def builtins() -> dict[str, VCPersona]:
    out = {}
    for path in sorted((HERE / "builtin").glob("*.yaml")):
        p = VCPersona.model_validate({**yaml.safe_load(path.read_text(encoding="utf-8")), "builtin": True})
        out[p.id] = p
    return out


@lru_cache
def templates() -> list[VCPersona]:
    raw = yaml.safe_load((HERE / "templates.yaml").read_text(encoding="utf-8")) or {}
    return [VCPersona.model_validate({**t, "builtin": False}) for t in raw.get("templates", [])]


def _from_row(r: dict) -> VCPersona:
    return VCPersona.model_validate({**r["spec"], "id": r["slug"], "builtin": False, "version": r["version"],
                                     "base_archetype": r["base_archetype"]})


async def custom() -> list[VCPersona]:
    rows = await db.fetch("select * from vc_personas order by created_at")
    return [_from_row(r) for r in rows]


async def all_personas() -> list[VCPersona]:
    return [*builtins().values(), *await custom()]


async def get(pid: str) -> VCPersona | None:
    if pid in builtins():
        return builtins()[pid]
    r = await db.fetchrow("select * from vc_personas where slug = $1", pid)
    return _from_row(r) if r else None


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "vc"
    return f"{base}-{uuid.uuid4().hex[:6]}"


async def create(spec: dict, base_archetype: str | None = None) -> VCPersona:
    data = {k: v for k, v in spec.items() if k not in ("id", "builtin", "version")}
    slug = _slug(str(data.get("name") or "vc"))
    p = VCPersona.model_validate({**data, "id": slug, "builtin": False,
                                  "base_archetype": base_archetype or data.get("base_archetype")})
    await db.execute("insert into vc_personas (slug, spec, base_archetype) values ($1, $2, $3)",
                     slug, p.model_dump(mode="json"), p.base_archetype)
    return p


async def update(pid: str, spec: dict) -> VCPersona:
    if pid in builtins():
        raise PersonaError("Built-in investors are read-only; fork one to edit it.")
    r = await db.fetchrow("select * from vc_personas where slug = $1", pid)
    if r is None:
        raise KeyError(pid)
    data = {**r["spec"], **{k: v for k, v in spec.items() if k not in ("id", "builtin", "version")}}
    p = VCPersona.model_validate({**data, "id": pid, "builtin": False, "version": r["version"] + 1})
    await db.execute("update vc_personas set spec = $2, version = version + 1 where slug = $1", pid, p.model_dump(mode="json"))
    return p


async def delete(pid: str) -> None:
    if pid in builtins():
        raise PersonaError("Built-in investors can't be deleted.")
    res = await db.execute("delete from vc_personas where slug = $1", pid)
    if res.endswith(" 0"):
        raise KeyError(pid)


async def fork(pid: str) -> VCPersona:
    src = await get(pid) or next((t for t in templates() if t.id == pid), None)
    if src is None:
        raise KeyError(pid)
    data = src.model_dump(mode="json")
    data["name"] = f"{src.name} (fork)"
    return await create(data, base_archetype=src.archetype if src.builtin else src.base_archetype or src.archetype)


async def panel(ids: list[str] | None, strict: bool = True) -> list[VCPersona]:
    """The investors for these ids. Not strict: skip ids that no longer exist (a custom investor
    deleted after a session seated them), so the session can still be viewed and ended."""
    ids = [i for i in (ids or DEFAULT_PANEL) if i][:MAX_PANEL]
    out = []
    for i in dict.fromkeys(ids):
        p = await get(i)
        if p is None:
            if not strict:
                continue
            raise PersonaError(f"Unknown investor {i!r}")
        out.append(p)
    if not out and strict:
        raise PersonaError("Pick at least one investor")
    return out
