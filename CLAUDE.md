# Vik — project guide for Claude

AI venture-capitalist pitch coach for the Catalyst hackathon. Next.js 16 frontend in `frontend/`, FastAPI backend in `backend/` (package `vik`), deployed on Render with Docker. The app's own LLM calls go to **Google Gemini** (`google-genai`), never the Anthropic API.

The app has exactly five tabs: **Knowledge base, Dashboard, Simulation, Areopagus, Reports**. There is no Preparation tab or text court any more; the court engine (`backend/vik/court/`) only runs the Simulation's Q&A after a pitch.

## Source of truth (read before building)

The docs in `docs/` win over any generic skill guidance:

| Doc | Use for |
|---|---|
| `docs/01-PRD.md` | Scope, principles, acceptance tests |
| `docs/02-TRD.md` | Stack, services, agents, API surface, env vars |
| `docs/03-UI-UX-DESIGN.md` | Tokens, components, screen specs |
| `docs/04-APP-FLOW.md` | Step-by-step user and system flows |
| `docs/05-BACKEND-SCHEMA.md` | Postgres tables, Redis keys, JSON shapes |
| `docs/07-KNOWLEDGE-BASE.md` | Knowledge base: ingest, OCR, organizer, graph, autofill |
| `docs/08-RAG.md` | Retrieval over the knowledge base: index built on Fill dashboard, BM25 + pgvector, caches, the Ask Vik ladder and catch-all offer, live court (ADRs in `docs/adr/`) |
| `docs/API.md` | REST and WebSocket reference |

## Folder layout

| Path | Contents |
|---|---|
| `frontend/` | Next.js app, Playwright E2E (`e2e/`) and demo specs (`demo/`) |
| `backend/` | FastAPI app (`vik/`), SQL migrations, pytest suite; sample companies in `data/samples/` |
| `docs/` | The docs above, ADRs (`adr/`), the Trionn style prompt (`design/`) |
| `docs/challenge/` | Catalyst brief and supporting PDF (gitignored) |
| `brand/` | The VIK logo set (`vik/`, SVG + PNG) and `build.py`, which draws it and writes the app's icons |

## Non-negotiable rules

- Numbers come from code (the metrics engine). LLM output never supplies a figure.
- Every figure carries a source; the audit blocks uncited numbers and benchmarks.
- No valuation or investment advice anywhere.
- No company-specific strings (e.g. the sample company) outside `backend/data/samples/` and tests.
- All model calls go through `backend/vik/llm/client.py` (routes, thinking levels, budget, refusals). Every agent has an offline path, and any `LLMError` falls back to it.

## Skills in `.claude/skills/`

Vendored from jeffallan/claude-skills (see `.claude/skills/_vendor-jeffallan/README.md`) plus `clone-website`, and the 50 QA skills from petrkindlmann/qa-skills (pinned in `skills-lock.json`; update with `npx skills update -p`). Use them for technique, but follow these overrides:

- **nextjs-developer / react-expert:** the app runs Next.js 16 and React 19. Read `frontend/AGENTS.md` and the guides in `frontend/node_modules/next/dist/docs/` before writing Next code; they override the skill's Next 14 advice. Deployment is Docker on Render, not Vercel.
- **fastapi-expert / postgres-pro:** use asyncpg with SQL migrations as in the schema doc, not SQLAlchemy ORM models.
- **fullstack-guardian / architecture-designer:** write design notes and ADRs under `docs/`, not `specs/`. Auth is the shared access-code cookie, not JWT user accounts.
- **devops-engineer:** infra is `render.yaml` + `docker-compose.yml` + GitHub Actions. No Kubernetes or Terraform.
- **prompt-engineer:** the app uses the Gemini API through `google-genai`; check model ids, thinking levels and structured-output rules against the Gemini API docs (ai.google.dev), and keep tests on the recorded responses in `backend/tests/llm_fakes.py`.
- **QA skills (qa-skills):** backend tests are pytest in `backend/tests/`; E2E is Playwright. Skip the Cypress, mobile, payment, email and analytics-tracking skills unless the app grows those features. `ci-cd-integration` targets GitHub Actions only. For the court and RAG agents, `ai-system-testing` must still honour the rule that figures come from the metrics engine.
