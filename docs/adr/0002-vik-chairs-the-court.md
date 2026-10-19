# ADR 0002 — Vik chairs the court; five philosopher investors; knowledge checks

**Status:** accepted, built · **Date:** 2026-10-18 · **Revised:** 2026-10-18, 2026-10-19 (see [Revisions](#revisions)) · **Code:** `backend/vik/court/` (`session.py`, `knowledge.py`, `review.py`, `referee.py`), `backend/vik/llm/minds.py`, migrations `0007_court_chair.sql`, `0012_chair_is_vik.sql`

## Context

The Preparation tab (since removed; see [Revisions](#revisions)) ran ten built-in investors with Vik only picking the next speaker, and an independent judge scored answers. The founder wanted:
- a smaller panel with clearer roles;
- Vik as the orchestrator, reviewer and validator of the other agents;
- the investors able to use the founder's own knowledge base (the retrieval stack of [ADR 0001](0001-rag-retrieval-stack.md)) to test whether the founder knows their material, with every answer verified by a retrieval query.

## Decision

1. **Five built-in investors, named for Greek philosophers:**

   | Investor | Role |
   |---|---|
   | Aristotle | Lead Seed Fund |
   | Thales | Angel Operator |
   | Xenophon | Strategic Investor |
   | Plato | Government-Backed Fund |
   | Socrates | Skeptical Partner |

   They keep the lenses, methods, kits and question banks of the archetypes they replace (lead seed, operator angel, corporate/strategic, mandate fund, skeptical IC partner). All five sit by default (the panel maximum is 5). The other five built-ins are removed; their question banks (`playbooks/questions-{priya,dana,victor,sam,olivia}.md`) stay as strong-answer anchors. The builder offers four templates of other archetypes (`areopagus/templates.yaml`): Impact Partner, Family Office Principal, Accelerator Partner and Revenue-Based Lender; saving one creates a custom investor. Custom investors still work.
2. **Vik orchestrates.** The referee still ranks candidates in code. Vik adds a `knowledge` candidate when a check is due (`knowledge.candidate`: from the second question, then every third, never right after a weak answer, at most cap ÷ 3), and the chair may pick it or not; `referee.pick/validate` keep a knowledge pick legal only when one is on offer.
3. **Vik reviews every line before it is spoken.** The investor drafts and the figure audit runs first. Then she reviews the line: code checks (one question, under 70 words, not a repeat of an earlier question, not giving a knowledge answer away) always count, and on the LLM path she can add issues of her own (`MODEL_VIK`, low thinking level; decided on the tiny tier, see [Revisions](#revisions)). A line she sends back is rewritten once; the rewrite is kept if it passes code's checks. The review is stored on the turn (`turns.audit.review`) and shown in the feed when a line was rewritten.
4. **Vik scores.** The `judge` route now speaks as Vik. Accuracy stays code's claim check; every number rule is unchanged.
5. **Knowledge checks.** A setting of the court engine, on by default; the Simulation opens its Q&A with it off (see [Revisions](#revisions)).
   - **At start:** retrieval over each investor's lenses finds passages of the founder's own notes. Tables and hub notes are excluded, because their text is generated, not the founder's.
   - **Questions:** a recall question is written from each passage, with its answer key a verbatim span of that passage. Drafted probes survive only if the quote is verbatim, the question has no numbers and it doesn't give the answer away.
   - **On the answer:** a fresh retrieval over the question and answer, plus the key passage, is what Vik verifies against. Her verdict is `knows`, `partial`, `contradicts`, `missed` or `unverified`. Her explanation quotes the note word for word with its `[kb:path]`, and the audit checks it against those notes.
   - **Records:** each check is stored in `knowledge_checks`, feeds her score, and appears in the feed, the Q&A list and the report. Missed notes go into the action plan.

## Consequences

- **Latency:** one more small LLM call per turn (the review), plus one on knowledge answers (verification, chained before scoring). Probe drafting runs in parallel with the per-hypothesis retrieval at session start.
- **No LLM key:** every step has a deterministic path (`court/knowledge.py`, `court/review.py`), so offline sessions get code reviews, template knowledge questions and overlap-based verdicts.
- **Old ids:** sessions recorded with the old persona ids (`james`, `mark`, …) still open; `registry.panel(strict=False)` skips investors that no longer exist.
- **Vault content:** knowledge checks need prose. A vault of only tables yields none, and the session's `knowledge_ready` says so.

## Revisions

- **2026-10-18, one tier each for Vik and the investors.** Vik's routes (chair, review, judge, verify, probes) moved onto one model setting, `MODEL_VIK` (then Claude Opus 5.5), and the investors' (memo, update and bid, speak, knowledge questions) onto `MODEL_INVESTOR` (then Claude Sonnet 5.5), all at low effort. The line review left the tiny tier with this change.
- **2026-10-19, LLM provider.** The model calls moved from Anthropic's Claude to Google Gemini: `MODEL_VIK` was then Gemini 4 Argon and `MODEL_INVESTOR` Gemini 3.8 Flash. Effort maps to Gemini's thinking level; every court route stays at low. Nothing else in the decision changes, and the deterministic paths are untouched.
- **2026-10-19, free Gemini tier.** The default key is a free AI Studio key (`GEMINI_TIER=free`), where Gemini 4 Argon isn't offered: `MODEL_VIK` is Gemini 3.8 Flash and `MODEL_INVESTOR` Gemini 3.6 Flash, so Vik and the investors draw on separate per-model quotas. On a paid key `MODEL_VIK` can be set back to Gemini 4 Argon. Each model is paced per process (`GEMINI_RPM`), and a model that answers 429 rests while its calls go to the offline mind at once, so a turn never waits long on a quota. The decision is unchanged.
- **2026-10-19, the court is the Simulation's Q&A.** The Preparation tab, the stand-alone text court, is gone, and with it founder memory (migration `0011_retire_founder_memory.sql`). The court now runs only after a pitch in after mode (`POST /pitch/{id}/end` opens it: mode `simulate`, 6 questions), and it opens with knowledge checks off. Decision 5 still holds in the court engine (`court/knowledge.py`, the `knowledge` chair intent, the `knowledge_checks` table) and runs when a court is started with knowledge checks on. Decisions 1 to 4 apply to the Q&A as written.
- **2026-10-19, the chair's name.** Stored rows use `vik` for the chair and the dashboard assistant; migration `0012_chair_is_vik.sql` renames the earlier enum labels and turn speakers in place.
