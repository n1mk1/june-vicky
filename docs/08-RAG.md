# Vicky — Retrieval (RAG) over the knowledge base

**Status:** built. Decision record: [adr/0001-rag-retrieval-stack.md](adr/0001-rag-retrieval-stack.md). Code: `backend/vicky/kb/` (`chunk.py`, `bm25.py`, `voyage.py`, `index.py`, `rag.py`, `ask.py`, `glossary.yaml`), `backend/vicky/court/session.py`, `frontend/components/kb/SearchIndexStatus.tsx`, `frontend/components/dashboard/DashboardChat.tsx`. Tests: `backend/tests/test_rag.py`, `frontend/e2e/catch-all.spec.ts`. Eval: `backend/evals/rag/run.py`.

**Retrieval is the main path** for every agent, the live court included:
- **Hybrid search:** chunks ranked by BM25 and by vectors, fused, then reranked.
- **Recovery:** a second, wider pass when the first one is unsure.
- **Caches** keyed to the index build and the vault version.

**The index is built when the founder presses Fill dashboard.** That button means "I'm done adding knowledge", so chunking, embedding and the BM25 index all run then, not on every import or edit. Going back to change the knowledge base means pressing Fill dashboard again: that **rebuilds the index from scratch** from the current vault and discards the old one.

**A whole-vault LLM call exists only as the worst-case catch-all, and it never runs without the user's go-ahead.** When retrieval can't answer, Vicky says so and offers to search every note; the call runs only if the user accepts. Every offer is logged as a retrieval miss and becomes a regression case, so retrieval improves until the offer is almost never needed.

**Every statement in a chat answer references the knowledge base.** A model-written sentence must quote a note word for word with its `[kb:path]`, or state a computed figure; a figure's footnote names the knowledge-base note its table or document came from. A sentence that cites nothing fails the audit, and the reply isn't used.

What does not change:

- **Figures come from the metrics engine.** Retrieval returns prose to quote. A number in an answer is either a computed Figure or sits inside a verbatim note quote, exactly as `audit_text(..., notes=)` enforces.
- **Note quotes.** A chunk is an exact span of `kb_notes.content`, so a quote from a chunk is a quote from the note. `[kb:path]` tokens and `kind: "note"` citations are unchanged.
- **The deterministic answer comes first.** `qa.answer_any` still computes the offline answer from the TruthPack; retrieval decides what the notes add.
- **No valuation or investment advice**, on every path.

## Targets and results

| Measure | Target | Measured |
|---|---|---|
| Recall@5 (the note that answers is in the top 5) | ≥ 0.95 | **1.00** with BM25 + glossary, no vectors (search before the index: 0.86) |
| MRR | ≥ 0.85 | **0.90** with BM25 + glossary (before: 0.79) |
| Offer rate (questions where the catch-all is offered) | < 5%, falling | `GET /kb/status` → `rag.offer_rate`, once real questions arrive |
| Audit pass rate of returned answers | 100% | Every path audits before it returns (tests) |
| Added latency in a court turn (P50) | ≤ 50 ms | Retrieval runs in parallel with claim extraction; BM25-only retrieval takes about 5 ms |

The measured rows come from `evals/rag/run.py` on the fixture vault in `backend/data/samples/rag_eval/` (15 notes, 50 questions phrased with synonyms and acronyms). The first run missed two questions ("CEO", "CTO"); glossary entries fixed them, which is how the miss log is meant to be used. The questions were written alongside the glossary, so these numbers flatter it: the miss log on real questions is the honest test. Rows for vectors and rerank need `VOYAGE_API_KEY` and print when it is set.

| Setup | recall@5 | MRR |
|---|---|---|
| Before the index (full-text over whole notes) | 0.860 | 0.787 |
| BM25 | 0.900 | 0.833 |
| BM25 + glossary | 1.000 | 0.903 |
| BM25 + glossary + recovery | 1.000 | 0.900 |

## Decisions

| Decision | Why |
|---|---|
| Vectors in the existing Render Postgres with **pgvector** | Render has no vector database service; Postgres already holds the notes, is backed up and is reached with asyncpg. Where the extension can't be created, the migration makes the tables without vector columns and search runs on BM25. |
| **BM25 in process**, a small inverted index (`kb/bm25.py`) | `ts_rank` has no IDF and no proper length normalization. The BM25 extensions (ParadeDB `pg_search`, `pg_textsearch`) are not expected on Render's managed Postgres. `bm25s` would pull in numpy and scipy; for a few thousand chunks, a dict-based index is a few MB and answers in about a millisecond. |
| **Voyage** embeddings (`voyage-4`, 1024 dims) and reranker (`rerank-2.5`; `rerank-2.5-lite` in court) over `httpx` | Anthropic has no embeddings endpoint and recommends Voyage. A local model doesn't fit next to the API on a 512 MB instance. |
| Hybrid ranking with **reciprocal rank fusion**, then a **reranker** | Fusion needs no score calibration between BM25 and cosine. A cross-encoder reranker is the biggest single precision gain over fused lists. |
| Query expansion by **code** (`kb/glossary.yaml`), not by an LLM | Deterministic, free and cacheable, and it keeps LLM calls out of the main path. Generic finance vocabulary only: no company-specific terms. |
| The index is built on **Fill dashboard**, not on every note write | Fill is the founder's signal that the vault is complete. Embedding once per Fill avoids paying for chunks that are about to change, and gives one clear "search is ready" moment. The build runs in the background, so Fill returns as quickly as before. |
| Every Fill is a **full rebuild that replaces the old index** | Search always matches one known state of the vault: the one at the last Fill. Nothing from an earlier build lingers. The new build is made beside the old one and swapped in only when ready, so search never goes empty. |
| Between Fills, search shows the vault **as of the last Fill** | Edits and new notes reach search at the next Fill. A chunk whose note was edited since is skipped (the note's `md5` no longer matches), because its quote could no longer be verified. |
| The vault version is a **Postgres counter bumped by a trigger** (`kb_meta.version`) | Every insert, update and delete on `kb_notes` bumps it, so no write path (the organizer, hub rewrites, imports, edits) can miss it. Cache keys include it and the build id. |
| Confidence is **computed by code** | The API returns no token probabilities, and a model's self-rating isn't reliable. Retrieval signals come before the call; the audit and structured output after it. |
| **Claude Haiku 5.5** (`model_tiny`) writes the answer from passages and runs the catch-all | $0.10 / $0.50 per MTok, cache reads $0.01, 1M context, 512-token cache minimum. Haiku 4.5 is 10× the price, with 200K context and a 4,096-token cache minimum; see the ADR. |
| The **catch-all** is a whole-vault call, offered only after recovery fails, **with the user's permission every time** | It answers what retrieval missed, and its citations reveal which note retrieval should have found. It's the one call that sends the whole vault to the model, so the user decides. A cached answer needs no permission, since no new call is made. |
| **Every model-written chat statement cites** (audit rule 5, `require_citations`) | The answer is grounded sentence by sentence: a computed figure, a note quote with `[kb:path]`, or a `[src:id]`. Only questions are exempt. A failed reply is regenerated once with the findings, then dropped. |
| The **Sonnet tool loop leaves Ask Vicky** once an index exists | With hybrid retrieval and recovery, the loop is a slower duplicate. Before the first Fill, Ask Vicky works as before. Court memos keep `kb_search` / `kb_read` as tools, backed by hybrid retrieval. |
| The **live court never uses the catch-all** | A spoken turn can't wait for a large-context call. A turn whose retrieval is unsure runs without notes, as every turn did before. |

## Data

Migration `0006_rag.sql` (idempotent). Full column lists are in [05 §2.23](05-BACKEND-SCHEMA.md).

| Table | Holds |
|---|---|
| `kb_meta` | `version`, bumped by a statement trigger on `kb_notes` |
| `kb_index_builds` | one row per Fill: status `queued → building → active → superseded \| failed \| cancelled` (one `active` at a time), counts, timings |
| `kb_chunks` | `build_id`, `note_id`, `note_md5`, `ord`, `heading`, `start_char`, `end_char`, `text` (= `content[start:end]`), `text_sha256`, `sha256` (of the embedded text, for reuse); `embedding halfvec(1024)` with pgvector |
| `qa_cache` | the semantic answer cache, per build; `embedding` with pgvector |
| `rag_misses` | every catch-all offer and the user's decision |
| `uploads.kb_note_id` | the note Fill sent to intake, so a figure's citation can name it |

Size: a 1024-dim `halfvec` is about 2 KB, so 10,000 chunks is about 20 MB. `halfvec` needs pgvector ≥ 0.7. Locally, `docker-compose.yml` uses `pgvector/pgvector:pg17`, which keeps Postgres 17's data format.

Redis keys ([05 §5](05-BACKEND-SCHEMA.md#5-redis-valkey-keys--ephemeral-only)):

| Key | Value | TTL |
|---|---|---|
| `rag:ret:{build}:{kb_v}:{mode}:{k}:{sha}` | ranked chunk ids, scores, confidence and signals | 1 h |
| `rag:rr:{build}:{model}:{sha}:{sha}` | rerank scores | 1 h |
| `rag:ans:{build}:{kb_v}:{tp_id}:{tp_v}:{sha}` | an audited answer | 24 h |
| `rag:emb:{model}:{sha}` | a query embedding (kept across builds: it encodes the question, not the vault) | 30 d |
| `rag:offer:{id}` | a pending catch-all: dashboard, question, `rag_misses` id | 15 min, deleted on use |
| `rag:stats:{YYYYMMDD}` | hits and misses per cache layer, answer paths, offers made, accepted and declined | 8 d |

## Indexing

```
POST /kb/autofill (Fill dashboard)
  ├─ index.start_build(): cancel any queued or running build; insert kb_index_builds (queued); enqueue kb_index
  ├─ profile, engagement, uploads (each upload remembers its note: uploads.kb_note_id)
  └─ the response includes  index: {build_id, status}

job kb_index (inline on the free plan, arq worker later)
  1. wait for any running kb_ingest / kb_organize job (the vault must be settled)
  2. chunk EVERY note from its current content (with its md5)
  3. with pgvector and a Voyage key: embed every chunk (input_type "document", batches of 128), copying a
     vector instead when the active build has a chunk with the same sha256 and model
  4. insert kb_chunks under the new build id
  5. swap, in one transaction: the new build becomes active and the old one superseded, with its chunks and
     qa_cache rows deleted
  6. drop the old build's Redis entries (rag:*:{old}:*); publish kb.index.ready on "kb"
     every process throws away its BM25 index and builds the new one on its next search
```

- **Full rebuild, then swap.** The old build serves until the swap. A failed build deletes its own chunks and stays `failed`, and the old build stays active. A Fill during a running build cancels it (checked between embedding batches and at the swap).
- **Vector reuse is the one shortcut.** Voyage returns the same vector for the same input, so copying it gives the same index; it only saves time and money. `RAG_REUSE_EMBEDDINGS=false` embeds every chunk fresh.
- **Before the first Fill** (no active build), `kb_search`, Ask Vicky and the court work as they did before this index existed.
- **Between Fills**, chunks of edited notes are skipped and new notes wait. `GET /kb/status` → `index.changed_since` counts notes written since the build read the vault (by `updated_at`, so the call stays cheap; retrieval itself compares content `md5`s, so a note touched without a content change is never skipped), and the knowledge base page says *"12 notes changed since the last Fill. Fill dashboard again to update search."*
- **A build can't hang:** it waits only for imports started in the last 15 minutes (one left "running" by a dead process doesn't count). A build whose job ended, vanished, or has run for more than 30 minutes is marked failed on the next status call, so the page offers Retry instead of polling forever.
- **Two Fills at once:** starting and activating builds take one database advisory lock, so exactly one build ends up active and the other is cancelled or superseded, never failed.
- **Warm start:** the process that ran the build loads its BM25 index right after the swap, so the first search after a Fill doesn't wait for it.
- **Status** (`SearchIndexStatus`, on the knowledge base and confirm pages) reads one of:
  - *Search builds when you press Fill dashboard*
  - *Building search…* (polls every 2 s)
  - *Search ready · 214 notes*
  - *Search failed · Retry* (`POST /kb/index`)
- **Backfill:** `uv run python scripts/kb_reindex.py` runs the same build without a Fill, after a deploy or an `EMBED_MODEL` change.

**Chunking** (`kb/chunk.py`) follows the converter's own structure:
- **Headings:** a heading (`## Page 4`, `## Slide 7: Traction`, any markdown heading) starts a new section, and no chunk crosses one, so a quote keeps its page.
- **Packing:** paragraphs and tables are packed to about 1,600 characters (~400 tokens, at most ~600), carrying the previous short block over as overlap.
- **Tables** stay whole unless they're longer than the limit. A long table splits by rows, and each piece carries the header row in its context, not in its text.
- **CSV notes** give one chunk: the header row. Values are the metrics engine's job.
- **Contextual embedding:** the text sent to Voyage is `title · path · tags · summary · heading`, then a split table's header, then the chunk. `kb_chunks.text` stores only the chunk, so quotes stay verbatim.

## Retrieval

`rag.retrieve(query, mode="ask" | "court" | "recover", k=…) → Retrieval{chunks, confidence, signals, build_id, kb_version}`

1. **Normalize** the query and look it up in `rag:ret`.
2. **Expand by code.** Glossary groups (`NRR ↔ net revenue retention`, `burn ↔ cash burn`, `CEO ↔ chief executive` …) add their other members' tokens at half weight (full weight in recovery). The vector query stays the original text.
3. **Search, in parallel:**
   - **BM25** over the active build's chunks (title, tags, heading and text), with a light English stemmer: "hire", "hired" and "hiring" share one key.
   - **pgvector cosine search**, with `hnsw.ef_search` raised per query.
4. **Fuse** with reciprocal rank fusion (`Σ 1/(60 + rank)`). Drop chunks whose note changed since the Fill. Collapse the same passage in two notes into the more recently updated one.
5. **Graph boost:** +10% for chunks of notes linked to or from the top three.
6. **Rerank** with Voyage: the top 30 (`ask`), 20 (`court`, fast model) or 60 (`recover`).
7. **Small-to-big:** a chunk under ~90 words gets its neighbours in the same section as `context`; quotes may come from them too.
8. **Keep** the top `k` (8, or 4 in court), at most 3 per note.

`kb_search` keeps its name and shape. It returns each note's chunks as verbatim excerpts with headings and cite tokens, and registers the notes so their quotes can be audited.

**Recovery** (`mode="recover"`) searches with three queries: the question, the question with expansions at full weight, and the label of the figure the deterministic answer resolved. It takes the BM25 and vector top 100 for each, fuses them all, and reranks the top 60.

## Confidence

| Signal | Definition |
|---|---|
| `rerank` | reranker score of the top chunk |
| `agree` | 1 if the top chunk is in both the BM25 top 10 and the vector top 10 |
| `sim` | best cosine, rescaled from [0.3, 0.8] to [0, 1] |
| `cover` | share of the query's words found in the top 3 chunks, **weighted by rarity** (IDF). A word no note contains weighs as much as the rarest one, so a question about something the vault lacks scores low, while filler words barely count. |
| `margin` | `(s1 − s5) / s1` over rerank scores (or BM25 scores without vectors) |

With vectors: `0.40·rerank + 0.20·agree + 0.15·sim + 0.15·cover + 0.10·margin`. Without: `0.6·cover + 0.4·margin`. The threshold is `RAG_CONF_MIN = 0.55`. These are starting values: calibrate them on the answer paths once there are real questions and a Voyage key.

**Output confidence:** the answer call returns `{answerable, reply}` as structured output. It passes only when `answerable` is true and `audit_text(..., notes=…, require_citations=True)` passes.

## Ask Vicky

Runs in `kb/ask.py`, called by `qa.answer_any` after the deterministic answer whenever an index exists.

```
0. Answer cache: exact, then semantic (cosine ≥ 0.95, same build, vault and TruthPack versions, same guard)
1. retrieve(mode="ask"); confidence ≥ RAG_CONF_MIN → Haiku answers from the passages → passes? cache, return
   not confident and the data answers it → Haiku phrases the figures alone (same citation rule) → return
2. retrieve(mode="recover"); confident → Haiku answers from the passages → passes? cache, return
3. the notes are needed → OFFER the catch-all with the best answer so far; log the miss; no LLM call
4. offline: the deterministic answer, plus verbatim quotes of the best passages when they cover most of the question
```

- **"The notes are needed"** means the deterministic answer is `not_found`, or the answer from passages came back `answerable = false`.
- **The answer from passages** (route `qa_rag`, Haiku 5.5, effort `low`) gets the fact sheet, the deterministic draft, the passages as `<passage cite="[kb:…]">…</passage>`, and the question. A reply that fails the audit is regenerated once with the findings, then dropped.
- **Without an API key**, only paths 0 and 4 run. The offline answer quotes the best passages, verbatim and cited, when they cover at least half of the question's weight. Headings, table rows and fragments under four words are never quoted as an answer.
- **Every figure citation** carries `source.kb_note: {id, path}` when its dataset or document came from a knowledge-base note through Fill dashboard. The footnote shows *From your knowledge base · financials/Income statement.csv*.

### Asking permission

The catch-all never runs on its own. When path 3 is reached, `POST /dashboards/{id}/chat` returns the best answer so far plus an offer:

```json
{"kind": "answer", "reply": "I couldn't find that in your data. …",
 "offer": {"kind": "catch_all", "id": "3f9c…", "notes": 214,
           "prompt": "Search all 214 notes with AI? This reads your whole knowledge base and takes a few seconds.",
           "expires_at": "2026-10-18T14:05:00Z"}}
```

- **The chat** shows the prompt under the answer with **Search all notes** and **No thanks**. It names how many notes it will read, but shows no dollar figure (the call costs a fraction of a cent).
- **Accept:** `POST /dashboards/{id}/chat/catch-all {offer_id, accept: true}` runs `qa_full` once. The answer shows under *From all your notes*, audited and cached.
- **Decline:** the same endpoint with `accept: false` returns 204 and runs nothing.
- **Ignored:** the offer expires after 15 minutes. Its miss is marked `expired` the next time an offer is made.
- **One offer, one call:** an offer is single-use (`GETDEL`) and tied to its dashboard. An expired, used or other dashboard's offer returns 410, and the chat says *That offer expired. Ask the question again.*
- **No offer** is made without an API key, over the daily budget, or with an empty vault, since no call could run.
- **Cache keys include the dashboard's currency** (figures are converted to it), so a USD view never gets a cached CAD answer.

**The catch-all** (route `qa_full`, Haiku 5.5, effort `medium`):
- **Prompt:** system `[RAG_SYSTEM, FULL_RULES, <vault>]`, then the fact sheet and the question. `<vault>` holds every note as `<note path title>content</note>`, sorted by path.
- **Caching:** the last two system blocks are cache breakpoints, so repeat calls on the same vault read from the prompt cache.
- **Audit:** every note in the snapshot is registered, so any quote can be checked.
- **Size cap:** over `RAG_FULL_MAX_TOKENS` (300,000), the snapshot fills up in order of relevance: notes the recovery pass found, hubs, the rest of their folders, then the most recently updated notes. It is never empty while the vault isn't. The offer says so up front: *"Search your notes with AI? Your 8,000 notes are more than one read can hold, so this reads as many as fit, starting with the ones closest to your question."*
- **When nothing could be read**, the reply says why: the daily budget is spent, or the model couldn't be reached. Only a real read that found nothing says *"I read every note and still couldn't find a cited answer to that."*

## Live court

The court reads the vault through retrieval only (`court/session.py`), with no recovery and no catch-all, so a turn takes no longer.

- **At session start**, after the memos: one `retrieve(mode="court", k=3)` per hypothesis (claim + detail), in parallel. The passages are stored on the hypothesis (`hyp["kb"]`, text capped at 800 characters, still a quotable span) with the build id (`state["kb_build"]`). After a rebuild they are ignored.
- **On each founder answer:** `retrieve(answer + current hypothesis claim, mode="court")` runs **in parallel with claim extraction** (an LLM call), so it adds no time. Below `RAG_CONF_MIN`, the turn gets no notes.
- **Vicky's scoring** (the `judge` route) gets the passages. When the answer contradicts the founder's own notes, she says so in `missing`, quoting the note with its cite token (audited with the notes).
- **The belief updates** get the passages in their prompt. Hypothesis evidence stays figure ids, so the no-concession rule is unchanged.
- **The speaker** gets the passages for the hypothesis being asked plus the turn's own, and a line may quote one (*Your plan says "…" [kb:team/Hiring plan.md]. How will you fund that?*). The turn's audit gets `notes=`, so a quote from a note it wasn't given fails; the speaker then regenerates, or falls back to its code line.
- Each turn's retrieval time and confidence are logged (`court retrieval: … ms`).

**Knowledge checks** (Vicky's; [ADR 0002](adr/0002-vicky-chairs-the-court.md)):
- **At session start**, in parallel with the memos, `retrieve(mode="court", k=3)` runs on each seated investor's top two lens labels. Passages from notes and documents (not tables or hub notes) become recall questions; each answer key is a verbatim span of its passage, stored on the probe with the chunk.
- **On the answer to a knowledge question**, `retrieve(question + answer, mode="court", k=4)` runs in parallel with claim extraction. Vicky verifies the answer against the key passage and those passages; their notes are the audit's `notes=`, so her explanation can quote them. The retrieval's confidence, build id and passage count are stored on the `knowledge_checks` row. Below `RAG_CONF_MIN` she still has the key passage to check against.
- **No active build**, or no prose in the vault, means no knowledge checks, and the Preparation tab says so.

## Learning from misses

- **Every offer writes a `rag_misses` row:** the question, both retrieval passes, the decision, and, for accepted offers, whether the answer passed and which notes it quoted.
- **An accepted miss shows where retrieval failed:** a quoted note that isn't in the recovery top 8. `uv run python scripts/rag_misses.py` lists unreviewed misses and flags those; `--mark-reviewed` clears them.
- **A reviewed miss becomes a case** in `backend/data/samples/rag_eval/cases.yaml`. Typical fixes, in order:
  1. a glossary entry
  2. a chunking rule
  3. a better organizer summary
  4. a weight or threshold

  Check each fix with `evals/rag/run.py` before it ships.
- `GET /kb/status` → `rag` shows today's counters, `offer_rate` and `accept_rate`.

## Environment variables

| Var | Default | Notes |
|---|---|---|
| `VOYAGE_API_KEY` | unset | `sync: false` in `render.yaml`. Unset: BM25 and expansion only; no vectors, rerank or semantic cache. |
| `EMBED_MODEL` | `voyage-4` | 1024 dims. After a change, the next Fill embeds everything fresh. |
| `RERANK_MODEL` / `RERANK_MODEL_FAST` | `rerank-2.5` / `rerank-2.5-lite` | Ask Vicky and recovery / court turns. |
| `RAG_CONF_MIN` | `0.55` | Below it: recovery (Ask Vicky) or no notes (court). |
| `RAG_FULL_MAX_TOKENS` | `300000` | Catch-all snapshot cap. |
| `RAG_REUSE_EMBEDDINGS` | `true` | Copy vectors of byte-identical chunks on a rebuild. |

## QA results (2026-10-18)

A rigorous pass over the built system: fuzzing, adversarial audit cases, failure and race probes, a scale benchmark, and browser tests. Twelve defects were found and fixed, each with a regression test in `backend/tests/test_rag_qa.py` or `frontend/e2e/catch-all.spec.ts`.

| # | Severity | Defect | Fix |
|---|---|---|---|
| 1 | low | Chunk numbers (`ord`) had gaps when a heading-only chunk was dropped | Renumbered after filtering |
| 2 | high | An uncited claim could follow a citation token after a comma, a semicolon or no space (`“…” [kb:a], and churn is falling.`) and pass rule 5 | A statement ends right after every citation token |
| 3 | medium | "In the U.S. your notes say …" was split at "U.S." and a cited answer was rejected | Abbreviations don't end a sentence when the next word is lowercase or a quote; « » „ count as quote marks |
| 4 | medium | A build waited 10 minutes behind an import left "running" by a dead process | Only imports started in the last 15 minutes count |
| 5 | medium | A build whose job died showed "Building search…" forever, and the page polled forever | Reaped to `failed` on the next status call; Retry works |
| 6 | high | Figure footnotes named their knowledge-base note only on the model path, not on code-written answers | Notes linked for every chat answer |
| 7 | medium | The answer cache ignored the dashboard's currency, so a USD view could get a cached CAD answer | Currency in the exact key and the semantic guard |
| 8 | low | A catch-all that couldn't run (budget spent, model down) still said "I read every note" | Says what actually happened |
| 9 | high (at scale) | BM25 index load: 14 s and ~480 MB peak at 33,000 chunks, past a 512 MB instance | Compact array postings, no per-chunk token sets, cached stemming: ~87 MB; warmed after each build |
| 10 | medium | `GET /kb/status` hashed every note on each call (600 ms at 8,000 notes, polled every 2 s while building) | Counts by `updated_at`: 25 ms |
| 11 | medium | Over the snapshot cap with nothing recovered, the catch-all read zero notes | Fills by relevance, then recency; the offer is honest about a partial read |
| 12 | medium | Two Fills at the same instant left one build `failed` (one-active constraint), so the page could show "Search failed" | Advisory lock around build start and swap |

Also fixed in the test setup: every test run shared Redis db 15, so concurrent runs from other sessions deleted each other's offers and reset each other's rate limits. `tests/conftest.py` now gives each test database its own Redis db and raises the per-IP request limit for the suite.

**Benchmark** (BM25 only, synthetic worst case where every word is in every chunk, local Postgres):

| Vault | Build | Index memory | Search P50 / P95 (ask) | Status call |
|---|---|---|---|---|
| 2,000 notes, 8,290 chunks | 2.7 s | — | 35 / 60 ms | — |
| 8,000 notes, 33,244 chunks | 6.2 s | ~87 MB (was ~480 MB) | 139 / 230 ms | 25 ms (was 586 ms) |

**Known limits, not defects:**
- A question mark exempts a sentence from rule 5, so a rhetorical claim ("Churn is falling, isn't it?") passes.
- A sentence with one cited figure can carry an uncited remark in the same sentence ("Revenue is $X, and we'll dominate").
- The vector path (pgvector + Voyage) was exercised with a fake Voyage, not the real service. Its latency and the confidence weights need a run with a real key.

## Tests and evals

**`backend/tests/test_rag_qa.py`** (21 tests, 46 cases): the QA probes above, kept as regression tests: odd queries, empty and renamed notes, cache isolation, hung and racing builds, migration idempotency, concurrent searches during a rebuild, offers accepted twice at once and malformed or unauthenticated catch-all requests, expiry, honest failure messages, figure footnotes on the offline path, and the citation rule under attack.

**`backend/tests/test_rag.py`** (24 tests):
- chunking: spans and boundaries, table splits, CSV header chunks
- search: stemming, BM25 order, glossary expansion
- the cite-every-statement rule, and the semantic-cache guard that keeps Q3 and Q4 apart
- builds:
  - every note is indexed and `kb_search` runs on chunks
  - a rebuild discards the old chunks and caches
  - edited notes are skipped and new notes wait
  - a new Fill cancels a running build, a failed build keeps the old one, and exactly one build is active
  - Fill starts a build and status reports it
- vectors, rerank and reuse with pgvector and a fake Voyage (skipped without pgvector)
- answers:
  - answers from passages are cached
  - an uncited sentence is regenerated, then dropped
  - offline answers quote passages
- the offer:
  - nothing runs before accept
  - foreign and reused ids are 410, and decline is 204
  - no offer over budget
- the court: passages reach the judge, the bids and the speaker, and a quoting line is audited

**`frontend/e2e/catch-all.spec.ts`:**
- both buttons show, and nothing is sent until one is pressed
- the answer shows after accepting
- "No thanks" sends `accept: false`
- an expired offer says so
- a double-click sends one request
- search status: building, ready with the changed-notes banner, and failed with Retry

**`backend/evals/rag/run.py`:** the retrieval eval above.

## Open questions

- **Calibration:** the confidence weights and `RAG_CONF_MIN` are starting values. With a Voyage key, run the eval's hybrid rows and watch `offer_rate`, then raise or lower the threshold.
- **Rerank latency in court:** if the fast reranker ever outlasts claim extraction, court mode should drop reranking and use fused order.
- **Haiku 5.5 vs Sonnet 5.5 for `qa_rag`:** Haiku is the default. Compare them on real questions once there's traffic.
- **"Don't ask again" for a session:** the design asks every time. Decide after the offer rate is known.
