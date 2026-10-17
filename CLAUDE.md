# Vicky (JUNE × VICKY) — project guide for Claude

AI venture-capitalist pitch coach for the Catalyst hackathon. Next.js 16 frontend in `frontend/`, FastAPI backend in `backend/` (to be built), deployed on Render with Docker.

## Source of truth (read before building)

The docs in `docs/` win over any generic skill guidance:

| Doc | Use for |
|---|---|
| `docs/01-PRD.md` | Scope, principles, acceptance tests (FR-1…FR-16) |
| `docs/02-TRD.md` | Stack, services, agents, API surface, env vars |
| `docs/03-UI-UX-DESIGN.md` | Tokens, components, screen specs |
| `docs/04-APP-FLOW.md` | Step-by-step user and system flows |
| `docs/05-BACKEND-SCHEMA.md` | Postgres tables, Redis keys, JSON shapes |
| `docs/06-IMPLEMENTATION-PLAN.md` | Day-by-day build order, cut order, verification |
| `docs/VICKY_PLAN.md` | Original product plan (metrics targets, agents, Areopagus) |
| `docs/BACKEND_PLAN.md` | Backend plan and decisions (Render, Docker, dashboards) |

## Folder layout

| Path | Contents |
|---|---|
| `frontend/` | Next.js app |
| `backend/` | FastAPI app (to be built); `data/samples/tidewell/` holds the sample CSV |
| `docs/design/` | Wireframe, logo format sheet, Trionn style prompt |
| `docs/challenge/` | Catalyst brief and supporting PDF (gitignored) |
| `brand/vicky/` | Logo set and lockups (SVG + PNG); `brand/_unsorted/` holds unidentified files |

## Non-negotiable rules

- Numbers come from code (the metrics engine). LLM output never supplies a figure.
- Every figure carries a source; the audit blocks uncited numbers and benchmarks.
- No valuation or investment advice anywhere.
- No company-specific strings (e.g. the sample company) outside `backend/data/samples/` and tests.

## Skills in `.claude/skills/`

Vendored from jeffallan/claude-skills (see `.claude/skills/_vendor-jeffallan/README.md`) plus `clone-website`. Use them for technique, but follow these overrides:

- **nextjs-developer / react-expert:** the app runs Next.js 16 and React 19. Read `frontend/AGENTS.md` and the guides in `frontend/node_modules/next/dist/docs/` before writing Next code; they override the skill's Next 14 advice. Deployment is Docker on Render, not Vercel.
- **fastapi-expert / postgres-pro:** use asyncpg with SQL migrations as in the schema doc, not SQLAlchemy ORM models.
- **fullstack-guardian / architecture-designer:** write design notes and ADRs under `docs/`, not `specs/`. Auth is the shared access-code cookie, not JWT user accounts.
- **devops-engineer:** infra is `render.yaml` + `docker-compose.yml` + GitHub Actions. No Kubernetes or Terraform.
- **prompt-engineer:** also load the built-in `claude-api` skill for any Anthropic SDK or model detail.
