# Northwind Studio sample data (synthetic)

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

Do not edit these files by hand. They are written by `backend/scripts/make_fixtures.py` (deterministic):

```
uv run --with openpyxl python backend/scripts/make_fixtures.py
```
