---
topics: [claims, forecast, market, team, product_tech, runway, arr, mrr, cmgr_12m, cmgr_recent, nrr, logo_churn_rate, burn, runway_months]
title: Deck heuristics, slide by slide
---

# Deck heuristics, slide by slide

What an investor checks on each slide of a seed deck, which claims need a figure, and how
to show history versus forecast. Use with the deck pre-scan: every extracted claim goes
through `check_claim`.

## Slide by slide

| Slide | What investors check | Claims that need a figure (and source) |
|---|---|---|
| Title / one-liner | Can a stranger say what the company does after one sentence? | None, but no superlatives ("leading", "#1") without evidence |
| Problem | Is it a specific, frequent, costly problem for a named customer type? | Cost of the problem (time, money) with a source or customer evidence |
| Solution / product | What does it do today (not the roadmap)? Screens of the real product | "Saves X hours", "Y% faster": measured where, on how many customers |
| Why now | What changed (technology, regulation, behaviour) that makes this possible now | Any market shift quoted needs a source |
| Market | Bottom-up: number of target customers x units x price, each input sourced | TAM/SAM/SOM; a top-down report figure alone is a red flag |
| Competition | Honest map including incumbents and "do nothing"; why customers switch | Win/loss evidence; if none is tracked, say so |
| Business model | Who pays, how much, how often; recurring vs one-time | Price points, contract length, share of revenue that recurs |
| Traction | Recurring revenue trend, growth over stated windows, retention, logos | ARR (recurring only), CMGR with window, churn with window, NRR/GRR by cohort |
| Go-to-market | Channel mix, who sources and who closes, rep ramp | CAC (fully loaded), payback, share of revenue by channel |
| Team | Why this team for this problem; gaps and the hiring plan | Prior results stated factually |
| Financials | History and forecast clearly separated; burn and runway | Burn (with and without credits), runway in months, forecast drivers |
| Ask / use of funds | Round size, what it buys, milestones for the next round | Months of runway on achieved growth; three measurable milestones |

## Claims that always need a figure

- Any growth word: "fast", "strong", "accelerating", "doubled". Needs the rate, the
  window and the base.
- Retention words: "customers love us", "sticky", "low churn". Needs churn and/or
  NRR/GRR with window.
- Efficiency words: "capital efficient", "low CAC", "high margin". Needs the metric and
  its definition (fully loaded, incl. support).
- Size words: "huge market", "billion-dollar opportunity". Needs a sourced bottom-up build.
- Comparatives: "better than", "faster than", "cheaper than" a competitor. Needs evidence
  or customer quotes with attribution.
- Benchmarks: "above industry average". Needs a named source (`cite_source`), or remove it.

## Historical vs forecast

- Separate them visually: solid line for actuals, dashed for forecast, with a vertical
  "today" marker. Label every chart "Actual" or "Forecast" in the title.
- Every forecast figure on a slide is labelled as forecast with the month it refers to.
  Never mix an actual month and a plan month in one number.
- Show the forecast drivers next to the history they come from: rep ramp, churn, price,
  expansion, conversion. If a driver is better than any month of history, say why.
- Include a downside case built on achieved rates and say where spending would slow.
- Unsigned expansion and pipeline belong in upside, not in the base case.

## Common deck failures the panel will attack

- A metric whose definition on the slide differs from the spreadsheet (Aristotle).
- A headline number that collapses after one follow-up (Socrates).
- A benchmark with no source (any investor).
- Runway quoted on plan growth, or burn net of tax credits (Plato).
- A market size with no bottom-up build (Xenophon).
- Product claims that are really custom work for one customer (Thales).
