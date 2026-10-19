"""Intake on files of any shape: date formats, title rows, scaled values, split dates, daily rows, ledgers,
wide sheets with summary columns, units in the mapping, and re-reading a table around the date column the
founder picks."""

import pytest

from vik.model.loader import parse_number, parse_period, parse_upload
from vik.model.mapping import propose_heuristic


def one(text: str, name: str = "t.csv"):
    [ds] = parse_upload(text.encode(), name)
    return ds


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("01/31/2024", ("2024-01", "month")),
        ("31/01/2024", ("2024-01", "month")),
        ("2024-01-15T10:00:00", ("2024-01", "month")),
        ("Jan 15, 2024", ("2024-01", "month")),
        ("15-Jan-24", ("2024-01", "month")),
        ("2024 Jan", ("2024-01", "month")),
        ("Mon, Feb 5 2024", ("2024-02", "month")),
        ("Sept 2024", ("2024-09", "month")),
        ("2024-W06", ("2024-02", "month")),
        ("1Q24", ("2024-Q1", "quarter")),
        ("Q1/2024", ("2024-Q1", "quarter")),
        ("FY24", ("2024", "year")),
        ("Jan 2024 Actual", ("2024-01", "month")),
        ("marketing 24", None),
        ("March", None),
    ],
)
def test_parse_period_formats(raw, expected):
    assert parse_period(raw) == expected


def test_day_first_is_decided_per_column():
    assert parse_period("03/04/2024") == ("2024-03", "month")
    assert parse_period("03/04/2024", dayfirst=True) == ("2024-04", "month")
    ds = one("Date,Revenue\n03/04/2024,1\n25/05/2024,2\n")
    assert [r["period"] for r in ds.rows] == ["2024-04", "2024-05"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.234,56", 1234.56),
        ("12,5%", 0.125),
        ("1,234", 1234.0),
        ("1.25", 1.25),
        ("1'234", 1234.0),
        ("500-", -500.0),
        ("2.5mm", 2_500_000.0),
        ("1.234.567", 1_234_567.0),
        ("#DIV/0!", None),
    ],
)
def test_parse_number_locales(raw, expected):
    assert parse_number(raw) == expected


def test_title_rows_and_thousands():
    ds = one(
        "Acme Inc. Income statement\nAll figures in CAD thousands\n\nMonth,Revenue,Customers\nJan 2024,47,10\nFeb 2024,52,12\n"
    )
    assert ds.table_kind == "series" and ds.period_axis == "Month"
    # counts aren't scaled; the row keeps its line in the file (title, title, blank, header, then line 5)
    assert ds.rows[0] == {"period": "2024-01", "_src_rows": [5], "Revenue": 47_000.0, "Customers": 10.0}
    assert any("thousands" in n for n in ds.notes)


def test_header_scale_and_percent_columns():
    ds = one("Month,Revenue ($000),Gross margin %\n2024-01,10,72%\n2024-02,12,74%\n")
    rev, gm = ds.columns[1], ds.columns[2]
    assert rev.scale == 1000 and ds.rows[0]["Revenue ($000)"] == 10_000
    assert gm.unit_hint == "pct" and gm.scale == 1
    props = {m.source_column: m for m in propose_heuristic(ds, "cad")}
    assert props["Month"].canonical_field == "period" and props["Month"].unit == "date"
    assert (
        props["Revenue ($000)"].canonical_field == "revenue.total" and props["Revenue ($000)"].unit == "cad"
    )
    assert props["Gross margin %"].canonical_field is None and props["Gross margin %"].unit == "pct"


def test_year_and_month_columns_combine():
    ds = one("Year,Month,Revenue\n2024,1,100\n2024,2,120\n2024,March,130\n")
    assert ds.granularity == "month" and [r["period"] for r in ds.rows] == ["2024-01", "2024-02", "2024-03"]


def test_daily_rows_sum_flows_and_keep_last_balance():
    ds = one(
        "Date,Revenue,Cash balance,New customers\n2024-01-03,100,900,1\n2024-01-20,50,850,2\n2024-02-02,70,800,0\n"
    )
    jan = ds.rows[0]
    assert jan["Revenue"] == 150 and jan["Cash balance"] == 850 and jan["New customers"] == 3


def test_ledger_pivots_to_one_column_per_account():
    ds = one(
        "Date,Account,Amount\n2024-01-03,Subscription revenue,100\n2024-01-20,Subscription revenue,50\n"
        "2024-01-05,Hosting,20\n2024-02-02,Subscription revenue,170\n"
    )
    assert ds.table_kind == "series" and ds.rows[0] == {
        "period": "2024-01",
        "Subscription revenue": 150.0,
        "Hosting": 20.0,
    }
    props = {m.source_column: m.canonical_field for m in propose_heuristic(ds, "cad")}
    assert props["Subscription revenue"] == "revenue.recurring" and props["Hosting"] == "cogs"


def test_customer_table_stays_a_customer_table():
    ds = one("Month,Customer,MRR\n2024-01,Acme,100\n2024-01,Globex,200\n2024-02,Acme,110\n")
    assert ds.table_kind == "customer_mrr"


def test_wide_sheet_with_codes_sections_and_summary_columns():
    ds = one(
        "Code,Line item,Jan-24,Feb-24,Mar-24,Q1 2024,FY2024 Budget\n4000,Revenue,10,11,12,33,40\n"
        ",Operating expenses,,,,,\n5000,Rent,1,1,1,3,3\n,Other,,,,,\n5100,Rent,2,2,2,6,6\n"
    )
    assert ds.transposed and ds.granularity == "month" and len(ds.rows) == 3
    assert [c.name for c in ds.columns] == ["period", "Revenue", "Rent", "Other · Rent"]
    assert any("Q1 2024" in n for n in ds.notes)


def test_excel_serials_only_under_a_date_header():
    assert one("Month,Revenue\n45292,10\n45323,20\n").rows[0]["period"] == "2024-01"
    ds = one("Month,Ending cash\n2024-01,45000\n2024-02,44000\n")
    assert ds.period_axis == "Month" and ds.rows[0]["Ending cash"] == 45_000


def test_table_without_dates_is_raw():
    ds = one("Metric,Value\nCash in bank,1200000\nCustomers,48\n")
    assert ds.table_kind == "raw" and "facts" in ds.notes[-1]


def test_forced_period_column():
    with pytest.raises(ValueError, match="doesn't read as dates"):
        parse_upload(b"Name,When,Revenue\na,x,1\nb,y,2\n", "t.csv", period_column={"t": "When"})


@pytest.mark.db
async def test_choosing_another_date_column_rereads_the_table(api_client):
    await api_client.post("/auth/access", json={"code": "vik-demo"})
    csv = b"Label,Billing period,Revenue\nA,2024/01,100\nB,2024/02,120\nC,2024/03,90\n"
    eng = (await api_client.post("/uploads", files={"file": ("billing.csv", csv, "text/csv")})).json()
    ds = eng["datasets"][0]
    m = (await api_client.get(f"/datasets/{ds['id']}/mapping")).json()
    assert any(t.get("kind") == "date" for t in m["targets"])
    rows = m["proposed"]
    axis = next(r for r in rows if r["canonical_field"] == "period")
    assert axis["unit"] == "date"
    # A stale unit on the axis ("quarter", as old sample mappings carry) is normalised, not rejected.
    fixed = [{**r, "unit": "quarter"} if r["canonical_field"] == "period" else r for r in rows]
    r = await api_client.put(f"/datasets/{ds['id']}/mapping", json={"mapping": fixed})
    assert r.status_code == 200, r.text
    assert next(x for x in r.json()["confirmed"] if x["canonical_field"] == "period")["unit"] == "date"
    # Two date axes are refused; a text column as the dates says why.
    two = [{**x, "canonical_field": "period"} for x in rows]
    assert (await api_client.put(f"/datasets/{ds['id']}/mapping", json={"mapping": two})).status_code == 422
    bad = [
        {
            **x,
            "canonical_field": "period"
            if x["source_column"] == "Label"
            else (None if x["canonical_field"] == "period" else x["canonical_field"]),
        }
        for x in rows
    ]
    r = await api_client.put(f"/datasets/{ds['id']}/mapping", json={"mapping": bad})
    assert r.status_code == 422 and "doesn't read as dates" in r.text
