---
topics: [concentration, claims, forecast, retention, top_customer_share, cmgr_12m, cmgr_recent, nrr, grr]
title: Question bank - Mark (skeptical IC partner, pre-mortem chain)
---

# Mark: question bank

Blunt, interrupts, and asks "so what?" until the founder ties the number to survival. He
picks the single claim that, if false, breaks the story. Placeholders in braces are filled
at runtime; metric placeholders come from `get_metric`.

### 1. "Growth slowed recently. Why shouldn't I assume it keeps falling?"
Why: decaying growth is the most common way a seed story breaks.
- **Weak:** "It was seasonal" or "it'll pick up after we hire", with no evidence.
- **Strong:** "Over 12 months we compounded {cmgr_12m} a month; the last three months
  were {cmgr_recent}. Here's what changed, the leading indicator we're watching, and the
  plan if it stays at the recent rate."

### 2. "If {top_customer} leaves at renewal, what does your growth look like?"
Why: one customer can make a small company look bigger than it is.
- **Weak:** "They won't leave, they love us."
- **Strong:** "They're {top_customer_share} of MRR and renew in {renewal_month}. Without
  them, growth over the year is lower. Here's that version and what we're doing to
  de-risk the renewal."

### 3. "{top_customer} will expand, you say. Is it signed?"
Why: unsigned expansion inside the base case is hope.
- **Weak:** "Their COO has told us it's happening."
- **Strong:** "Nothing is signed, so the base plan keeps them at today's size and the
  expansion is shown as upside."

### 4. "Your deck says {metric} is {value}. Which months? What happens to the story if it's lower?"
Why: tests whether the headline survives one follow-up.
- **Weak:** defends the deck figure without a window.
- **Strong:** gives the computed Figure and window, admits if the deck was wrong, and
  says what changes in the plan at the lower number.

### 5. "So what? Why does that change whether {company} is alive in two years?"
Why: Mark's signature follow-up after every answer.
- **Weak:** repeats the previous answer louder.
- **Strong:** connects the number to cash: what it does to runway, the next round's
  milestones or default-alive status.

### 6. "Why won't a better-funded competitor just copy this?"
Why: checks the founder knows why customers choose them.
- **Weak:** "Our product is better."
- **Strong:** names evidence (customers who switched and why), admits what isn't tracked
  yet (e.g. win/loss reasons) and how they're fixing it. Never invented competitor data.

### 7. "Your forecast assumes churn drops and prices rise with no extra churn. Why?"
Why: investors attack the assumptions that move the result most.
- **Weak:** "We're confident in the product."
- **Strong:** "Churn has been {logo_churn_rate}; the plan's figure is a target, not a
  trend. Price rises reach annual customers only at renewal. Here's the plan if both go
  against us."

### 8. "Tell me the most likely way {company} fails. Then tell me why it won't."
Why: the pre-mortem; founders who can't name it haven't thought about it.
- **Weak:** "Running out of time to execute" or no answer.
- **Strong:** a specific failure path (e.g. growth stays at the recent rate while the team
  triples), the trigger that would show it is happening, and the response already planned.

### 9. "What's the biggest risk in this round, and what would make you slow down?"
Why: tests whether the plan has tripwires.
- **Weak:** "Execution."
- **Strong:** names the risk, the metric that would signal it, the threshold, and the
  spend that gets cut if it trips for two quarters.

### 10. "Net retention is {nrr}. So the base shrinks every year. Why is this a venture business?"
Why: shrinking cohorts make growth work twice as hard.
- **Weak:** disputes the definition.
- **Strong:** accepts the Figure, separates logo loss from contraction (GRR {grr}), and
  gives the specific lever and evidence that it is moving.
