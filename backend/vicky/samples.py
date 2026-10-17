"""Sample companies ("Try a sample"). They load through the same path as any upload:
files → datasets → mapping (prefilled from the sample's mapping.yaml) → facts → confirm.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from vicky import DATA_DIR
from vicky.model.figures import Fact, Source
from vicky.model.loader import ParsedDataset, parse_upload
from vicky.model.mapping import ColumnMapping, propose_heuristic

SAMPLES_DIR = DATA_DIR / "samples"
DATA_SUFFIXES = (".csv", ".xlsx")


@dataclass
class SampleFile:
    filename: str
    data: bytes
    datasets: list[ParsedDataset]


@dataclass
class Sample:
    id: str
    profile: dict
    files: list[SampleFile]
    mappings: dict[str, list[ColumnMapping]] = field(default_factory=dict)
    facts: list[Fact] = field(default_factory=list)


def list_samples() -> list[dict]:
    out = []
    for d in sorted(p for p in SAMPLES_DIR.iterdir() if p.is_dir() and (p / "profile.yaml").exists()):
        prof = yaml.safe_load((d / "profile.yaml").read_text(encoding="utf-8")) or {}
        out.append({"id": d.name, "name": prof.get("name", d.name), "country": prof.get("country"),
                    "business_model": prof.get("business_model"), "granularity": prof.get("granularity"),
                    "one_liner": prof.get("one_liner", "")})
    return out


def _mapping_entries(raw) -> dict[str, list[dict]]:
    """Return {dataset filename or '*': [mapping dicts]} for both supported mapping.yaml shapes."""
    if raw is None:
        return {}
    if isinstance(raw, list):
        return {"*": raw}
    if isinstance(raw, dict):
        if "mappings" in raw:
            return {raw.get("dataset", "*"): raw["mappings"]}
        if "datasets" in raw:
            return {d.get("dataset", "*"): d.get("mappings", []) for d in raw["datasets"]}
    return {}


def _to_mapping(entries: list[dict], ds: ParsedDataset, currency: str) -> list[ColumnMapping]:
    by_col = {str(e["source_column"]): e for e in entries}
    heuristic = {m.source_column: m for m in propose_heuristic(ds, currency)}
    out = []
    for col in ds.column_names():
        e = by_col.get(col)
        if col == "period" and ds.transposed:
            out.append(ColumnMapping(source_column="period", canonical_field="period", confidence=0.95))
            continue
        if e is None:
            out.append(heuristic[col])
            continue
        unit = e.get("unit") or ""
        if unit in ("month", "quarter", "null", None):
            unit = ""
        out.append(ColumnMapping(source_column=col, canonical_field=e.get("canonical_field"), unit=str(unit),
                                 confidence=float(e.get("confidence", 0.95)), note=e.get("note") or ""))
    return out


def load_sample(sample_id: str) -> Sample:
    d = SAMPLES_DIR / sample_id
    if not (d / "profile.yaml").exists():
        raise KeyError(sample_id)
    profile = yaml.safe_load((d / "profile.yaml").read_text(encoding="utf-8")) or {}
    currency = str(profile.get("currency", "usd"))
    mapping_raw = yaml.safe_load((d / "mapping.yaml").read_text(encoding="utf-8")) if (d / "mapping.yaml").exists() else None
    entries = _mapping_entries(mapping_raw)
    files: list[SampleFile] = []
    mappings: dict[str, list[ColumnMapping]] = {}
    for path in sorted(d.iterdir()):
        if path.suffix.lower() not in DATA_SUFFIXES:
            continue
        data = path.read_bytes()
        parsed = parse_upload(data, path.name)
        files.append(SampleFile(path.name, data, parsed))
        for ds in parsed:
            own = entries.get(path.name)
            if own is None and "*" in entries and ds.table_kind == "series":
                own = entries["*"]
            key = f"{path.name}#{ds.name}"
            mappings[key] = _to_mapping(own, ds, currency) if own else propose_heuristic(ds, currency)
    facts = load_pack_facts(d)
    return Sample(sample_id, profile, files, mappings, facts)


def load_pack_facts(d: Path) -> list[Fact]:
    path = d / "pack_facts.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = raw.get("facts", raw) if isinstance(raw, dict) else raw
    out = []
    for i, f in enumerate(items or []):
        try:
            value = float(f["value"])
        except (TypeError, ValueError, KeyError):
            continue
        src = f.get("source") or {}
        if isinstance(src, str):
            src = {"kind": "pack_summary", "ref": src}
        out.append(Fact(
            id=f"pack-{i + 1}", name=str(f["name"]), label=f.get("label", ""), value=value,
            unit=str(f.get("unit") or "count").lower(), period=str(f["period"]) if f.get("period") else None,
            kind=f.get("kind", "historical"),
            source=Source(kind=src.get("kind", "pack_summary"), ref=str(src.get("ref", ""))),
            status="confirmed", target_metric=bool(f.get("target_metric", False)), note=f.get("note"),
        ))
    return out


def load_targets(sample_id: str) -> list[dict]:
    path = SAMPLES_DIR / sample_id / "pack_facts.yaml"
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw.get("targets", []) if isinstance(raw, dict) else []
