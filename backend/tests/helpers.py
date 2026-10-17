"""Test helpers: build the canonical model and metrics for a sample without a database."""

from vicky.model.financials import DatasetInput, build_model
from vicky.model.metrics import compute_metrics
from vicky.samples import load_sample


def sample_model(sample_id: str):
    s = load_sample(sample_id)
    inputs = []
    for f in s.files:
        for ds in f.datasets:
            mapping = s.mappings[f"{f.filename}#{ds.name}"]
            inputs.append(DatasetInput(
                id=f"{f.filename}#{ds.name}", name=ds.name, table_kind=ds.table_kind, granularity=ds.granularity,
                transposed=ds.transposed, rows=ds.rows, mapping=[m.model_dump() for m in mapping],
            ))
    model = build_model(inputs, s.profile.get("currency", "usd"), s.profile.get("granularity"))
    return s, model


def sample_metrics(sample_id: str):
    s, model = sample_model(sample_id)
    return s, model, compute_metrics(model, s.facts, s.profile)
