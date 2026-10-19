# Harbor Labs sample data (synthetic)

**Fictional company. Synthetic numbers.** Harbor Labs, its founders and every customer name in
`customer_mrr.csv` are invented; any resemblance to a real business is coincidental.

## Purpose

Test fixture proving Vik is startup-agnostic. Compared with the Tidewell sample it differs in
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

Do not edit these files by hand. They are written by `backend/scripts/make_fixtures.py` (deterministic, seeded with
`random.Random(42)`):

```
uv run --with openpyxl python backend/scripts/make_fixtures.py
```
