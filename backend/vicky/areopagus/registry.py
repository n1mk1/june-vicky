"""Persona registry: built-ins and builder templates from the repo, custom VCs from Postgres."""

import re
import uuid
from functools import lru_cache
from pathlib import Path

import yaml

from vicky import db
from vicky.areopagus.schema import VCPersona

HERE = Path(__file__).resolve().parent
DEFAULT_PANEL = ["aristotle", "thales", "xenophon", "plato", "socrates"]
MAX_PANEL = 5
# The built-ins before the philosopher rename (ADR 0002). Sessions recorded under these ids still open,
# show the new names and can be continued; new sessions seat the new investors.
LEGACY_IDS = {
    "james": "aristotle",
    "alex": "thales",
    "mark": "socrates",
    "claire": "plato",
    "kenji": "xenophon",
}


def canonical(pid: str) -> str:
    return LEGACY_IDS.get(pid, pid)


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
    return VCPersona.model_validate(
        {
            **r["spec"],
            "id": r["slug"],
            "builtin": False,
            "version": r["version"],
            "base_archetype": r["base_archetype"],
        }
    )


async def custom() -> list[VCPersona]:
    rows = await db.fetch("select * from vc_personas order by created_at")
    return [_from_row(r) for r in rows]


async def all_personas() -> list[VCPersona]:
    return [*builtins().values(), *await custom()]


async def get(pid: str) -> VCPersona | None:
    """By id; an old built-in id gives the investor it became."""
    if (cid := canonical(pid)) in builtins():
        return builtins()[cid]
    r = await db.fetchrow("select * from vc_personas where slug = $1", pid)
    return _from_row(r) if r else None


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "vc"
    return f"{base}-{uuid.uuid4().hex[:6]}"


async def create(spec: dict, base_archetype: str | None = None) -> VCPersona:
    data = {k: v for k, v in spec.items() if k not in ("id", "builtin", "version")}
    slug = _slug(str(data.get("name") or "vc"))
    p = VCPersona.model_validate(
        {**data, "id": slug, "builtin": False, "base_archetype": base_archetype or data.get("base_archetype")}
    )
    await db.execute(
        "insert into vc_personas (slug, spec, base_archetype) values ($1, $2, $3)",
        slug,
        p.model_dump(mode="json"),
        p.base_archetype,
    )
    return p


async def update(pid: str, spec: dict) -> VCPersona:
    if pid in builtins():
        raise PersonaError("Built-in investors are read-only; fork one to edit it.")
    r = await db.fetchrow("select * from vc_personas where slug = $1", pid)
    if r is None:
        raise KeyError(pid)
    data = {**r["spec"], **{k: v for k, v in spec.items() if k not in ("id", "builtin", "version")}}
    p = VCPersona.model_validate({**data, "id": pid, "builtin": False, "version": r["version"] + 1})
    await db.execute(
        "update vc_personas set spec = $2, version = version + 1 where slug = $1",
        pid,
        p.model_dump(mode="json"),
    )
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
    return await create(
        data, base_archetype=src.archetype if src.builtin else src.base_archetype or src.archetype
    )


async def panel(ids: list[str] | None, strict: bool = True) -> list[VCPersona]:
    """The investors for these ids. Strict (a new session): old built-in ids seat the investors they became.
    Not strict (an existing session): skip ids that no longer exist (a custom investor deleted after a
    session seated them), so the session can still be viewed and ended; an old built-in id gives the
    investor it became, keyed by the old id, because that is the key the session's state and turns use."""
    ids = [i for i in (ids or DEFAULT_PANEL) if i][:MAX_PANEL]
    if strict:
        ids = [canonical(i) for i in ids]
    out = []
    for i in dict.fromkeys(ids):
        p = await get(i)
        if p is None:
            if not strict:
                continue
            raise PersonaError(f"Unknown investor {i!r}")
        out.append(p if p.id == i else p.model_copy(update={"id": i}))
    if not out and strict:
        raise PersonaError("Pick at least one investor")
    return out
