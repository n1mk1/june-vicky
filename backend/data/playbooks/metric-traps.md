---
topics: [claims, forecast, retention, unit_economics, arr, mrr, cmgr_12m, cmgr_recent, gross_margin, gross_margin_incl_cs, burn, burn_multiple, nrr, grr, cac, cac_payback_months, logo_churn_rate, magic_number]
title: Metric traps investors check first
---

# Metric traps investors check first

Each trap below is a way a founder's headline number differs from the number an investor
will compute. For each: what the founder says, what the investor computes, how to spot it
in the data, and what a strong answer does. Values always come from `get_metric` or
`check_claim`; this playbook only explains definitions.

## 1. ARR that includes one-time fees (`arr`, `mrr`)

- **Founder says:** last month's total revenue x 12.
- **Investor computes:** recurring revenue only (subscriptions), x 12. Onboarding,
  setup, implementation, hardware and services fees are excluded because they do not repeat.
- **Spot it:** revenue lines tagged one-time or services; a gap between `arr` and
  total revenue x 12.
- **Strong answer:** states ARR as MRR x 12, names what was left out and how much it
  was over the last 12 months.

## 2. Growth rate on a flattering window (`cmgr_12m`, `cmgr_recent`)

- **Founder says:** one monthly growth figure, often the best month or a rounded-up average.
- **Investor computes:** compounded monthly growth rate,
  `CMGR = (MRR_end / MRR_start) ^ (1 / months) - 1`, over 12 months *and* over the most
  recent 3 months. A falling recent rate is the first thing a skeptic attacks.
- **Also checks:** how much of the growth came from one large customer; growth with that
  customer removed.
- **Spot it:** `cmgr_recent` well below `cmgr_12m`; one month with a step change.
- **Strong answer:** gives both windows, says which one the forecast uses and why, and
  explains the slowdown with evidence rather than optimism.

## 3. Gross margin that excludes support (`gross_margin`, `gross_margin_incl_cs`)

- **Founder says:** margin after hosting and payment fees only.
- **Investor computes:** margin after all cost of delivering the service, including
  customer support / customer success staff, onboarding staff and third-party tools used
  to serve customers.
- **Spot it:** a large gap between `gross_margin` and `gross_margin_incl_cs`; support
  salaries sitting in operating expenses.
- **Strong answer:** gives both, says which one is the comparable figure, and uses the
  support-inclusive margin in CAC payback.

## 4. Burn that nets off tax credits or grants (`burn`, `runway_months`, `burn_multiple`)

- **Founder says:** monthly burn after counting R&D tax-credit refunds or grants as income.
- **Investor computes:** net burn from operations, excluding non-dilutive income, because
  refunds are lumpy, arrive after a filing and review, and can be reduced or delayed.
- **Burn multiple:** `net burn / net new ARR` over the same period (David Sacks'
  definition; cite via `cite_source`). Show it with and without the credits.
- **Spot it:** large one-off receipts in other income; runway that changes a lot when
  the refund is removed.
- **Strong answer:** quotes burn and runway with and without credits, names when the
  next refund is expected and what happens if it is late.

## 5. NRR quoted without GRR (`nrr`, `grr`)

- **Founder says:** "net retention above 100%" from a few expanding accounts, or with new
  customers mixed in.
- **Investor computes:** take the customers paying a year ago (one cohort); revenue
  from that same set today divided by their revenue then. NRR includes expansion;
  GRR caps each customer at their starting revenue, so it only shows losses.
- **Spot it:** no cohort table; NRR computed on total revenue; a big gap between NRR and
  GRR driven by one account.
- **Strong answer:** gives both by cohort, names the driver of the gap, and says what is
  being done about the weaker one.

## 6. CAC and payback on marketing spend only (`cac`, `cac_payback_months`, `magic_number`)

- **Founder says:** ad spend divided by new customers.
- **Investor computes:** fully loaded CAC = all sales and marketing cost (salaries,
  commissions, tools, programs) over the period / new customers in the period.
  Payback = CAC / (new MRR per customer x gross margin incl. support).
- **Spot it:** sales salaries not in the CAC numerator; payback computed on revenue rather
  than margin; payback on the booked margin instead of the support-inclusive one.
- **Strong answer:** shows the fully loaded inputs, the margin used, and the result.

## 7. Logo churn vs revenue churn (`logo_churn_rate`, `grr`)

- **Founder says:** whichever churn number looks better, often a recent month, or churn
  "excluding early customers".
- **Investor computes:** logo churn (customers lost / customers at start, monthly) and
  revenue churn (MRR lost / MRR at start) over 12 months and recently. Monthly churn
  compounds: annual retention is about `(1 - monthly churn) ^ 12`.
- **Spot it:** the deck figure matches no window in the data; small customers churning
  while large ones stay (or the reverse).
- **Strong answer:** gives both measures and windows, says where churn concentrates
  (plan type, tenure, segment) and what is being done.

## 8. Forecast stated as fact (`forecast`)

- **Founder says:** "we will reach X" or quotes a plan figure as if it had happened.
- **Investor computes:** nothing new; they ask which historical line supports each
  driver (rep ramp, churn, price rise, expansion, conversion).
- **Spot it:** `check_claim` returns `forecast_as_fact`; forecast drivers better than any
  month of history; unsigned expansion inside the base case.
- **Strong answer:** labels plan figures as plan, ties each driver to history, and shows
  a downside case built on achieved rates.

## Rules for Vik and the panel

- Quote the founder's figure and the computed Figure side by side; never "correct" with
  a number that is not a Figure.
- If the input needed for a metric is missing, say which data would fill the gap
  (`list_missing_data`), never estimate.
- Benchmarks only through `cite_source`. If none exists for the company's stage and model,
  say so.
