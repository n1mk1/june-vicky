"""Playbooks (data/playbooks/*.md) and per-investor question banks.

`read_playbook(topic)` returns the playbooks tagged with a topic; geo rules are chosen by the
company's country. `question_bank(persona_id)` parses `questions-<id>.md` into questions with
their why/weak/strong anchors. Placeholders are filled only from Figures (`fill`); a question
whose placeholders can't all be filled is skipped rather than guessed.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from vicky import DATA_DIR
from vicky.model.figures import Figure

PLAYBOOKS = DATA_DIR / "playbooks"
GEO = {"CA": "CA", "US": "US", "GB": "UK", "UK": "UK"}
PLACEHOLDER = re.compile(r"\{([a-z0-9_.]+)\}")


@dataclass
class Playbook:
    id: str
    title: str
    topics: list[str]
    body: str


@dataclass
class BankQuestion:
    persona: str
    n: int
    text: str
    why: str = ""
    weak: str = ""
    strong: str = ""
    placeholders: set[str] = field(default_factory=set)


def _parse(path) -> Playbook:
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    if raw.startswith("---"):
        _, fm, body = raw.split("---", 2)
        meta = yaml.safe_load(fm) or {}
    return Playbook(id=path.stem, title=str(meta.get("title") or path.stem), topics=[str(t) for t in meta.get("topics") or []],
                    body=body.strip())


@lru_cache
def playbooks() -> list[Playbook]:
    return [_parse(p) for p in sorted(PLAYBOOKS.glob("*.md"))]


def geo_playbook(country: str | None) -> Playbook | None:
    name = GEO.get(str(country or "").upper(), "generic")
    path = PLAYBOOKS / "geo" / f"{name}.md"
    if not path.exists():
        path = PLAYBOOKS / "geo" / "generic.md"
    return _parse(path) if path.exists() else None


def read_playbook(topic: str, country: str | None = None) -> list[Playbook]:
    t = topic.lower().strip()
    out = [p for p in playbooks() if t in p.topics and not p.id.startswith("questions-")]
    if t in ("governance", "impact", "geo", "tax", "credits", "mandate"):
        g = geo_playbook(country)
        if g:
            out.append(g)
    return out


def _clean(m: re.Match | None) -> str:
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


_Q = re.compile(r"^###\s+(\d+)\.\s+(.+?)\s*$", re.M)


@lru_cache
def question_bank(persona_id: str) -> list[BankQuestion]:
    path = PLAYBOOKS / f"questions-{persona_id}.md"
    if not path.exists():
        return []
    body = _parse(path).body
    heads = list(_Q.finditer(body))
    out = []
    for i, m in enumerate(heads):
        chunk = body[m.end(): heads[i + 1].start() if i + 1 < len(heads) else len(body)]
        text = m.group(2).strip().strip('"“”')
        why = re.search(r"^Why:\s*(.+?)(?=\n- |\n\n|\Z)", chunk, re.M | re.S)
        weak = re.search(r"\*\*Weak:\*\*\s*(.+?)(?=\n- \*\*|\n\n|\Z)", chunk, re.S)
        strong = re.search(r"\*\*Strong:\*\*\s*(.+?)(?=\n- \*\*|\n\n|\Z)", chunk, re.S)
        q = BankQuestion(persona=persona_id, n=int(m.group(1)), text=text, why=_clean(why), weak=_clean(weak),
                         strong=_clean(strong).strip('"“”'))
        q.placeholders = set(PLACEHOLDER.findall(q.text))
        out.append(q)
    return out


def fill(text: str, figures: dict[str, Figure], company: str, extra: dict[str, str] | None = None) -> str | None:
    """Fill {placeholders} from figure displays and the profile; None if any can't be filled."""
    values = {"company": company, **(extra or {})}
    ok = True

    def sub(m: re.Match) -> str:
        nonlocal ok
        key = m.group(1)
        if key in values:
            return values[key]
        f = figures.get(key)
        if isinstance(f, Figure):
            return f.display
        ok = False
        return m.group(0)

    out = PLACEHOLDER.sub(sub, text)
    out = re.sub(r"(\d) mo (months?)\b", r"\1 \2", out)  # "{runway_months} months" -> "8.3 months"
    return out if ok else None
