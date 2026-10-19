"""Currency: CAD by default, column currencies read from the file, conversion at Bank of Canada rates
(period average for flows, period end for stocks), the Valet client, and the dashboard's display currency."""

import json
from datetime import date

import httpx
import pytest

from vik.model.context import build_context
from vik.model.currencies import CURRENCIES, currency_in, norm_currency
from vik.model.figures import Fact, Source, fmt_money
from vik.model.financials import DatasetInput, build_model
from vik.model.fx import FOREIGN, Rates, period_range, series_id
from vik.model.loader import parse_number, parse_upload
from vik.model.mapping import propose_heuristic
from vik.services import fx as fx_service

USD = {"2025-01-02": 1.40, "2025-01-15": 1.44, "2025-01-31": 1.45, "2025-02-03": 1.42, "2025-02-28": 1.38}
GBP = {"2025-01-02": 1.80, "2025-01-15": 1.80, "2025-01-31": 1.80, "2025-02-03": 1.75, "2025-02-28": 1.75}


def rates() -> Rates:
    return Rates(daily={"usd": dict(USD), "gbp": dict(GBP)})


def series(rows: list[dict], mapping: list[dict], name: str = "pl") -> DatasetInput:
    return DatasetInput(
        id=name,
        name=name,
        table_kind="series",
        granularity="month",
        transposed=False,
        rows=rows,
        mapping=mapping,
    )


# ---------------------------------------------------------------- rates


def test_default_currency_is_cad_and_every_bank_of_canada_currency_is_known():
    assert norm_currency(None) == "cad" and norm_currency("") == "cad" and norm_currency("XYZ") == "cad"
    assert norm_currency("USD") == "usd"
    assert len(CURRENCIES) == 25 and len(FOREIGN) == 24 and "cad" not in FOREIGN
    assert series_id("usd") == "FXUSDCAD"
    assert (
        fmt_money(1_500_000) == "$1.50M"
        and fmt_money(1_500_000, "usd") == "US$1.50M"
        and fmt_money(900, "gbp") == "£900"
    )


def test_period_rates_average_for_flows_end_for_stocks_and_cross_through_cad():
    r = rates()
    avg = r.rate("usd", "cad", "2025-01", "avg")
    assert (
        avg
        and avg.value == pytest.approx((1.40 + 1.44 + 1.45) / 3)
        and "Jan 2025 average of 3 daily rates" in avg.basis
    )
    end = r.rate("usd", "cad", "2025-01", "end")
    assert end and end.value == 1.45 and end.basis == "rate on 2025-01-31"
    inv = r.rate("cad", "usd", "2025-02", "end")
    assert inv and inv.value == pytest.approx(1 / 1.38)
    cross = r.rate("gbp", "usd", "2025-02", "avg")  # GBP→CAD→USD
    assert cross and cross.value == pytest.approx(1.75 / ((1.42 + 1.38) / 2))
    q = r.rate("usd", "cad", "2025-Q1", "avg")
    assert q and q.value == pytest.approx(sum(USD.values()) / 5)
    assert r.rate("cad", "cad", "2025-01").value == 1.0
    assert "Bank of Canada" in avg.note() and avg.note().startswith("USD→CAD ×")


def test_a_period_after_the_last_rate_uses_the_latest_and_one_before_any_rate_is_not_converted():
    r = rates()
    fut = r.rate("usd", "cad", "2027-06", "avg")
    assert fut and fut.value == 1.38 and fut.basis == "latest rate, 2025-02-28"
    assert r.rate("usd", "cad", "2019-03", "avg") is None  # no rate published for it: never guessed
    assert r.rate("eur", "cad", "2025-01", "avg") is None  # a currency with no rates loaded
    assert period_range("2025-Q2") == (date(2025, 4, 1), date(2025, 6, 30)) and period_range("nope") is None


# ---------------------------------------------------------------- detection


def test_column_currency_is_read_from_headers_and_cells():
    assert (
        currency_in("Revenue (USD)") == "usd"
        and currency_in("revenue_eur") == "eur"
        and currency_in("MRR CA$") == "cad"
    )
    assert (
        currency_in("Total revenue") is None
        and currency_in("audit fees") is None
        and currency_in("Pen testing") is None
    )
    assert (
        currency_in("Revenue TRY") == "try" and currency_in("USD and EUR") is None
    )  # two currencies: not one
    assert (
        parse_number("US$1,200") == 1200
        and parse_number("(USD 1.2M)") == -1_200_000
        and parse_number("1 200 €") == 1200
    )
    assert parse_number("£900") == 900 and parse_number("$5k") == 5000 and parse_number("CHF 10") == 10
    csv = (
        b'Month,Revenue (USD),Cash,Customers\n2025-01,"US$1,000","$5,000",3\n2025-02,"US$1,100","$5,500",4\n'
    )
    ds = parse_upload(csv, "pl.csv")[0]
    cols = {c.name: c.currency for c in ds.columns}
    assert cols["Revenue (USD)"] == "usd" and cols["Cash"] is None and cols["Customers"] is None
    units = {m.source_column: m.unit for m in propose_heuristic(ds, "cad")}
    assert units["Revenue (USD)"] == "usd" and units["Cash"] == "cad" and units["Customers"] == "count"


# ---------------------------------------------------------------- conversion


def test_foreign_columns_convert_into_the_reporting_currency_with_the_rate_cited():
    ds = series(
        [
            {"period": "2025-01", "rev": 1000.0, "cash": 10_000.0, "fees": 50.0},
            {"period": "2025-02", "rev": 2000.0, "cash": 12_000.0, "fees": 60.0},
        ],
        [
            {"source_column": "period", "canonical_field": "period"},
            {"source_column": "rev", "canonical_field": "revenue.total", "unit": "usd"},
            {"source_column": "cash", "canonical_field": "cash_balance", "unit": "usd"},
            {"source_column": "fees", "canonical_field": None, "unit": "gbp"},
        ],
    )
    m = build_model([ds], "cad", fx=rates())
    assert m.value("revenue.total", "2025-01") == pytest.approx(
        1000 * (1.40 + 1.44 + 1.45) / 3
    )  # Jan average
    assert m.value("cash_balance", "2025-01") == pytest.approx(10_000 * 1.45)  # a stock: the Jan 31 rate
    assert m.raw["pl:fees"]["2025-02"] == pytest.approx(60 * 1.75)  # raw columns in a currency convert too
    _, ref, _ = m.source_ref("cash_balance", ["2025-01"])
    assert "converted USD→CAD ×1.45 (Bank of Canada, rate on 2025-01-31)" in ref
    _, ref2, _ = m.source_ref("revenue.total", ["2025-01", "2025-02"])
    assert ref2.endswith("converted USD→CAD at Bank of Canada rates for each period")


def test_without_a_rate_a_foreign_column_is_left_out_not_shown_in_the_wrong_currency():
    ds = series(
        [{"period": "2025-01", "rev": 1000.0}],
        [{"source_column": "rev", "canonical_field": "revenue.total", "unit": "usd"}],
    )
    m = build_model([ds], "cad", fx=None)
    assert m.value("revenue.total", "2025-01") is None and "pl:rev" not in m.raw
    assert m.fx_skipped == ["pl:rev 2025-01"]
    same = build_model(
        [
            series(
                [{"period": "2025-01", "rev": 1000.0}],
                [{"source_column": "rev", "canonical_field": "revenue.total", "unit": "cad"}],
            )
        ],
        "cad",
    )
    assert same.value("revenue.total", "2025-01") == 1000.0  # already CAD: no rate needed


def test_the_view_currency_converts_tables_facts_and_the_round_size():
    ds = series(
        [{"period": "2025-01", "rev": 1450.0}, {"period": "2025-02", "rev": 1380.0}],
        [{"source_column": "rev", "canonical_field": "revenue.total", "unit": "cad"}],
    )
    fact = Fact(
        id="f1",
        name="bookings_q1",
        label="Q1 bookings",
        value=100.0,
        unit="gbp",
        period="2025-02",
        status="confirmed",
        source=Source(kind="pdf", ref="deck.pdf p.2"),
    )
    profile = {"currency": "cad", "round_size": 1_420_000, "granularity": "month"}
    ctx = build_context([ds], [fact], profile, fx=rates(), currency="usd")
    assert ctx.currency == "usd" and ctx.profile["reporting_currency"] == "cad"
    jan = (1.40 + 1.44 + 1.45) / 3
    assert ctx.model.value("revenue.total", "2025-01") == pytest.approx(1450 / jan)
    f = ctx.facts[0]
    assert (
        f.unit == "usd"
        and f.value == pytest.approx(100 * 1.75 / ((1.42 + 1.38) / 2))
        and "GBP→USD" in f.source.ref
    )
    assert (
        ctx.profile["round_size"] == pytest.approx(1_420_000 / 1.38)
        and "CAD→USD" in ctx.profile["round_size_fx"]
    )
    base = build_context([ds], [fact], profile, fx=rates())
    assert base.currency == "cad" and base.model.value("revenue.total", "2025-01") == 1450.0
    assert base.facts[0].unit == "cad" and base.facts[0].value == pytest.approx(100 * 1.75)


# ---------------------------------------------------------------- Bank of Canada client


@pytest.fixture
def cache(monkeypatch) -> dict:
    """An in-memory stand-in for the Redis rate cache."""
    store: dict = {}

    async def cached(code, year):
        return store.get((code, year))

    async def put(code, year, obs, now):
        store[(code, year)] = {"fetched": now.isoformat(), "obs": obs}

    monkeypatch.setattr(fx_service, "_cached", cached)
    monkeypatch.setattr(fx_service, "_store", put)
    return store


def _valet(request: httpx.Request) -> httpx.Response:
    series_ids = request.url.path.split("/")[-2].split(",")
    year = request.url.params["start_date"][:4]
    obs = [
        {"d": f"{year}-01-02", **{s: {"v": "1.5"} for s in series_ids}},
        {"d": f"{year}-01-03", **{s: {"v": "1.6"} for s in series_ids}},
    ]
    return httpx.Response(200, json={"observations": obs})


async def test_valet_rates_are_parsed_per_year_cached_and_reused(cache):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return _valet(request)

    r = await fx_service.load(
        {"usd", "eur", "cad", "nope"},
        date(date.today().year - 1, 5, 1),
        transport=httpx.MockTransport(handler),
    )
    y = date.today().year
    assert (
        set(r.daily) == {"usd", "eur"}
        and r.daily["usd"][f"{y - 1}-01-02"] == 1.5
        and f"{y}-01-03" in r.daily["eur"]
    )
    assert len(seen) == 2 and all("FXEURCAD,FXUSDCAD" in u for u in seen)  # one call per year, both series
    assert ("usd", y - 1) in cache
    again = await fx_service.load({"usd"}, date(y - 1, 5, 1), transport=httpx.MockTransport(handler))
    assert len(seen) == 2 and again.daily["usd"] == r.daily["usd"]  # fresh cache: no second call


async def test_an_unreachable_api_falls_back_to_the_cache_or_no_rates(cache):
    def down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    r = await fx_service.load({"usd"}, transport=httpx.MockTransport(down))
    assert r.daily == {} and r.rate("usd", "cad", "2025-01") is None
    y = date.today().year
    cache[("usd", y)] = {
        "fetched": "2000-01-01T00:00:00+00:00",
        "obs": {f"{y}-01-02": 1.33},
    }  # stale, but all there is
    r = await fx_service.load({"usd"}, transport=httpx.MockTransport(down))
    assert r.daily["usd"] == {f"{y}-01-02": 1.33}
    assert (await fx_service.load(set())).daily == {}


def test_a_cached_year_counts_as_stale_until_it_is_over():
    from datetime import UTC, datetime

    now = datetime(2026, 10, 18, 12, tzinfo=UTC)
    assert fx_service._stale(None, 2026, now)
    assert not fx_service._stale({"fetched": "2026-10-18T10:00:00+00:00"}, 2026, now)
    assert fx_service._stale({"fetched": "2026-10-18T01:00:00+00:00"}, 2026, now)  # older than six hours
    assert fx_service._stale({"fetched": "2025-12-30T10:00:00+00:00"}, 2025, now)  # fetched before 2025 ended
    assert not fx_service._stale({"fetched": "2026-01-05T10:00:00+00:00"}, 2025, now)
    assert json.dumps({"fetched": now.isoformat()})  # entries are JSON for Redis


# ---------------------------------------------------------------- dashboard display currency (API)


@pytest.mark.db
async def test_dashboard_shows_any_currency_at_cited_rates(api_client, monkeypatch):
    from tests.helpers import load_and_confirm

    flat = {f"{y}-{m:02d}-01": 1.25 for y in range(2017, date.today().year + 2) for m in range(1, 13)}

    async def fake_load(codes, since=None, **_):
        return Rates(daily={c: dict(flat) for c in codes})

    monkeypatch.setattr(fx_service, "load", fake_load)
    await api_client.post("/auth/access", json={"code": "vik-demo"})
    r = await api_client.get("/dashboards/active")
    if r.status_code == 404:
        await load_and_confirm(api_client, "tidewell")
        r = await api_client.get("/dashboards/active")
    cad = r.json()
    assert cad["currency"] == "cad" and cad["reporting_currency"] == "cad" and len(cad["currencies"]) == 25
    usd = (await api_client.get("/dashboards/active", params={"currency": "usd"})).json()
    assert usd["currency"] == "usd" and usd["reporting_currency"] == "cad"

    def money_kpis(d: dict) -> dict[str, dict]:
        out = {}
        for w in d["widgets"]:
            kpi = w["evaluated"].get("kpi") or {}
            for k in [kpi.get("primary"), *(kpi.get("secondary") or [])]:
                if k and k.get("unit") in CURRENCIES and k.get("value"):
                    out[f"{w['id']}:{k['id']}"] = k
        return out

    a, b = money_kpis(cad), money_kpis(usd)
    assert a and set(a) == set(b)
    for key, k in a.items():
        assert b[key]["value"] == pytest.approx(k["value"] / 1.25, rel=1e-6) and b[key]["unit"] == "usd"
        assert b[key]["display"].startswith(("US$", "-US$"))
    eur = await api_client.get("/dashboards/active", params={"currency": "EUR"})
    assert eur.json()["currency"] == "eur"
    assert (await api_client.get("/dashboards/active", params={"currency": "xyz"})).json()[
        "currency"
    ] == "cad"
