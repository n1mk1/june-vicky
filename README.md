# VIK

(Access code for the hosted demo: `vik-atlas-58d8cc`)

**Vik is an AI venture capitalist that gets founders ready to raise.** A founder brings their own financials and documents. Vik computes every metric in code, builds a dashboard where every figure has a source, and lists what investors will ask about first. A panel of AI investors then hears the founder pitch in a spoken pitch room, questions them, scores every answer and writes it up as a report.

Built for the Catalyst hackathon (AI Pitch Coach challenge).

## Ground rules

These hold everywhere in the app and are enforced in code:

- **Numbers come from code.** The metrics engine computes every figure. The model never supplies a number.
- **Every figure carries a source:** a file, a row range and a formula. An audit blocks uncited numbers and benchmarks.
- **Missing data is reported as missing**, and history is kept apart from forecasts.
- **No valuation or investment advice**, anywhere.

## The app

After the landing page and the access gate (one shared access code becomes a signed, HTTP-only cookie), the app has five tabs and a light/dark switch.

### Knowledge base

Everything Vik knows about the company. Imported CSV/XLSX, PDF, DOCX and PPTX files (scans are OCR'd) become notes in a vault. An organizer files them into folders with hub notes and `[[links]]`, drawn as a graph. Tables stay tables for the metrics engine. Search is hybrid (BM25 + pgvector) and is rebuilt on each Fill. **Fill dashboard** turns the vault into the source of truth, which the founder confirms.

### Dashboard

The confirmed numbers: ARR, gross margin, MRR and burn, operating expenses, pitch readiness, and *What they'll ask first*. Every widget explains its figure, and a widget whose data is missing says so and asks for it. **Ask Vik** answers questions about the data with footnotes, and **Chart it** pins the answer to the dashboard as a widget.

### Simulation

The pitch room. The founder uploads a deck (optional) and presents out loud. Vik chairs a panel of up to five investor personas, who interrupt live or question the founder afterwards, each in their own ElevenLabs voice. The claims ledger and the *against your notes* checks fill in during the pitch, and delivery stats (talk time, filler words, seconds per slide) are tracked. In the Q&A every answer is scored on accuracy, evidence, clarity, composure and investor fit, and every claim is checked against the data: *matches*, *contradicts*, *unsupported* or *forecast stated as fact*. Without a microphone the founder can type instead.

### Areopagus

The investor personas, built in or custom. Each has a lens (how hard they press on growth, retention, unit economics, governance…), a style, a signature move, opening questions and dealbreakers. **New investor** turns a one-sentence description into a full persona draft for the founder to check and save, then seats it in the pitch room.

### Reports

Every session, written up, with the score trend per company. A report covers the verdict and readiness, scores by dimension, what each investor still doubts, every question with the founder's answer, the correct figure and a strong answer, an action plan, and sources. It downloads as Markdown.

## How it works

```
browser ──HTTPS──▶ vik-web (Next.js 16) ── /api/v1/* proxy ──▶ vik-api (FastAPI)
        ──WSS──────────────────────────────────────────────────▶   ├── Postgres 17 + pgvector (only durable store)
                                                                     └── Redis / Valkey (jobs, pub/sub, caches, rate limit, spend cap)
```

| Layer | Stack |
|---|---|
| Frontend | Next.js 16 (App Router, standalone output), React 19, Tailwind v4, React Three Fiber, ECharts |
| Backend | Python 3.13, FastAPI, asyncpg with SQL migrations, pandas, pypdf, Tesseract OCR, arq jobs |
| Models | Google Gemini through the `google-genai` SDK, on a free AI Studio key by default: Gemini 3.8 Flash for Vik as chair (speaker choice, line review, scoring), document facts, the column mapper, the organizer, chat and persona drafts; Gemini 3.6 Flash for the investors; Gemini 3.5 Flash-Lite for claim extraction and answers from retrieved notes. Each model has its own free quota; requests are paced, and after a 429 a model rests while the offline agents answer. Offline agents also run when no key is set. |
| Voice | ElevenLabs realtime speech-to-text, plus one text-to-speech voice per investor and one for Vik |
| Retrieval | BM25 + pgvector over the knowledge base, with Voyage embeddings |
| Infra | Docker everywhere; `docker-compose.yml` locally, `render.yaml` on Render, GitHub Actions CI |

## Run it locally

You need Docker, [uv](https://docs.astral.sh/uv/) and Node 22.

```bash
cp .env.example backend/.env
```

Fill in `backend/.env`. `ACCESS_CODE` and `COOKIE_SECRET` are required. `GEMINI_API_KEY`, `ELEVENLABS_API_KEY` and `VOYAGE_API_KEY` are optional: without them the app runs its offline agents, shows the panel's lines as captions, and searches by keyword only.

A free Gemini key from [Google AI Studio](https://aistudio.google.com/apikey) is enough (`GEMINI_TIER=free`, the default): calls cost nothing and no dollar budget applies, each model is paced to `GEMINI_RPM` requests a minute, and when a quota runs out the offline agents answer until it resets. On the free tier Google may use what you send to improve its products, so use a paid key (`GEMINI_TIER=paid`, which applies `DAILY_USD_BUDGET` and lets `MODEL_VIK` / `MODEL_DEEP` be `gemini-4-argon`) for real company data.

```bash
docker compose up -d db kv
```

```bash
uv --directory backend run uvicorn vik.api:app --port 8000 --reload
```

```bash
npm --prefix frontend install && npm --prefix frontend run dev
```

Open http://localhost:3000, press **Get started** and enter your access code. To try the sample company, import the files in `backend/data/samples/` on the Knowledge base tab and press **Fill dashboard**.

`docker compose --profile full up` runs the whole stack (web, API, worker, Postgres, Redis) in containers instead.

## Tests

```bash
uv --directory backend run pytest
```

```bash
npm --prefix frontend run test:e2e
```

The backend tests need `docker compose up -d db kv`; the LLM path runs on recorded Gemini responses, so no key is needed. The E2E suite needs the stack running; see [frontend/README.md](frontend/README.md).

## Recording demos

`frontend/demo/` holds one Playwright spec per tab (`00-landing` to `05-reports`), with a visible cursor, captions and the waits marked to play faster. Record them against a production build (the dev server's Fast Refresh shows in recordings):

```bash
npm --prefix frontend run build
```

```bash
npm --prefix frontend run start -- -p 3100
```

```bash
cd frontend && BASE_URL=http://localhost:3100 npm run demo:record
```

```bash
cd frontend && npm run demo:videos
```

`demo:record` writes raw WebM files to `docs/demo/raw/` (gitignored). `demo:videos` needs ffmpeg on `PATH` (or its path in `FFMPEG`) and writes the MP4s, the GIF previews and `vik-tour.mp4` to `docs/demo/`. Run a single tab with `npm run demo:record -- 03-simulation`. The Simulation and Areopagus clips make real model and voice calls, and they add sessions and reports to the workspace. The Dashboard clip removes the widget it adds.

## Brand

`brand/vik/` holds the VIK wordmark (SVG and PNG, black and white, 250×250). `brand/build.py` draws it from the glyph outlines and writes the logo set, the copies in `frontend/public/brand/`, and the app's icons and share image:

```bash
uv --directory backend run python ../brand/build.py
```

## Deploy

`render.yaml` is a Render Blueprint for `vik-web` and `vik-api`, wired to an existing Postgres and Key Value. On the first sync Render asks for the secrets (`DATABASE_URL`, `GEMINI_API_KEY`, `ELEVENLABS_API_KEY`, `VOYAGE_API_KEY`, `ACCESS_CODE`); shared settings live in the `vik-shared` environment group. If Render gives a service a suffixed hostname, fix `API_INTERNAL_URL` and `WEB_ORIGIN` as the file's header says. See [docs/02-TRD.md](docs/02-TRD.md).

## Docs

| Doc | What's in it |
|---|---|
| [01-PRD](docs/01-PRD.md) | Problem, goals, scope, acceptance tests |
| [02-TRD](docs/02-TRD.md) | Stack, services, agents, API surface, env vars |
| [03-UI-UX-DESIGN](docs/03-UI-UX-DESIGN.md) | Tokens, components, screen specs |
| [04-APP-FLOW](docs/04-APP-FLOW.md) | User and system flows, step by step |
| [05-BACKEND-SCHEMA](docs/05-BACKEND-SCHEMA.md) | Postgres tables, Redis keys, JSON shapes |
| [07-KNOWLEDGE-BASE](docs/07-KNOWLEDGE-BASE.md) | Ingest, OCR, organizer, graph, autofill |
| [08-RAG](docs/08-RAG.md) | Retrieval, caches, the Ask Vik ladder, live court |
| [API](docs/API.md) | REST and WebSocket reference |
| [adr/](docs/adr/) | Architecture decisions |

## Layout

| Path | Contents |
|---|---|
| `frontend/` | Next.js app, E2E tests (`e2e/`), demo specs (`demo/`) |
| `backend/` | FastAPI app (`vik/`), migrations, tests, sample companies (`data/samples/`) |
| `docs/` | Product and technical docs, ADRs, the style reference (`design/`) |
| `brand/` | The VIK logo set (`vik/`) and the script that builds it |

---

No investment advice. Vik prepares founders for investor conversations. It doesn't value companies or recommend investments.
