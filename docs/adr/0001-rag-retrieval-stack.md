# ADR 0001 — Retrieval stack for the knowledge base

**Status:** accepted, built · **Date:** 2026-10-18 · **Revised:** 2026-10-18 (build on confirm), 2026-10-19 (LLM provider: Gemini; free Gemini tier; see [Revisions](#revisions)) · **Design:** [08-RAG.md](../08-RAG.md)

## Context

Ask Vik and the court memos read the founder's vault through `kb_search` / `kb_read`. Search is Postgres full-text plus prefix matching over whole notes, computed per row at query time with no index, and nothing is cached. Questions phrased differently from the notes miss ("how sticky are customers?" vs "net revenue retention"), and a long board pack competes as one block. The live court doesn't read the vault at all.

Product direction: **retrieval is the primary path** for every agent, the live court included. An LLM call over the whole vault is only a worst-case catch-all, and it **runs only with the user's permission**.

Constraints:
- Render (free plan now, 512 MB instances for the demo)
- asyncpg with SQL migrations, no ORM
- one global vault of modest size
- every figure from the metrics engine
- every note quote verified word for word by `audit_text`
- court turns within the chair-latency target
- a daily USD budget

## Decision

1. **Store chunks and vectors in the existing Render Postgres with pgvector** (`kb_chunks`, `halfvec(1024)`, HNSW). Chunks are exact spans of note content, so the citation audit is unchanged.
2. **Rank keywords with BM25 in process** (a small inverted index in `kb/bm25.py`, with a light stemmer), rebuilt after each index build, instead of Postgres `ts_rank`.
3. **Embed and rerank with Voyage over HTTP** (`voyage-4`, `rerank-2.5`, `rerank-2.5-lite` in court). Embeddings get contextual prefixes (title, path, tags, summary, heading).
4. **Build the index when the founder presses Fill dashboard**, their signal that the vault is complete. **Every Fill rebuilds it from scratch and discards the old one** (since revised: the build runs on *Confirm knowledge base*, the intake's last step; see [Revisions](#revisions)):
   - **In the background:** a `kb_index` job runs alongside the profile and uploads, so Fill returns as quickly as it does today.
   - **Full rebuild:** after running ingest and organize jobs finish, every note is chunked and embedded again from its current content, under a new build id.
   - **Swap, then discard:** the old build serves until the new one is ready. One transaction makes the new build active and deletes the old build's chunks. Its BM25 index, retrieval, rerank and answer caches and semantic-cache rows are then dropped. A failed build is deleted and the old one stays.
   - **The only reuse:** a vector is copied for byte-identical text with the same model, which gives the same result as re-embedding. It can be turned off.
   - **Nothing else touches the index:** imports and edits only bump the vault version (`kb_meta.version`, a trigger on `kb_notes`). To update search after changing the knowledge base, the founder presses Fill dashboard again.
   - **Between Fills:** search shows the vault as of the last Fill. Chunks of notes edited since are skipped, so no unverifiable quote is served.
   - **Before the first Fill:** everything uses today's search.
5. **The retrieval pipeline**, in order:
   - query expansion by code (generic finance glossary, metric vocabulary, tags)
   - BM25 and vector search in parallel
   - reciprocal rank fusion with duplicate collapse
   - a one-hop wikilink boost
   - cross-encoder rerank
   - small-to-big neighbour expansion

   A second, wider **recovery pass** (several queries, top 100 per query, deeper rerank) runs when confidence is low.
6. **Cache in seven layers**, keyed to the active build and the vault version (and the TruthPack version for answers): exact answer, guarded semantic answer, retrieval, rerank, query embedding, chunk-vector reuse, and the court's per-session hypothesis chunks. All but the query-embedding cache are discarded with their build. The LLM provider's prompt caching sits on top: since 2026-10-19, Gemini's implicit caching of repeated prefixes, with no explicit breakpoints.
7. **Ask Vik answers along these paths, in order:**
   1. cache
   2. answer from first-pass chunks
   3. answer from recovery chunks
   4. **offer** the catch-all whole-vault call, only when the notes are needed; it runs only if the user accepts
   5. the offline answer, which is also what the user sees alongside the offer

   Confidence is computed by code; every path is audited. The fast-tier tool loop (route `qa`) leaves Ask Vik. Court memos keep the kb tools, now backed by hybrid retrieval.
8. **The live court uses retrieval on every turn**:
   - per hypothesis at session start
   - per founder answer, in parallel with claim extraction
   - chunks go to the judge, the belief update and the speaker
   - no recovery pass and no catch-all, so turn latency is unchanged
9. **The catch-all asks first, every time.** The chat answer carries an `offer`; a separate `POST /dashboards/{id}/chat/catch-all` with `accept: true` runs the call. Offers are single-use, tied to their dashboard, and expire after 15 minutes. Decline or silence runs nothing. No offer is made when no call could run (no key, budget spent, empty vault).
10. **Every offer is logged as a miss** (`rag_misses`, with the user's decision). Misses that show a retrieval failure become retrieval-eval cases, so the offer rate trends toward zero.
11. **Use the tiny model tier** (`model_tiny`, already configured) for the answer from chunks and for the catch-all. Decided on Claude Haiku 5.5; Gemini 3.5 Flash-Lite since 2026-10-19 (see [Revisions](#revisions)).
12. **Every model-written chat statement cites the knowledge base or a figure** (audit rule 5, `require_citations`): a note quote with its `[kb:path]`, a computed figure, or a `[src:id]`; only questions are exempt. A reply that fails is regenerated once, then dropped. Figure citations name the note their table or document came from (`source.kb_note`, through `uploads.kb_note_id`).

## Alternatives considered

| Option | Why not |
|---|---|
| Dedicated vector database (Pinecone, Qdrant Cloud, Weaviate) | A second store to sync, back up and secure for a few thousand chunks. Joins with `kb_notes` and transactional deletes come free in Postgres. |
| Vector search in Render Key Value (Valkey) | Render's managed Key Value is a cache, not a document index; no supported vector module, and the data would not be durable. |
| Neon or another Postgres for vectors | Already have Postgres on Render with the notes in it; splitting stores adds cross-service consistency work. |
| Postgres BM25 extensions (ParadeDB `pg_search`, `pg_textsearch`) | Not expected on Render's managed Postgres. Revisit if Render adds one. |
| `bm25s` | Pulls in numpy and scipy (image size, memory) for a corpus of a few thousand chunks that a dict-based index handles in about a millisecond. |
| BM25 in SQL with term-statistics tables | Possible on stock Postgres, but more code and slower than an in-memory index at this corpus size. |
| Keep `ts_rank` full-text only | No IDF or length normalization; the weakest part of retrieval today. |
| Local embedding or rerank model in the API image | Doesn't fit beside the API on a 512 MB instance; adds image size and cold-start time. Worth revisiting on a larger plan to drop the Voyage dependency. |
| LLM query rewriting (HyDE, multi-query by model) | An LLM call on the main path costs latency and money on every question, and is not deterministic. Code expansion plus recovery covers the same misses; reconsider only if the miss log shows phrasing that code can't expand. |
| Claude Haiku 4.5 (when the tiny tier was Claude Haiku 5.5) | $1 / $5 per MTok vs $0.10 / $0.50; 200K context vs 1M; 4,096-token cache minimum vs 512. The catch-all is roughly 10× the cost and may not fit. |
| Keep the tool loop as a fallback in Ask Vik | Slower and more expensive than recovery plus catch-all, and it duplicates what retrieval now does. |
| Whole vault as the main path | Cheap on the tiny tier while the vault is small, but slower per answer, grows with the vault, unusable in the live court, and hides retrieval failures instead of fixing them. |
| Embed on every note write (import, organize, edit) | Pays to embed notes the organizer is about to move, retitle and summarize, and leaves search in flux while the founder is still adding files. Fill dashboard is the moment the vault is complete. |
| Incremental index updates on each Fill (keep unchanged chunks) | Cheaper per Fill, but the index becomes a mix of builds, and chunking or glossary changes never reach old chunks. A full rebuild gives one known state per Fill; vector reuse keeps most of the cost saving. |
| Keep old chunks searchable after edits, or bridge edited notes with full-text search | Keeping old chunks would serve text the note no longer has, which the audit can't verify. A full-text bridge would blur what the index holds. Search reflects the last Fill; the knowledge base page says when it's out of date. |
| Block Fill until the index is built | Fill already takes about a minute; the build can finish while the founder checks the confirm page. |
| Run the catch-all automatically when retrieval fails | It's the one call that sends the whole vault to the model, so the user decides. A declined offer still logs the miss, so retrieval improves either way. |
| A standing "always allow" setting | Turns a per-question decision into a default the user may forget about. Left as an open question until the offer rate is known. |
| Catch-all in the live court | A spoken turn can't wait for a large-context call; a turn without notes is the safe fallback, and it's today's behaviour. |
| Model self-rated confidence or logprobs | The API in use then returned no token probabilities (Gemini's API has an option for them; it stays unused, see [Revisions](#revisions)); self-ratings aren't calibrated. Code signals plus the audit are checkable. |

## Consequences

- **New pieces:**
  - no new Python dependency; a Voyage API key (`VOYAGE_API_KEY`), without which the system falls back to BM25 and expansion only
  - migration `0006_rag.sql` (`kb_meta`, `kb_index_builds`, `kb_chunks`, `qa_cache`, `rag_misses`, `uploads.kb_note_id`); vector columns only where pgvector is available
  - job kind `kb_index` (started by Fill dashboard), backfill and miss-review scripts, and `kb/glossary.yaml`
- **The vault version is bumped by a Postgres trigger** on every insert, update and delete in `kb_notes`, so no write path can leave a cache stale. It keys the caches; it never triggers embedding.
- **Search reflects the vault as of the last Fill.** New notes aren't searchable, and edited notes' old chunks are skipped, until the founder fills again; the knowledge base page says so. Re-filling also creates a new draft engagement, as Fill does today.
- **Rebuild cost:** each Fill re-chunks the whole vault and briefly holds two builds' chunks (about 20 MB per 10,000 chunks). With vector reuse, a rebuild after a few edits embeds only the edited chunks.
- **Ask Vik gains an offer step:** an `offer` field on `ChatResult`, a catch-all endpoint, a Redis offer key, and an accept/decline prompt in `DashboardChat`. A test proves no `qa_full` request happens before an accept.
- **The court reads notes.** Spoken lines and the judge's `missing` can quote the founder's own notes. The court audit gains `notes=`.
- **Infrastructure:** `docker-compose.yml` moves to `pgvector/pgvector:pg17`; the Render instance must have pgvector ≥ 0.7 for `halfvec`.
- **The BM25 index lives in each process**; a worker and the API each build their own. Fine at this size; revisit if the vault grows past roughly 100,000 chunks.
- **The semantic answer cache needs its question guard**, or near-identical questions about different periods would share an answer.
- **The confidence weights and the threshold are starting values.** The retrieval eval meets recall@5 ≥ 0.95 and MRR ≥ 0.85 on BM25 + glossary alone (1.00 / 0.90 on the fixture vault); the offer rate < 5% target is measured in production (`GET /kb/status`).

## Revisions

- **2026-10-18, build on confirm.** The index is built when the founder confirms the knowledge base (`POST /engagements/{id}/confirm`, the intake's last step), not on Fill dashboard: Fill now only drafts the profile, mappings and facts. Everything decision 4 says of a Fill (full rebuild, swap, vector reuse, search as of the last build) holds for each confirm, and `POST /kb/index` rebuilds on demand. Where this record says Fill for the index, read confirm ([08-RAG §Indexing](../08-RAG.md#indexing)).
- **2026-10-19, LLM provider.** The model calls moved from Anthropic's Claude to Google Gemini (`google-genai`). What that changes here:
  - **Decision 11:** `model_tiny` is Gemini 3.5 Flash-Lite, at $0.30 / $2.50 per MTok and $0.03 for cached input (the 2027 list rates the budget uses), against $0.10 / $0.50 for Haiku 5.5. The answer from chunks stays cheap; a catch-all over a full 300,000-token snapshot (`RAG_FULL_MAX_TOKENS`) costs about $0.10 at most. The choice of the cheapest tier for both calls stands.
  - **Decision 6:** no explicit cache breakpoints. Gemini caches repeated prompt prefixes implicitly; the catch-all puts the rules and the vault in the system instruction, ahead of the question, so repeat calls on the same vault share that prefix. Cached tokens are billed at the cached rate.
  - **Confidence:** the Gemini API has a log-probability option (`response_logprobs`); it isn't used. Confidence stays code's: retrieval signals before the call, the audit and structured output after it.
  - **Unchanged:** Voyage for embeddings and reranking (it never depended on the LLM provider, so the index needed no rebuild), retrieval, caching keys, the offer flow and every audit rule.
- **2026-10-19, free Gemini tier.** The default key is a free AI Studio key (`GEMINI_TIER=free`). Its calls cost nothing, so the daily USD budget in the constraints, decision 9's "budget spent" and the dollar figures above apply only on a paid key (`GEMINI_TIER=paid`). The free tier's limits are requests per model: each model is paced per process (`GEMINI_RPM`), and one that answers 429 rests while its calls take the offline path. `model_tiny` stays Gemini 3.5 Flash-Lite, a model of its own with its own quota. On the free tier Google may use what is sent to improve its products, and the catch-all sends the whole vault, so real company data needs a paid key or `LLM_MODE=offline`.
