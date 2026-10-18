# ADR 0002 — Vicky chairs the court; five philosopher investors; knowledge checks

**Status:** accepted, built · **Date:** 2026-10-18 · **Code:** `backend/vicky/court/` (`session.py`, `knowledge.py`, `review.py`, `referee.py`), `backend/vicky/llm/minds.py`, migration `0007_court_vicky.sql`

## Context

The Preparation tab ran ten built-in investors with Vicky only picking the next speaker, and an independent judge scored answers. The founder wanted:
- a smaller panel with clearer roles;
- Vicky as the orchestrator, reviewer and validator of the other agents;
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

   They keep the lenses, methods, kits and question banks of the archetypes they replace (lead seed, operator angel, corporate/strategic, mandate fund, skeptical IC partner). All five sit by default (the panel maximum is 5). The other five archetypes stay as builder templates and question banks (strong-answer anchors); custom investors still work.
2. **Vicky orchestrates.** The referee still ranks candidates in code. Vicky adds a `knowledge` candidate when a check is due (`knowledge.candidate`: from the second question, then every third, never right after a weak answer, at most cap ÷ 3), and the chair may pick it or not; `referee.pick/validate` keep a knowledge pick legal only when one is on offer.
3. **Vicky reviews every line before it is spoken.** The investor drafts and the figure audit runs first. Then she reviews the line: code checks (one question, under 70 words, not a repeat of an earlier question, not giving a knowledge answer away) always count, and on the LLM path she can add issues of her own (Haiku, low effort). A line she sends back is rewritten once; the rewrite is kept if it passes code's checks. The review is stored on the turn (`turns.audit.review`) and shown in the feed when a line was rewritten.
4. **Vicky scores.** The `judge` route now speaks as Vicky. Accuracy stays code's claim check; every number rule is unchanged.
5. **Knowledge checks.**
   - **At start:** retrieval over each investor's lenses finds passages of the founder's own notes. Tables and hub notes are excluded, because their text is generated, not the founder's.
   - **Questions:** a recall question is written from each passage, with its answer key a verbatim span of that passage. Drafted probes survive only if the quote is verbatim, the question has no numbers and it doesn't give the answer away.
   - **On the answer:** a fresh retrieval over the question and answer, plus the key passage, is what Vicky verifies against. Her verdict is `knows`, `partial`, `contradicts`, `missed` or `unverified`. Her explanation quotes the note word for word with its `[kb:path]`, and the audit checks it against those notes.
   - **Records:** each check is stored in `knowledge_checks`, feeds her score, and appears in the feed, the Q&A list and the report. Missed notes go into the action plan.

## Consequences

- **Latency:** one more small LLM call per turn (the review), plus one on knowledge answers (verification, chained before scoring). Probe drafting runs in parallel with the per-hypothesis retrieval at session start.
- **No LLM key:** every step has a deterministic path (`court/knowledge.py`, `court/review.py`), so offline sessions get code reviews, template knowledge questions and overlap-based verdicts.
- **Old ids:** sessions recorded with the old persona ids (`james`, `mark`, …) still open; `registry.panel(strict=False)` skips investors that no longer exist.
- **Vault content:** knowledge checks need prose. A vault of only tables yields none, and the Preparation tab says so.
