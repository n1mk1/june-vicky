"""Generate the synthetic sample companies used as Vicky test fixtures.

Writes two fully fictional companies under ``backend/data/samples/``:

* ``harbor-labs/``  - US B2B SaaS, USD, quarterly, wide layout, cohort table,
  no tax-credit / grant income.
* ``services-co/``  - UK project-based studio, GBP, monthly, long layout,
  non-recurring (only the generic metric set applies).

Each folder gets the data files, ``profile.yaml``, ``mapping.yaml`` (the
correct column mapping) and ``expected.yaml`` (metric values computed here
from the generated numbers, with the formula next to each value).

Deterministic: the only randomness is ``random.Random(42)``. Re-running the
script reproduces byte-identical files.

Run from the repo root:

    uv run --with openpyxl python backend/scripts/make_fixtures.py

(Only the standard library is used; openpyxl is not required.)
"""

from __future__ import annotations

import csv
import io
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "data" / "samples"
GENERATOR = "backend/scripts/make_fixtures.py"
REGEN_CMD = "uv run --with openpyxl python backend/scripts/make_fixtures.py"


# --------------------------------------------------------------------------
# Small helpers: YAML emitter (stdlib has no YAML), CSV writer, formatting
# --------------------------------------------------------------------------


def _scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return json.dumps(str(v), ensure_ascii=False)


def _yaml_lines(obj, indent: int = 0) -> list[str]:
    pad = "  " * indent
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = _scalar(k) if not str(k).replace("_", "").isalnum() else str(k)
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{key}:")
                out.extend(_yaml_lines(v, indent + 1))
            elif isinstance(v, dict):
                out.append(f"{pad}{key}: {{}}")
            elif isinstance(v, list):
                out.append(f"{pad}{key}: []")
            else:
                out.append(f"{pad}{key}: {_scalar(v)}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and item:
                sub = _yaml_lines(item, indent + 1)
                first = sub[0].lstrip()
                out.append(f"{pad}- {first}")
                out.extend(sub[1:])
            elif isinstance(item, list) and item:
                out.append(f"{pad}-")
                out.extend(_yaml_lines(item, indent + 1))
            else:
                out.append(f"{pad}- {_scalar(item)}")
    else:
        out.append(f"{pad}{_scalar(obj)}")
    return out


def write_yaml(path: Path, obj, header: str) -> None:
    text = "\n".join(f"# {h}" if h else "#" for h in header.splitlines())
    text += "\n" + "\n".join(_yaml_lines(obj)) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def write_csv(path: Path, rows: list[list]) -> None:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")


def usd(v: int) -> str:
    """Harbor style: $1,234,567 ; negatives (12,345)."""
    return f"({-v:,})" if v < 0 else f"${v:,}"


def gbp(v: int) -> str:
    """Services style: £12,345 ; negatives -£1,234."""
    return f"-£{-v:,}" if v < 0 else f"£{v:,}"


def r6(x: float) -> float:
    return round(x, 6)


def r2(x: float) -> float:
    return round(x, 2)


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


# --------------------------------------------------------------------------
# Harbor Labs (US B2B SaaS, quarterly)
# --------------------------------------------------------------------------

# Quarter index 0 = Q1 2024 ... 10 = Q3 2026. Cohorts start at -4 = Q1 2023.
FIRST_COHORT = -4
N_Q = 11


def qlabel(i: int) -> str:
    year, q = divmod(i, 4)
    return f"Q{q + 1} {2024 + year}"


# New logos signed per quarter, keyed by quarter index.
NEW_LOGOS = {
    -4: 5,
    -3: 6,
    -2: 7,
    -1: 8,
    0: 8,
    1: 9,
    2: 10,
    3: 11,
    4: 11,
    5: 12,
    6: 13,
    7: 14,
    8: 15,
    9: 15,
    10: 16,
}
# Typical starting MRR per new logo (USD / month), keyed by quarter index.
BASE_ARPA = {i: 650 + 55 * (i - FIRST_COHORT) for i in NEW_LOGOS}
ARPA_MULT = [0.5, 0.6, 0.75, 0.9, 1.0, 1.0, 1.15, 1.3, 1.6, 2.1]

PREFIXES = [
    "Alder",
    "Brindle",
    "Cobalt",
    "Dunmore",
    "Elsworth",
    "Fenwick",
    "Greyfield",
    "Hollis",
    "Ivorine",
    "Juniper",
    "Kittering",
    "Larchmont",
    "Marlow",
    "Norcastle",
    "Orchard",
    "Pellham",
    "Quillon",
    "Redfern",
    "Stillwater",
    "Tamsin",
    "Upland",
    "Vantor",
    "Westbury",
    "Yarrow",
    "Zephyrine",
]
SUFFIXES = [
    "Freight",
    "Logistics",
    "Supply Co",
    "Distribution",
    "Foods",
    "Outfitters",
    "Industrial",
    "Parts",
    "Wholesale",
]

TOP_CUSTOMER = "Stillwater Distribution"
# Anchor account (signed Q2 2024): scripted MRR path, final quarter calibrated.
TOP_PATH = {1: 4200, 2: 4200, 3: 6500, 4: 6500, 5: 9800, 6: 12500, 7: 12500, 8: 16000, 9: 21000}

CHURN_EARLY, CHURN_LATE = 0.09, 0.04  # quarterly logo churn odds: first 2 quarters, later
P_EXPAND, P_CONTRACT = 0.12, 0.08  # quarterly odds a surviving account expands / contracts
NRR_TARGET = 1.08
GRR_TARGET = 0.90
TOP_SHARE_TARGET = 0.14
START_Q, END_Q = 6, 10  # Q3 2025 -> Q3 2026


def simulate_customers() -> dict[str, dict]:
    """Customer-level MRR simulation. Returns {name: {cohort, mrr{q: int}}}."""
    rng = random.Random(42)
    names = [f"{p} {s}" for s in SUFFIXES for p in PREFIXES]
    rng.shuffle(names)
    anchor_word = TOP_CUSTOMER.split()[0]  # keep the anchor's name unique
    names = [n for n in names if not n.startswith(anchor_word)]
    customers: dict[str, dict] = {}
    for q in range(FIRST_COHORT, N_Q):
        for k in range(NEW_LOGOS[q]):
            if q == 1 and k == 0:
                name = TOP_CUSTOMER
                path = dict(TOP_PATH)
            else:
                name = names.pop()
                path = {}
                mrr = round(BASE_ARPA[q] * rng.choice(ARPA_MULT) / 10) * 10
                path[q] = mrr
                for t in range(q + 1, N_Q):
                    age = t - q
                    churn_p = CHURN_EARLY if age <= 2 else CHURN_LATE
                    if rng.random() < churn_p:
                        break
                    roll = rng.random()
                    if roll < P_EXPAND:
                        mrr = round(mrr * rng.choice([1.15, 1.25, 1.4]) / 10) * 10
                    elif roll < P_EXPAND + P_CONTRACT:
                        mrr = round(mrr * rng.choice([0.7, 0.8, 0.9]) / 10) * 10
                    path[t] = mrr
            customers[name] = {"cohort": q, "mrr": path}
    return customers


def cohort_table(customers) -> dict[int, dict[int, int]]:
    tab: dict[int, dict[int, int]] = {}
    for c in customers.values():
        for t, m in c["mrr"].items():
            if t >= 0:
                tab.setdefault(c["cohort"], {}).setdefault(t, 0)
                tab[c["cohort"]][t] += m
    return tab


def nrr_grr(tab) -> tuple[int, int, int]:
    base = now = capped = 0
    for c, row in tab.items():
        if c <= START_Q:
            s, e = row.get(START_Q, 0), row.get(END_Q, 0)
            base += s
            now += e
            capped += min(s, e)
    return base, now, capped


def calibrate(customers) -> None:
    """Nudge a few last-quarter MRR values so NRR/GRR/top share hit targets."""
    # 1) Anchor account at ~14% of total MRR in the last quarter.
    others = sum(c["mrr"].get(END_Q, 0) for n, c in customers.items() if n != TOP_CUSTOMER)
    customers[TOP_CUSTOMER]["mrr"][END_Q] = (
        round(TOP_SHARE_TARGET * others / (1 - TOP_SHARE_TARGET) / 10) * 10
    )

    # 2) GRR: move capped MRR by adjusting accounts in contracting cohorts
    #    (each cohort stays strictly below its starting MRR).
    tab = cohort_table(customers)
    base, _, capped = nrr_grr(tab)
    gap = round(GRR_TARGET * base) - capped
    contracting = sorted(
        (c for c, row in tab.items() if c <= START_Q and row.get(END_Q, 0) < row.get(START_Q, 0)),
        key=lambda c: tab[c][END_Q] - tab[c][START_Q],
    )
    for c in contracting:
        if gap == 0:
            break
        room_up = tab[c][START_Q] - tab[c][END_Q] - 10
        acct = max(
            (n for n, x in customers.items() if x["cohort"] == c and END_Q in x["mrr"]),
            key=lambda n: customers[n]["mrr"][END_Q],
        )
        room_down = customers[acct]["mrr"][END_Q] - 100
        step = max(-room_down, min(gap, room_up))
        customers[acct]["mrr"][END_Q] += step
        gap -= step
    assert gap == 0, f"GRR calibration short by {gap}"

    # 3) NRR: adjust non-anchor accounts in expanding cohorts (each cohort stays
    #    at or above its starting MRR, so capped MRR - and GRR - is unchanged).
    tab = cohort_table(customers)
    base, now, capped_before = nrr_grr(tab)
    gap = round(NRR_TARGET * base) - now
    expanding = sorted(
        (c for c, row in tab.items() if c <= START_Q and row.get(END_Q, 0) > row.get(START_Q, 0)),
        key=lambda c: tab[c][START_Q] - tab[c][END_Q],
    )
    for c in expanding:
        if gap == 0:
            break
        accts = [
            n for n, x in customers.items() if x["cohort"] == c and END_Q in x["mrr"] and n != TOP_CUSTOMER
        ]
        if not accts:
            continue
        acct = max(accts, key=lambda n: customers[n]["mrr"][END_Q])
        room_down = min(customers[acct]["mrr"][END_Q] - 100, tab[c][END_Q] - tab[c][START_Q])
        step = max(-room_down, gap)
        customers[acct]["mrr"][END_Q] += step
        gap -= step
    assert gap == 0, f"NRR calibration short by {gap}"
    assert nrr_grr(cohort_table(customers))[2] == capped_before


def build_harbor():
    customers = simulate_customers()
    calibrate(customers)
    tab = cohort_table(customers)

    qs = list(range(N_Q))
    mrr = {t: sum(row.get(t, 0) for row in tab.values()) for t in qs}
    paying = {t: sum(1 for c in customers.values() if c["mrr"].get(t, 0) > 0) for t in range(-1, N_Q)}
    new = {t: NEW_LOGOS[t] for t in qs}
    churned = {t: paying[t - 1] + new[t] - paying[t] for t in qs}

    sub = {t: 3 * mrr[t] for t in qs}
    impl_projects = [0, 14000, 0, 9000, 0, 0, 18000, 0, 12000, 0, 22000]
    ps = {t: new[t] * 2500 + impl_projects[t] for t in qs}
    rev = {t: sub[t] + ps[t] for t in qs}
    hosting = {t: round(sub[t] * 0.085) + 7500 for t in qs}
    data = {t: round(sub[t] * 0.035) + 4200 for t in qs}
    cogs = {t: hosting[t] + data[t] for t in qs}
    gp = {t: rev[t] - cogs[t] for t in qs}

    hc_eng = [4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9]
    hc_gtm = [1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6]
    hc_sup = [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3]
    hc_adm = [1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2]

    def year_step(t: int) -> int:  # salary review every January
        return t // 4

    eng = {t: hc_eng[t] * (41000 + 1500 * year_step(t)) for t in qs}
    net_new_arr = {t: 12 * (mrr[t] - (mrr[t - 1] if t else 0)) for t in qs}
    gtm = {t: hc_gtm[t] * (31000 + 1200 * year_step(t)) + round(0.08 * max(net_new_arr[t], 0)) for t in qs}
    paid = {t: 12000 + 3500 * t for t in qs}
    support = {t: hc_sup[t] * (19500 + 900 * year_step(t)) for t in qs}
    admin = {t: hc_adm[t] * (26000 + 1000 * year_step(t)) + 7800 + 900 * t for t in qs}
    legal = {
        t: v for t, v in enumerate([8500, 31000, 9200, 9600, 14800, 10100, 10400, 10800, 16900, 11500, 27500])
    }
    opex = {t: eng[t] + gtm[t] + paid[t] + support[t] + admin[t] + legal[t] for t in qs}
    ebitda = {t: gp[t] - opex[t] for t in qs}
    headcount = {t: hc_eng[t] + hc_gtm[t] + hc_sup[t] + hc_adm[t] for t in qs}

    cash = {}
    bal = 1_180_000  # end of Q4 2023
    seed = {1: 2_750_000}  # seed extension closed Q2 2024 (not shown as a row)
    for t in qs:
        bal += ebitda[t] + seed.get(t, 0)
        cash[t] = bal

    lines = [
        ("Subscription ARR-recognized revenue", sub, usd),
        ("Professional services", ps, usd),
        ("Total Revenue", rev, usd),
        ("Hosting & infrastructure", hosting, usd),
        ("Third-party data costs", data, usd),
        ("Cost of revenue", cogs, usd),
        ("Gross profit", gp, usd),
        ("Engineering payroll", eng, usd),
        ("Go-to-market payroll", gtm, usd),
        ("Paid acquisition", paid, usd),
        ("Customer support team", support, usd),
        ("Admin & office", admin, usd),
        ("Legal and accounting", legal, usd),
        ("Total opex", opex, usd),
        ("EBITDA", ebitda, usd),
        ("Cash at quarter end", cash, usd),
        ("Paying customers (end of quarter)", paying, str),
        ("New logos", new, str),
        ("Churned logos", churned, str),
        ("Headcount", headcount, str),
    ]

    out = SAMPLES / "harbor-labs"
    out.mkdir(parents=True, exist_ok=True)
    rows = [["Line item"] + [qlabel(t) for t in qs]]
    for label, series, fmt in lines:
        rows.append([label] + [fmt(series[t]) for t in qs])
    write_csv(out / "financials_quarterly.csv", rows)

    crow = [["signup_quarter", "quarter", "mrr"]]
    for c in sorted(tab):
        for t in sorted(tab[c]):
            crow.append([qlabel(c), qlabel(t), tab[c][t]])
    write_csv(out / "cohort_mrr.csv", crow)

    last = sorted(
        ((n, c["mrr"][END_Q]) for n, c in customers.items() if END_Q in c["mrr"]), key=lambda x: (-x[1], x[0])
    )
    write_csv(
        out / "customer_mrr.csv", [["customer", "quarter", "mrr"]] + [[n, qlabel(END_Q), m] for n, m in last]
    )
    assert sum(m for _, m in last) == mrr[END_Q]
    assert len(last) == paying[END_Q]

    hdr = f"Synthetic fixture - generated by {GENERATOR}. Do not edit by hand.\nFictional company; any resemblance to a real business is coincidental."
    write_yaml(
        out / "profile.yaml",
        {
            "name": "Harbor Labs",
            "country": "US",
            "currency": "usd",
            "fiscal_year_start_month": 1,
            "stage": "seed",
            "round_type": "priced_equity",
            "round_size": 9000000,
            "business_model": "recurring",
            "granularity": "quarter",
            "city": "Columbus, Ohio",
            "founders": [
                {"name": "Priya Vandermolen", "role": "CEO"},
                {"name": "Tomas Okafor-Lind", "role": "CTO"},
            ],
            "one_liner": "Harbor Labs gives mid-market distributors one live view of every late, short or damaged shipment, so ops teams fix exceptions before customers call.",
            "synthetic": True,
        },
        hdr,
    )

    def m(src, field, unit, note):
        return {
            "source_column": src,
            "canonical_field": field,
            "unit": unit,
            "confidence": 0.95,
            "note": note,
        }

    write_yaml(
        out / "mapping.yaml",
        {
            "dataset": "financials_quarterly.csv",
            "layout": "wide",
            "transpose": True,
            "period_format": "Qn YYYY",
            "mappings": [
                m(
                    "Line item",
                    "period",
                    "quarter",
                    "wide layout: the quarter headers become the period column after transposition",
                ),
                m(
                    "Subscription ARR-recognized revenue",
                    "revenue.recurring",
                    "usd",
                    "recognized subscription revenue for the quarter (a quarterly flow, not ARR despite the label)",
                ),
                m("Professional services", "revenue.one_time", "usd", "onboarding and implementation fees"),
                m("Total Revenue", "revenue.total", "usd", "= Subscription + Professional services"),
                m("Hosting & infrastructure", None, "usd", "component of Cost of revenue"),
                m("Third-party data costs", None, "usd", "component of Cost of revenue"),
                m("Cost of revenue", "cogs", "usd", "= Hosting & infrastructure + Third-party data costs"),
                m("Gross profit", "gross_profit", "usd", "= Total Revenue - Cost of revenue"),
                m("Engineering payroll", "opex.r_and_d", "usd", "opex category"),
                m(
                    "Go-to-market payroll",
                    "opex.s_and_m",
                    "usd",
                    "opex category; summed with Paid acquisition",
                ),
                m(
                    "Paid acquisition",
                    "opex.s_and_m",
                    "usd",
                    "opex category; summed with Go-to-market payroll",
                ),
                m("Customer support team", "opex.customer_success", "usd", "opex category"),
                m("Admin & office", "opex.g_and_a", "usd", "opex category; summed with Legal and accounting"),
                m("Legal and accounting", "opex.g_and_a", "usd", "opex category; summed with Admin & office"),
                m("Total opex", "opex.total", "usd", "= sum of the six opex rows"),
                m(
                    "EBITDA",
                    "operating_income",
                    "usd",
                    "no D&A line, so EBITDA is operating income; = Gross profit - Total opex",
                ),
                m("Cash at quarter end", "cash_balance", "usd", "balance at quarter end"),
                m(
                    "Paying customers (end of quarter)",
                    "customers.count",
                    "count",
                    "end-of-quarter paying logos",
                ),
                m("New logos", "customers.new", "count", "logos signed in the quarter"),
                m("Churned logos", "customers.churned", "count", "logos lost in the quarter"),
                m("Headcount", "headcount.total", "count", "end-of-quarter FTEs"),
            ],
            "tables": [
                {
                    "file": "cohort_mrr.csv",
                    "kind": "cohorts",
                    "columns": ["signup_quarter", "quarter", "mrr"],
                    "note": "mrr = average monthly recurring revenue of the cohort in that quarter; sum over cohorts x 3 = Subscription ARR-recognized revenue",
                },
                {
                    "file": "customer_mrr.csv",
                    "kind": "per_customer_mrr",
                    "columns": ["customer", "quarter", "mrr"],
                    "note": "latest quarter only; sums to total MRR for that quarter",
                },
            ],
            "absent_fields": ["non_dilutive_income", "net_income", "depreciation", "bookings", "pipeline"],
        },
        hdr,
    )

    # ---- expected metrics -------------------------------------------------
    L, P, Y = END_Q, END_Q - 1, END_Q - 4
    lq, pq, yq = qlabel(L), qlabel(P), qlabel(Y)
    arr = sub[L] / 3 * 12
    mrr_v = sub[L] / 3
    growth = rev[L] / rev[P] - 1
    cqgr = (sub[L] / sub[Y]) ** 0.25 - 1
    gm = (rev[L] - cogs[L]) / rev[L]
    gm_cs = (rev[L] - cogs[L] - support[L]) / rev[L]
    q_burn = max(-ebitda[L], 0)
    burn = q_burn / 3
    runway = cash[L] / burn if burn else None
    nn_arr = 4 * (sub[L] - sub[P])
    burn_mult = q_burn / nn_arr
    base, now, capped = nrr_grr(tab)
    nrr, grr = now / base, capped / base
    top_share = last[0][1] / mrr[L]
    logo_churn = churned[L] / paying[P]
    s_and_m = gtm[L] + paid[L]
    g_and_a = admin[L] + legal[L]
    mix = {
        "opex.r_and_d": eng[L],
        "opex.s_and_m": s_and_m,
        "opex.customer_success": support[L],
        "opex.g_and_a": g_and_a,
    }

    def fig(value, unit, formula, inputs, display=None, period=lq):
        d = {"value": value, "unit": unit, "period": period, "formula": formula, "inputs": inputs}
        if display:
            d["display"] = display
        return d

    expected = {
        "company": "Harbor Labs",
        "currency": "usd",
        "granularity": "quarter",
        "latest_period": lq,
        "conventions": "ratios are decimals (0.08 = 8%); money in USD; flows are per-quarter unless noted; values rounded to 6 dp (ratios, months) or 2 dp (money)",
        "metrics": {
            "arr": fig(
                r2(arr),
                "usd",
                f"revenue.recurring[{lq}] / 3 * 12",
                {f"revenue.recurring[{lq}]": sub[L]},
                f"${arr:,.0f}",
            ),
            "mrr": fig(
                r2(mrr_v),
                "usd",
                f"revenue.recurring[{lq}] / 3",
                {f"revenue.recurring[{lq}]": sub[L]},
                f"${mrr_v:,.0f}",
            ),
            "revenue_growth_qoq": fig(
                r6(growth),
                "pct",
                f"revenue.total[{lq}] / revenue.total[{pq}] - 1",
                {f"revenue.total[{lq}]": rev[L], f"revenue.total[{pq}]": rev[P]},
                pct(growth),
            ),
            "cqgr_4q": fig(
                r6(cqgr),
                "pct",
                f"(revenue.recurring[{lq}] / revenue.recurring[{yq}]) ** (1/4) - 1",
                {f"revenue.recurring[{lq}]": sub[L], f"revenue.recurring[{yq}]": sub[Y]},
                pct(cqgr),
                period=f"{yq} to {lq}",
            ),
            "gross_margin": fig(
                r6(gm),
                "pct",
                f"(revenue.total[{lq}] - cogs[{lq}]) / revenue.total[{lq}]",
                {f"revenue.total[{lq}]": rev[L], f"cogs[{lq}]": cogs[L]},
                pct(gm),
            ),
            "gross_margin_incl_cs": fig(
                r6(gm_cs),
                "pct",
                f"(revenue.total[{lq}] - cogs[{lq}] - opex.customer_success[{lq}]) / revenue.total[{lq}]",
                {
                    f"revenue.total[{lq}]": rev[L],
                    f"cogs[{lq}]": cogs[L],
                    f"opex.customer_success[{lq}]": support[L],
                },
                pct(gm_cs),
            ),
            "burn": fig(
                r2(burn),
                "usd",
                f"max(-operating_income[{lq}], 0) / 3  (monthly; no non_dilutive_income to exclude)",
                {f"operating_income[{lq}]": ebitda[L]},
                f"${burn:,.0f}/mo",
            ),
            "runway_months": fig(
                r6(runway),
                "months",
                f"cash_balance[{lq}] / burn",
                {f"cash_balance[{lq}]": cash[L], "burn": r2(burn)},
                f"{runway:.1f} months",
            ),
            "burn_multiple": fig(
                r6(burn_mult),
                "x",
                f"max(-operating_income[{lq}], 0) / (4 * (revenue.recurring[{lq}] - revenue.recurring[{pq}]))  (quarterly net burn / net new ARR in the quarter)",
                {
                    f"operating_income[{lq}]": ebitda[L],
                    f"revenue.recurring[{lq}]": sub[L],
                    f"revenue.recurring[{pq}]": sub[P],
                    "net_new_arr": nn_arr,
                },
                f"{burn_mult:.2f}x",
            ),
            "nrr": fig(
                r6(nrr),
                "pct",
                f"sum over cohorts c with signup_quarter <= {yq} of mrr[c, {lq}] / sum of mrr[c, {yq}]",
                {f"base_mrr[{yq}]": base, f"same_cohorts_mrr[{lq}]": now},
                pct(nrr),
                period=f"{yq} to {lq}",
            ),
            "grr": fig(
                r6(grr),
                "pct",
                f"sum over cohorts c with signup_quarter <= {yq} of min(mrr[c, {lq}], mrr[c, {yq}]) / sum of mrr[c, {yq}]  (cohort-level cap: expansion within a cohort is excluded, cohorts are not netted against each other)",
                {f"base_mrr[{yq}]": base, "capped_mrr": capped},
                pct(grr),
                period=f"{yq} to {lq}",
            ),
            "top_customer_share": fig(
                r6(top_share),
                "pct",
                f"max customer mrr[{lq}] / sum of customer mrr[{lq}]",
                {"customer": last[0][0], "customer_mrr": last[0][1], "total_mrr": mrr[L]},
                pct(top_share),
            ),
            "logo_churn_rate": fig(
                r6(logo_churn),
                "pct",
                f"customers.churned[{lq}] / customers.count[{pq}]",
                {f"customers.churned[{lq}]": churned[L], f"customers.count[{pq}]": paying[P]},
                pct(logo_churn),
            ),
            "opex_mix": fig(
                {k: r6(v / opex[L]) for k, v in mix.items()},
                "pct",
                f"opex.<category>[{lq}] / opex.total[{lq}]",
                {**{f"{k}[{lq}]": v for k, v in mix.items()}, f"opex.total[{lq}]": opex[L]},
            ),
        },
        "must_be_missing": [
            {
                "id": "tax_credit_metrics",
                "needs": ["non_dilutive_income"],
                "reason": "non_dilutive_income is ABSENT: no tax-credit or grant row exists. Any tax-credit / grant / ex-credit metric (e.g. burn ex-credits, burn multiple ex-credits) must be a MissingFigure, never zero or an estimate.",
            },
        ],
    }
    write_yaml(out / "expected.yaml", expected, hdr)

    (out / "README.md").write_text(
        f"""# Harbor Labs sample data (synthetic)

**Fictional company. Synthetic numbers.** Harbor Labs, its founders and every customer name in
`customer_mrr.csv` are invented; any resemblance to a real business is coincidental.

## Purpose

Test fixture proving Vicky is startup-agnostic. Compared with the Tidewell sample it differs in
almost every dimension the ingestion and metrics engine care about:

| | Tidewell | Harbor Labs |
|---|---|---|
| Country / currency | CA / CAD | US / USD |
| Granularity | month | quarter (Q1 2024 to Q3 2026, 11 quarters) |
| Layout | long (one row per month) | **wide** (one row per line item, one column per quarter) |
| Column names | snake_case | spreadsheet-style labels, e.g. `Subscription ARR-recognized revenue` |
| Negatives | `-$5.00` | `(12,345)` |
| Tax credits | SR&ED row | **none** (no non-dilutive income at all) |
| Extra tables | none | `cohort_mrr.csv`, `customer_mrr.csv` |

## Files

| File | Content |
|---|---|
| `financials_quarterly.csv` | Wide P&L plus cash, customers and headcount. Totals equal their components; Gross profit = Total Revenue - Cost of revenue; EBITDA = Gross profit - Total opex; cash moves by EBITDA plus a seed extension in Q2 2024 (financing is not a P&L row). |
| `cohort_mrr.csv` | `signup_quarter,quarter,mrr`; cohorts from Q1 2023. `mrr` is the cohort's average monthly recurring revenue in that quarter, so the sum over cohorts x 3 equals the subscription revenue row. |
| `customer_mrr.csv` | `customer,quarter,mrr` for the latest quarter (Q3 2026); sums to total MRR and the row count equals paying customers. |
| `profile.yaml` | Company profile (`business_model: recurring`, `granularity: quarter`). |
| `mapping.yaml` | The correct column mapping (row labels become columns after transposition). |
| `expected.yaml` | Metric values the engine must reproduce, each with its exact formula and inputs. |

Tuned targets: NRR 108.0%, GRR 90.0% (cohort formula in `expected.yaml`), top customer about 14% of MRR.

## Regenerating

Do not edit these files by hand. They are written by `{GENERATOR}` (deterministic, seeded with
`random.Random(42)`):

```
{REGEN_CMD}
```
""",
        encoding="utf-8",
        newline="\n",
    )
    return expected


# --------------------------------------------------------------------------
# Services co (UK project studio, monthly, non-recurring)
# --------------------------------------------------------------------------


def build_services():
    months = [
        "Oct 2025",
        "Nov 2025",
        "Dec 2025",
        "Jan 2026",
        "Feb 2026",
        "Mar 2026",
        "Apr 2026",
        "May 2026",
        "Jun 2026",
        "Jul 2026",
        "Aug 2026",
        "Sep 2026",
    ]
    revenue = [38400, 44150, 29800, 31250, 47600, 52300, 36900, 41750, 49200, 33600, 30150, 45900]
    contractor_pct = [0.31, 0.34, 0.22, 0.27, 0.36, 0.38, 0.29, 0.33, 0.35, 0.26, 0.24, 0.33]
    contractors = [round(r * p / 10) * 10 for r, p in zip(revenue, contractor_pct, strict=True)]
    # Four staff incl. the two directors; pay review in April (fiscal year start).
    salaries = [19600] * 6 + [20850] * 6
    rent = [4350, 4350, 4980, 4350, 4350, 4420, 4610, 4610, 4610, 4610, 4610, 4795]
    net = [r - c - s - o for r, c, s, o in zip(revenue, contractors, salaries, rent, strict=True)]
    bank, bal = [], 57_300  # end of Sep 2025
    dividends = {2: 9000, 5: 9000, 8: 9000, 11: 9000}  # quarterly director dividends
    for i, n in enumerate(net):
        bal += n - dividends.get(i, 0)
        bank.append(bal)

    out = SAMPLES / "services-co"
    out.mkdir(parents=True, exist_ok=True)
    rows = [
        [
            "Month",
            "Project revenue",
            "Contractor costs",
            "Salaries",
            "Rent & overheads",
            "Net profit",
            "Bank balance",
        ]
    ]
    for i, mo in enumerate(months):
        rows.append(
            [
                mo,
                gbp(revenue[i]),
                gbp(contractors[i]),
                gbp(salaries[i]),
                gbp(rent[i]),
                gbp(net[i]),
                gbp(bank[i]),
            ]
        )
    write_csv(out / "projects_monthly.csv", rows)

    hdr = f"Synthetic fixture - generated by {GENERATOR}. Do not edit by hand.\nFictional company; any resemblance to a real business is coincidental."
    write_yaml(
        out / "profile.yaml",
        {
            "name": "Northwind Studio Ltd",
            "country": "GB",
            "currency": "gbp",
            "fiscal_year_start_month": 4,
            "stage": "other",
            "round_type": "none",
            "round_size": 0,
            "business_model": "other",
            "granularity": "month",
            "city": "Bristol",
            "founders": [
                {"name": "Imogen Ashcombe", "role": "Creative Director"},
                {"name": "Rafe Delacourt-Nwosu", "role": "Managing Director"},
            ],
            "one_liner": "Northwind Studio is a four-person brand and web design studio that builds marketing sites for regional food and drink producers, billed per project.",
            "synthetic": True,
        },
        hdr,
    )

    def m(src, field, unit, note):
        return {
            "source_column": src,
            "canonical_field": field,
            "unit": unit,
            "confidence": 0.95,
            "note": note,
        }

    write_yaml(
        out / "mapping.yaml",
        {
            "dataset": "projects_monthly.csv",
            "layout": "long",
            "transpose": False,
            "period_format": "Mon YYYY",
            "mappings": [
                m("Month", "period", "month", "one row per month"),
                m(
                    "Project revenue",
                    "revenue.total",
                    "gbp",
                    "all revenue is one-off project fees; there is no recurring revenue, so the SaaS metric set stays off",
                ),
                m(
                    "Contractor costs",
                    "cogs",
                    "gbp",
                    "freelancers billed directly to client projects (direct cost of delivery)",
                ),
                m(
                    "Salaries",
                    "opex.other",
                    "gbp",
                    "opex category; staff split across delivery and admin, not separable",
                ),
                m("Rent & overheads", "opex.g_and_a", "gbp", "opex category"),
                m(
                    "Net profit",
                    "net_income",
                    "gbp",
                    "= Project revenue - Contractor costs - Salaries - Rent & overheads (pre-tax)",
                ),
                m(
                    "Bank balance",
                    "cash_balance",
                    "gbp",
                    "month-end balance; also moves by quarterly director dividends (not a P&L row)",
                ),
            ],
            "absent_fields": [
                "revenue.recurring",
                "revenue.one_time",
                "gross_profit",
                "opex.total",
                "operating_income",
                "non_dilutive_income",
                "customers.count",
                "customers.new",
                "customers.churned",
                "headcount.total",
            ],
        },
        hdr,
    )

    L, P = 11, 10
    lm, pm = months[L], months[P]
    growth = revenue[L] / revenue[P] - 1
    gm = (revenue[L] - contractors[L]) / revenue[L]
    profit = net[L]
    burn = max(-net[L], 0)
    opex_l = salaries[L] + rent[L]

    def fig(value, unit, formula, inputs, display=None, period=lm):
        d = {"value": value, "unit": unit, "period": period, "formula": formula, "inputs": inputs}
        if display:
            d["display"] = display
        return d

    metrics = {
        "revenue_growth_mom": fig(
            r6(growth),
            "pct",
            f"revenue.total[{lm}] / revenue.total[{pm}] - 1",
            {f"revenue.total[{lm}]": revenue[L], f"revenue.total[{pm}]": revenue[P]},
            pct(growth),
        ),
        "gross_margin": fig(
            r6(gm),
            "pct",
            f"(revenue.total[{lm}] - cogs[{lm}]) / revenue.total[{lm}]",
            {f"revenue.total[{lm}]": revenue[L], f"cogs[{lm}]": contractors[L]},
            pct(gm),
        ),
        "burn": fig(
            r2(burn),
            "gbp",
            f"max(-net_income[{lm}], 0)  (monthly; no non_dilutive_income to exclude)",
            {f"net_income[{lm}]": net[L]},
            f"£{burn:,.0f}/mo",
        ),
        "net_profit": fig(r2(profit), "gbp", f"net_income[{lm}]", {f"net_income[{lm}]": net[L]}, gbp(profit)),
        "opex_mix": fig(
            {"opex.other": r6(salaries[L] / opex_l), "opex.g_and_a": r6(rent[L] / opex_l)},
            "pct",
            f"opex.<category>[{lm}] / (opex.other[{lm}] + opex.g_and_a[{lm}])  (no opex.total row; total = sum of categories)",
            {f"opex.other[{lm}]": salaries[L], f"opex.g_and_a[{lm}]": rent[L]},
        ),
    }
    if burn:
        metrics["runway_months"] = fig(
            r6(bank[L] / burn),
            "months",
            f"cash_balance[{lm}] / burn",
            {f"cash_balance[{lm}]": bank[L], "burn": burn},
        )
    expected = {
        "company": "Northwind Studio Ltd",
        "currency": "gbp",
        "granularity": "month",
        "latest_period": lm,
        "conventions": "ratios are decimals; money in GBP; flows are per-month; generic metric set only",
        "profitable_latest_period": burn == 0,
        "metrics": metrics,
        "runway_note": None
        if burn
        else f"profitable in {lm} (burn = 0): runway is not applicable and must not be reported as a finite number",
        "must_be_missing_saas": ["arr", "mrr", "nrr", "grr", "cac_payback", "burn_multiple", "magic_number"],
        "must_be_missing_saas_reason": "business_model is 'other' and no revenue.recurring column exists, so the recurring metric set never activates",
        "also_missing": [
            {"id": "top_customer_share", "needs": ["per_customer_mrr"], "reason": "no per-customer table"},
            {
                "id": "gross_margin_incl_cs",
                "needs": ["opex.customer_success"],
                "reason": "no customer-success cost line",
            },
            {
                "id": "tax_credit_metrics",
                "needs": ["non_dilutive_income"],
                "reason": "no grant or tax-credit row",
            },
        ],
    }
    write_yaml(out / "expected.yaml", expected, hdr)

    (out / "README.md").write_text(
        f"""# Northwind Studio sample data (synthetic)

**Fictional company. Synthetic numbers.** Northwind Studio Ltd and its directors are invented;
any resemblance to a real business is coincidental.

## Purpose

The smallest possible non-SaaS fixture: a UK project-based design studio (GBP, monthly, fiscal
year starting in April). It has no recurring revenue, customers or cohort data, so Vicky must
compute **only** the generic metric set (revenue growth, gross margin, burn or profit, runway if
burning, opex mix) and return `MissingFigure` for every SaaS metric (ARR, MRR, NRR, GRR, CAC
payback, burn multiple, magic number). In the latest month the studio is profitable, which
exercises the "burn = 0, no runway" branch.

## Files

| File | Content |
|---|---|
| `projects_monthly.csv` | Long layout, Oct 2025 to Sep 2026: `Month, Project revenue, Contractor costs, Salaries, Rent & overheads, Net profit, Bank balance`. Amounts like `£12,345`, negatives `-£1,234`. Net profit = revenue - contractors - salaries - rent; bank balance moves by net profit less quarterly director dividends. |
| `profile.yaml` | Company profile (`business_model: other`, `granularity: month`). |
| `mapping.yaml` | The correct column mapping. |
| `expected.yaml` | Generic metric values with formulas, plus the list of metrics that must be missing. |

## Regenerating

Do not edit these files by hand. They are written by `{GENERATOR}` (deterministic):

```
{REGEN_CMD}
```
""",
        encoding="utf-8",
        newline="\n",
    )
    return expected


def main() -> None:
    h = build_harbor()
    s = build_services()
    for name, exp in (("harbor-labs", h), ("services-co", s)):
        print(f"[{name}] latest {exp['latest_period']}")
        for k, v in exp["metrics"].items():
            print(f"  {k:24s} {v.get('display', v['value'])}")


if __name__ == "__main__":
    main()
