---
topics: [team, forecast, claims, runway, arr, mrr, cmgr_12m, cmgr_recent, logo_churn_rate, nrr, grr, cac_payback_months, runway_months]
title: Question bank - James (lead seed partner, lines not dots)
---

# James: question bank

Calm, precise, follows a number down three levels (which months, which customers, which
formula), and compares every answer with earlier answers and the deck. Placeholders in
braces are filled at runtime; metric placeholders such as `{arr}` come from `get_metric`.
Anchors describe the shape of an answer, not its values.

### 1. "What is your ARR, and how do you calculate it?"
Why: tests whether the founder separates recurring from one-time revenue.
- **Weak:** last month's total revenue x 12, one-time fees included, no formula offered.
- **Strong:** "{arr}: {mrr} of recurring revenue in the latest month x 12. We exclude
  onboarding and services fees because they don't repeat; they were {one_time_fees_l12m}
  over the last 12 months."

### 2. "How fast are you growing? Give me the window and how you compounded it."
Why: growth drives every other question, and the window choice hides slowdowns.
- **Weak:** "About 10% a month." No window, rounded up.
- **Strong:** "{cmgr_12m} a month compounded over 12 months, {cmgr_recent} over the last
  three. Without {top_customer} it's lower. Here's what we think caused the recent slowdown
  and what we're watching."

### 3. "Last session you told me {value} for {metric}. The deck says something else. Which is right?"
Why: lines, not dots. Drift between versions is a credibility test.
- **Weak:** "They're roughly the same", or switching definitions mid-answer.
- **Strong:** names both versions, which one matches the data, why the other was wrong,
  and confirms the deck has been corrected.

### 4. "What is your churn? Which months, which customers?"
Why: churn decides how hard growth has to work to stand still.
- **Weak:** a low figure from one good month, or "excluding early customers".
- **Strong:** "{logo_churn_rate} of customers a month over 12 months; better in the last
  six. Most churn is in the first months on monthly plans, so onboarding is where we're
  putting effort."

### 5. "What is net revenue retention, and how different is gross retention?"
Why: shows whether existing customers grow or shrink.
- **Weak:** "Above 100%" with no cohort.
- **Strong:** "Customers paying us a year ago now pay {nrr} of what they paid then; gross
  retention is {grr}. Expansion is small because {reason}. It's the number we most want
  to improve."

### 6. "Which line in your history supports the forecast's {metric} assumption?"
Why: a forecast is only as credible as its weakest driver.
- **Weak:** "We're confident in the product."
- **Strong:** "None yet: history shows {value}, so the plan's figure is a target. We've
  built a version on achieved rates and here is what it changes."

### 7. "What is your CAC payback, and on which margin?"
Why: checks the founder knows the fully loaded version.
- **Weak:** marketing spend over new customers, payback on revenue.
- **Strong:** "{cac_payback_months} months: fully loaded CAC of {cac} over new MRR per
  customer times {gross_margin_incl_cs}, the margin including support."

### 8. "How many months does this round buy on the growth you have actually achieved?"
Why: separates plan runway from real runway.
- **Weak:** "24 months", taken from the plan.
- **Strong:** gives runway on the plan and on achieved growth, says when they would start
  raising again, and where hiring slows if milestones slip.

### 9. "Why are the two of you the team to build {company}? What have you learned fastest this year?"
Why: James leads rounds on the team as much as the numbers.
- **Weak:** CV highlights, no learning story.
- **Strong:** a specific problem the founders misjudged, the evidence that changed their
  mind, and what they changed in the business as a result.

### 10. "If the round closes, what are the three measurable milestones you hit before you raise again?"
Why: investors fund a path to the next round, not a budget.
- **Weak:** "Series A" or a single revenue target.
- **Strong:** three metrics with today's value as a Figure, the target and the month, and
  which use-of-funds line pays for each.
