"""Investor kits: every tool runs on every sample, returns only Figure-shaped numbers, agrees with
the engine, and has a strict-compatible input schema.

Number rule (kept deliberately simple): walking a tool result, every int/float must sit inside a
dict that looks like a Figure (has id, value, formula and source; anything nested in it, such as
`inputs[].value`, is part of that Figure). The single exception is an integer under the key
`"month"`, used as a path index in projections. Booleans are not numbers here.
"""

import json
import re
from functools import cache

import pytest
import yaml

from vicky.areopagus.kits import KITS, LENS_KITS, TOOLS, kit_tools, registry_for, run_tool
from vicky.areopagus.kits.cash import simulate
from vicky.areopagus.kits.governance import GEO_DIR, country_code
from vicky.model.context import TruthContext, sample_context
from vicky.model.figures import Figure, MissingFigure

SAMPLES = ["tidewell", "harbor-labs", "services-co"]
FIG_KEYS = {"id", "value", "formula", "source"}
META_INT_KEYS = {"month"}
UNSUPPORTED_SCHEMA_KEYS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength",
                           "maxLength", "pattern", "maxItems", "uniqueItems", "minProperties", "maxProperties"}

# Example arguments for tools that take any (all fields are required under strict tool use).
ARGS: dict[str, dict] = {
    "quant_runway_sensitivity": {"burn_change_pct": 20},
    "redteam_stress": {"scenario": "all"},
    "market_bottom_up": {"target_accounts": 40000, "annual_value_per_account": 6000, "reachable_share_pct": 25},
    "terms_dilution": {"instrument": "priced_round", "round_size": 3_000_000, "pre_money_or_cap": 15_000_000,
                       "option_pool_pct": 0, "safe_amounts": [1_000_000, 500_000], "safe_caps": [10_000_000, 10_000_000]},
    "terms_waterfall": {"exit_value": 6_000_000, "invested": 3_000_000, "investor_ownership_pct": 20,
                        "liquidation_multiple": 1, "participating": False, "participation_cap_multiple": None},
    "milestone_use_of_funds": {"round_size": None, "burn_increase_pct": 50},
    "milestone_arr_projection": {"months": 18, "target_arr": 5_000_000},
    "benchmark_compare": {"metric": "burn_multiple"},
    "cash_default_alive": {"growth_basis": "recent", "growth_override_pct": None, "include_credits": False},
}


@cache
def ctx(sample: str) -> TruthContext:
    return sample_context(sample)


def bare_numbers(x, path: str = "$") -> list[str]:
    if isinstance(x, dict):
        if FIG_KEYS <= x.keys():
            return []
        bad: list[str] = []
        for k, v in x.items():
            if k in META_INT_KEYS and isinstance(v, int) and not isinstance(v, bool):
                continue
            bad += bare_numbers(v, f"{path}.{k}")
        return bad
    if isinstance(x, list):
        return [p for i, v in enumerate(x) for p in bare_numbers(v, f"{path}[{i}]")]
    if x is None or isinstance(x, bool | str):
        return []
    if isinstance(x, int | float):
        return [path]
    return [f"{path} (not JSON: {type(x).__name__})"]


def figures_in(x) -> list[dict]:
    if isinstance(x, dict):
        if FIG_KEYS <= x.keys():
            return [x]
        return [f for v in x.values() for f in figures_in(v)]
    if isinstance(x, list):
        return [f for v in x for f in figures_in(v)]
    return []


def missing_in(x) -> list[dict]:
    if isinstance(x, dict):
        if x.get("missing") is True:
            return [x]
        return [m for v in x.values() for m in missing_in(v)]
    if isinstance(x, list):
        return [m for v in x for m in missing_in(v)]
    return []


def call(sample: str, name: str, **override) -> dict:
    return TOOLS[name].fn(ctx(sample), **{**ARGS.get(name, {}), **override})


def fval(res: dict, *path: str) -> float:
    x = res
    for p in path:
        x = x[p]
    return x["value"]


# ---------------------------------------------------------------- every tool, every sample

@pytest.mark.parametrize("sample", SAMPLES)
@pytest.mark.parametrize("name", sorted(TOOLS))
def test_tool_runs_and_numbers_are_figures(sample, name):
    res = call(sample, name)
    assert isinstance(res, dict) and "error" not in res, res
    json.dumps(res)
    assert bare_numbers(res) == []
    for f in figures_in(res):
        fig = Figure.model_validate(f)
        assert fig.formula.strip(), fig.id
        if fig.source.kind == "derived":
            assert fig.inputs, f"derived figure {fig.id} has no inputs"
    for m in missing_in(res):
        mf = MissingFigure.model_validate(m)
        assert mf.needs and mf.reason


def test_projections_are_forecasts():
    res = call("tidewell", "redteam_stress")
    decay = res["scenarios"]["growth_decay"]
    assert decay["arr_after_12m"]["kind"] == "forecast"
    assert decay["arr_after_12m"]["source"]["kind"] == "derived"
    assert all(p["arr"]["kind"] == "forecast" for p in decay["path"])
    assert [p["month"] for p in decay["path"]] == [3, 6, 9, 12]
    rs = call("harbor-labs", "quant_runway_sensitivity")
    assert rs["runway_burn_up"]["kind"] == "forecast"


# ---------------------------------------------------------------- kit figures agree with the engine

@pytest.mark.parametrize("sample", ["tidewell", "harbor-labs"])
def test_quant_audit_matches_engine(sample):
    c = ctx(sample)
    bm = call(sample, "quant_burn_multiple")
    assert fval(bm, "burn_multiple") == c.figures["burn_multiple"].value
    arr = call(sample, "quant_arr_without_fees")
    assert fval(arr, "arr") == c.figures["arr"].value
    k = 12 // c.model.months_per_period
    assert fval(arr, "revenue_run_rate") == pytest.approx(c.figures["revenue"].value * k)
    assert fval(arr, "run_rate_gap") == pytest.approx(fval(arr, "revenue_run_rate") - c.figures["arr"].value)
    ret = call(sample, "quant_retention")
    for k_ in ("nrr", "grr"):
        if isinstance(c.figures.get(k_), Figure):
            assert fval(ret, k_) == c.figures[k_].value
    rs = call(sample, "quant_runway_sensitivity")
    cash, burn = c.figures["cash_balance"].value, c.figures["burn"].value
    assert fval(rs, "runway_months") == c.figures["runway_months"].value
    assert fval(rs, "runway_burn_up") == pytest.approx(cash / (burn * 1.2))
    assert fval(rs, "runway_burn_down") == pytest.approx(cash / (burn * 0.8))


def test_credit_dependence_matches_engine():
    c = ctx("tidewell")
    r = call("tidewell", "governance_credit_dependence")
    assert fval(r, "burn_multiple_ex_credits") == c.figures["burn_multiple_ex_credits"].value
    share = fval(r, "credit_share_of_burn")
    assert share == pytest.approx(fval(r, "credits_l12m") / fval(r, "burn_before_credits_l12m"))
    assert 0 < share < 1


def test_concentration_matches_engine():
    c = ctx("harbor-labs")
    r = call("harbor-labs", "customer_concentration")
    assert fval(r, "top_customer_share") == c.figures["top_customer_share"].value
    assert r["top_customers"][0]["share"]["value"] == pytest.approx(c.figures["top_customer_share"].value)
    ids = [f["id"] for f in figures_in(r)]
    assert len(ids) == len(set(ids)), "figure ids in one result must be unique"


def test_largest_customer_leaves_uses_engine_share():
    c = ctx("harbor-labs")
    r = call("harbor-labs", "redteam_stress", scenario="largest_customer_leaves")["scenarios"]["largest_customer_leaves"]
    share, mrr = c.figures["top_customer_share"].value, c.figures["mrr"].value
    assert fval(r, "arr_after") == pytest.approx((mrr - share * mrr) * 12)


def test_growth_decay_below_flat_when_slowing():
    c = ctx("tidewell")
    assert c.figures["cmgr_recent"].value < c.figures["cmgr_12m"].value
    d = call("tidewell", "redteam_stress", scenario="growth_decay")["scenarios"]["growth_decay"]
    assert fval(d, "arr_after_12m") < fval(d, "arr_if_recent_growth_holds")
    assert fval(d, "growth_after_12m") < c.figures["cmgr_recent"].value


def test_cash_default_alive_inputs_and_simulation():
    c = ctx("harbor-labs")
    r = call("harbor-labs", "cash_default_alive")
    assert fval(r, "cash_balance") == c.figures["cash_balance"].value
    assert fval(r, "growth") == c.figures["cmgr_recent"].value
    assert r["verdict"] in ("default_alive", "default_dead", "undetermined", "profitable_now")
    # cash 100, revenue 10, expenses 20, flat: cash hits 0 after month 10 and goes negative in month 11
    assert simulate(100, 10, 20, 0.0) == {"verdict": "default_dead", "month": 11, "low": -10}
    assert simulate(100, 10, 20, 0.5)["verdict"] == "default_alive"
    profitable = call("services-co", "cash_default_alive")
    assert profitable["verdict"] == "profitable_now"


def test_milestone_months_arithmetic():
    c = ctx("harbor-labs")
    r = call("harbor-labs", "milestone_use_of_funds", round_size=2_000_000, burn_increase_pct=50)
    burn = c.figures["burn"].value
    assert fval(r, "months_current_burn") == pytest.approx(2_000_000 / burn)
    assert fval(r, "months_higher_burn") == pytest.approx(2_000_000 / (burn * 1.5))
    assert r["round_size"]["source"]["kind"] == "founder_stated"


# ---------------------------------------------------------------- missing inputs

def test_missing_inputs_name_what_is_needed():
    r = call("services-co", "quant_burn_multiple")
    assert {m["id"] for m in r["missing"]} >= {"burn_multiple"}
    r = call("harbor-labs", "redteam_forecast_gaps")
    assert r["missing"][0]["needs"]
    r = call("services-co", "product_services_share")
    assert r["missing"][0]["needs"] == ["revenue.one_time"]


def test_benchmark_only_from_sources():
    r = call("harbor-labs", "benchmark_compare", metric="top_customer_share")
    if not r["sources"]:
        assert "no sourced benchmark" in r["no_sourced_benchmark"].lower()
    r = call("tidewell", "benchmark_compare", metric="burn_multiple")
    if r["sources"]:
        assert all(s.get("id") for s in r["sources"])
        assert "caution" in r  # Canadian company, US-heavy sources


# ---------------------------------------------------------------- Terms: worked examples

def own(res: dict, key: str) -> float:
    return res[key]["value"]


def test_terms_priced_round_with_capped_safes():
    """data/playbooks/term-sheets.md worked example: two post-money SAFEs at a $10M cap
    ($1.0M and $0.5M), then $3M at $15M pre-money, no new pool.
    Existing holders 70.83% (founders 63.75% + pool 7.08%), SAFE A 8.33%, SAFE B 4.17%, investor 16.67%."""
    r = call("tidewell", "terms_dilution")
    assert own(r, "new_investor") == pytest.approx(3 / 18)
    assert r["safes"][0]["value"] == pytest.approx(0.0833, abs=1e-4)
    assert r["safes"][1]["value"] == pytest.approx(0.0417, abs=1e-4)
    assert own(r, "existing_holders") == pytest.approx(0.7083, abs=1e-4)
    assert own(r, "implied_post_money") == 18_000_000
    total = own(r, "existing_holders") + own(r, "new_investor") + own(r, "option_pool") + sum(s["value"] for s in r["safes"])
    assert total == pytest.approx(1.0)
    assert all(f["source"]["kind"] == "founder_stated" for f in r["inputs"])
    assert "not a view" in r["note"]


def test_terms_option_pool_shuffle():
    """$3M at $12M pre ($15M post) with a 10%-of-post pool created pre-money: investor 20%, pool 10%, existing 70%."""
    r = call("tidewell", "terms_dilution", round_size=3_000_000, pre_money_or_cap=12_000_000, option_pool_pct=10,
             safe_amounts=[], safe_caps=[])
    assert own(r, "new_investor") == pytest.approx(0.20)
    assert own(r, "option_pool") == pytest.approx(0.10)
    assert own(r, "existing_holders") == pytest.approx(0.70)
    assert own(r, "dilution_existing") == pytest.approx(0.30)


def test_terms_uncapped_and_out_of_money_safes_convert_at_round_price():
    """$4M at $12M pre ($16M post), one $500K SAFE: it owns 500K / 16M = 3.125% whether uncapped or capped above the price."""
    for caps in ([None], [50_000_000]):
        r = call("tidewell", "terms_dilution", round_size=4_000_000, pre_money_or_cap=12_000_000, option_pool_pct=0,
                 safe_amounts=[500_000], safe_caps=caps)
        assert r["safes"][0]["value"] == pytest.approx(0.03125)
        assert own(r, "new_investor") == pytest.approx(0.25)
        assert own(r, "existing_holders") == pytest.approx(0.71875)


def test_terms_post_money_safe_round():
    """$1M SAFE at a $10M post-money cap, plus an earlier $0.5M SAFE at a $5M cap: 10% + 10%, existing 80%."""
    r = call("tidewell", "terms_dilution", instrument="post_money_safe", round_size=1_000_000, pre_money_or_cap=10_000_000,
             option_pool_pct=0, safe_amounts=[500_000], safe_caps=[5_000_000])
    assert own(r, "new_investor") == pytest.approx(0.10)
    assert r["safes"][0]["value"] == pytest.approx(0.10)
    assert own(r, "existing_holders") == pytest.approx(0.80)


@pytest.mark.parametrize("exit_value,participating,investor", [
    (6_000_000, False, 3_000_000), (6_000_000, True, 3_600_000),
    (60_000_000, False, 12_000_000), (60_000_000, True, 14_400_000),
])
def test_terms_waterfall_playbook_table(exit_value, participating, investor):
    """Playbook: investor paid $3M for 20%; 1x preference."""
    r = call("tidewell", "terms_waterfall", exit_value=exit_value, participating=participating)
    assert own(r, "investor_proceeds") == pytest.approx(investor)
    assert own(r, "common_proceeds") == pytest.approx(exit_value - investor)


def test_terms_bad_inputs_are_recoverable():
    r = run_tool("terms_dilution", ctx("tidewell"), {**ARGS["terms_dilution"], "option_pool_pct": 150})
    assert "error" in r
    r = run_tool("terms_dilution", ctx("tidewell"), {**ARGS["terms_dilution"], "safe_caps": [1]})
    assert "error" in r
    assert "error" in run_tool("no_such_tool", ctx("tidewell"), {})


def test_terms_never_suggests_a_valuation():
    for name in ("terms_dilution", "terms_waterfall"):
        d = TOOLS[name].description.lower()
        assert "supplies" in d and "never" in d
    text = json.dumps(call("tidewell", "terms_dilution")).lower()
    for phrase in ("you should", "we recommend", "fair valuation", "suggested valuation", "market valuation"):
        assert phrase not in text


# ---------------------------------------------------------------- Governance: country rules

def test_country_code_mapping():
    assert country_code({"country": "CA"}) == "CA"
    assert country_code({"country": "GB"}) == "UK"
    assert country_code({"country": "FR"}) == "generic"


@pytest.mark.skipif(not ((GEO_DIR / "CA.md").exists() and (GEO_DIR / "US.md").exists()), reason="geo playbooks absent")
def test_governance_rules_differ_by_country():
    ca, us = (call(s, "governance_country_rules") for s in ("tidewell", "harbor-labs"))
    assert ca["playbook"] == "geo/CA.md" and us["playbook"] == "geo/US.md"
    assert ca["rules"] and us["rules"] and set(ca["rules"]) != set(us["rules"])
    for r in ca["rules"] + us["rules"]:
        assert "verify" in r.lower()
    assert "not tax or legal advice" in ca["note"]


def test_governance_rules_without_playbook(monkeypatch, tmp_path):
    from vicky.areopagus.kits import governance

    monkeypatch.setattr(governance, "GEO_DIR", tmp_path)
    r = call("tidewell", "governance_country_rules")
    assert r["rules"] == [] and r["missing"][0]["needs"]


def test_parse_playbook_bullets():
    from vicky.areopagus.kits.governance import parse_playbook

    front, rules = parse_playbook("---\ntitle: X\nversion: 2\n---\n# Head\n## Credits\n- A rule that\n  wraps.\n- **Bold** one\n\nText\n")
    assert front == {"title": "X", "version": "2"}
    assert rules == ["Credits: A rule that wraps.", "Credits: Bold one"]


# ---------------------------------------------------------------- schemas and registry

def _walk_schema(s: dict, path: str = "$") -> list[str]:
    bad = [f"{path}.{k}" for k in s if k in UNSUPPORTED_SCHEMA_KEYS]
    for k, v in s.items():
        if isinstance(v, dict):
            bad += _walk_schema(v, f"{path}.{k}")
        elif isinstance(v, list):
            bad += [b for i, x in enumerate(v) if isinstance(x, dict) for b in _walk_schema(x, f"{path}.{k}[{i}]")]
    return bad


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_input_schema_is_strict(name):
    t = TOOLS[name]
    s = t.input_schema
    assert s["type"] == "object"
    assert s["additionalProperties"] is False
    assert s["required"] == list(s["properties"])
    assert _walk_schema(s) == []
    assert re.fullmatch(r"[a-z][a-z0-9_]{2,63}", t.name)
    assert t.description and len(t.description) < 600
    assert t.to_tool()["strict"] is True
    for prop in s["properties"].values():
        assert prop.get("description")


def test_tool_names_unique_and_kits_complete():
    names = [t.name for k in KITS.values() for t in k.tools]
    assert len(names) == len(set(names))
    assert set(KITS) == {"QuantAudit", "Customer", "Channel", "Governance", "RedTeam", "Market", "Terms", "Milestone",
                         "Benchmark", "Cash", "Product"}
    assert all(k in KITS for kits in LENS_KITS.values() for k in kits)


def test_builtin_persona_kits_resolve():
    from vicky import PACKAGE_DIR

    for path in sorted((PACKAGE_DIR / "areopagus" / "builtin").glob("*.yaml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        tools = kit_tools(spec["kits"])
        assert {t.kit for t in tools} == set(spec["kits"]), path.name


def test_registry_for_personas_and_lenses():
    james = registry_for(["Milestone", "QuantAudit"], {})
    assert [t.kit for t in james][0] == "Milestone"
    assert {t.kit for t in james} == {"Milestone", "QuantAudit"}
    custom = registry_for([], {"runway": 0.8, "market": 0.59, "terms_cap_table": 0.6})
    assert {t.kit for t in custom} == {"Cash", "Milestone", "Terms"}
    both = registry_for(["Cash"], {"unit_economics": 0.9})
    assert {t.kit for t in both} == {"Cash", "QuantAudit"}
    assert len({t.name for t in both}) == len(both)
    assert registry_for(["quant_audit", "red team", "Nope"], {}) == kit_tools(["QuantAudit", "RedTeam"])
