---
topics: [terms_cap_table, governance]
title: Term-sheet and SAFE mechanics
---

# Term-sheet and SAFE mechanics

> **This explains how terms work mechanically. It is not advice on which terms, round
> size or valuation to accept.** Every example below uses illustrative round numbers, not
> market data or a suggestion. The founder's own outcome must be computed by the Terms
> kit from the founder's inputs, and a lawyer should review any real document.

## 1. SAFEs (simple agreement for future equity)

A SAFE is cash now for shares later. It converts automatically when the company sells
preferred shares in a priced round. YC's post-money SAFE comes in standard versions:
valuation cap (no discount), discount (no cap), and MFN (no cap or discount). YC's
Canadian form is cap-only. Source: https://www.ycombinator.com/documents

- **Post-money valuation cap:** the SAFE holder's ownership is fixed at
  `investment / post-money cap`, measured on the company's capitalization *before* the new
  priced-round money. Capitalization counts existing shares, options, the existing pool
  and all converting SAFEs, but not a new or increased pool created in the priced round.
  Consequence: each additional SAFE dilutes the founders and earlier holders, not the
  other post-money SAFE holders.
- **Discount:** the SAFE converts at a price below the priced-round price, e.g. a 20%
  discount converts at 80% of the round price per share.
- **Cap and discount together** (custom or older forms): converts at whichever price
  gives the holder more shares (the lower price).
- **MFN (most favoured nation):** no cap or discount of its own; if the company later
  issues SAFEs on better terms, the MFN holder can take those terms.
- **Pro rata side letter:** a separate letter giving the SAFE holder the right to buy
  into the priced round. Check whether any were signed.

### Worked example (generic, illustrative numbers)

Before the round: founders hold 9,000,000 shares and the option pool holds 1,000,000:
10,000,000 total. Two post-money cap SAFEs are outstanding:

| SAFE | Investment | Post-money cap | Ownership before new money |
|---|---|---|---|
| A | $1,000,000 | $10,000,000 | 1.0 / 10 = 10% |
| B | $500,000 | $10,000,000 | 0.5 / 10 = 5% |

1. Existing shares are the remaining 85%, so capitalization including SAFE shares is
   `10,000,000 / 0.85 = 11,764,706`.
2. SAFE price = `cap / capitalization = 10,000,000 / 11,764,706 = $0.85`.
3. SAFE A gets `1,000,000 / 0.85 = 1,176,471` shares; SAFE B gets `588,235`.
4. Priced round: a new investor puts in $3,000,000 at a $15,000,000 pre-money valuation,
   with the pre-money share count including the converted SAFEs and no pool increase.
   Round price = `15,000,000 / 11,764,706 = $1.275`. The SAFEs' $0.85 is lower, so the
   cap applies.
5. New investor shares = `3,000,000 / 1.275 = 2,352,941`. Post-round total = 14,117,647.

| Holder | Shares | Ownership after round |
|---|---|---|
| Founders | 9,000,000 | 63.75% |
| Option pool | 1,000,000 | 7.08% |
| SAFE A | 1,176,471 | 8.33% |
| SAFE B | 588,235 | 4.17% |
| New investor | 2,352,941 | 16.67% |

Check: SAFE A's 10% is diluted by the new money in the ratio pre/post = 15/18, giving
8.33%. Discount version: a $500,000 SAFE with a 20% discount in a round priced at $1.00
converts at $0.80, into 625,000 shares.

## 2. Priced round basics

- **Pre-money / post-money:** `post = pre + new money`; investor ownership =
  `new money / post`. Price per share = `pre-money / pre-money fully diluted shares`.
  What counts as "fully diluted" (options, pool, converting SAFEs and notes) is
  negotiated and changes the price.
- **Preferred shares** carry rights common shares do not: liquidation preference,
  anti-dilution, protective provisions (investor consent for certain decisions), board
  seats, information rights, pro rata. US model documents: NVCA. Canadian and UK deals use
  different forms.

## 3. Liquidation preference

Decides who is paid first on a sale. Example: investor paid $3,000,000 for 20%.

| Exit value | 1x non-participating | 1x participating |
|---|---|---|
| $6,000,000 | Investor takes the greater of $3.0M or 20% x $6M = $1.2M, so $3.0M. Common: $3.0M | $3.0M back, then 20% of the remaining $3.0M = $0.6M, so $3.6M. Common: $2.4M |
| $60,000,000 | Converts: 20% x $60M = $12.0M. Common: $48.0M | $3.0M + 20% x $57M = $14.4M. Common: $45.6M |

- **Non-participating:** investor chooses preference *or* conversion.
- **Participating:** investor gets the preference *and* a share of the rest ("double
  dip"); sometimes capped at a multiple.
- **Multiples (2x, 3x)** and **seniority** (later series paid before earlier) stack on top
  and matter most at modest exits. Always run the waterfall at a low, middle and high exit.

## 4. Anti-dilution

Protects investors if a later round is priced below theirs (a down round) by lowering
their conversion price. Example: Series A bought 2,000,000 shares at $1.00; 10,000,000
shares outstanding on a fully diluted basis; a later round sells 1,000,000 shares at $0.50
($500,000).

- **Full ratchet:** conversion price drops to the new price, $0.50. The A holder's
  2,000,000 shares now convert into 4,000,000 common. The extra 2,000,000 shares come from
  everyone else, mostly founders and employees.
- **Broad-based weighted average:** `CP2 = CP1 x (A + B) / (A + C)` where A = fully
  diluted shares before the issue, B = shares the new money would buy at CP1, C = shares
  actually issued. `CP2 = 1.00 x (10,000,000 + 500,000) / (10,000,000 + 1,000,000) =
  $0.9545`, so the 2,000,000 shares convert into about 2,095,238.
- **Narrow-based** weighted average uses a smaller A (e.g. outstanding shares only), so
  the adjustment is larger than broad-based.

## 5. Option pool shuffle

If the new investor requires the pool to be created or topped up *before* the round
(inside the pre-money), the new pool shares dilute only existing holders.

Example: $3,000,000 at $12,000,000 pre-money ($15,000,000 post), with an unissued pool
equal to 10% of post-money created in the pre-money. Investor 20%, pool 10%, existing
holders 70%. If the pool were instead added after the round, existing holders would keep
72% (80% x 90%) and the investor 18%. The pre-money effectively available to existing
holders is $12,000,000 minus the $1,500,000 pool, $10,500,000. The question to ask: how
big a pool does the hiring plan actually need?

## 6. Pro rata rights

The right (not the obligation) to buy enough of a future round to keep the same
ownership percentage. Often limited to "major investors" above a threshold. Many pro
rata promises across SAFE side letters can crowd out the next lead; keep a list.

## 7. Strategic-investor terms and side letters

| Term | What it does | What it can cost |
|---|---|---|
| Right of first refusal (ROFR) on a sale of the company | The strategic can match any acquisition offer | Other buyers may not bid if they expect to be matched; can lower or chill exit offers |
| Right of first notice / negotiation | Must be told of, or negotiate first on, a sale | Lighter than ROFR, still slows a process and signals |
| Exclusivity (channel, segment, geography) | Company cannot partner with competitors of the strategic | Limits other channels and partners; may conflict with existing partner contracts |
| Data-sharing side letter | Strategic receives customer or usage data | May breach customer contracts or privacy commitments; hands data to a possible competitor |
| Information rights / board observer | Regular financials; observer in board meetings | Competitive information flows to a company in the same market |

Note: a ROFR on *share transfers* (company or investors can buy shares a founder wants to
sell) is common and different from a ROFR on *selling the whole company*.

## How the panel uses this

- Xenophon (and any investor on the panel) floats terms; the founder should compute the outcome with the Terms
  kit and name the question to ask their lawyer.
- No agent says whether a term is acceptable, what it should be, or what the company is
  worth. See `valuation-decline.md`.
