# Vik frontend

Next.js 16 app for Vik, the AI venture capitalist. Its look is inspired by trionn.com: dark space scenes with light streaks, grey "paper" light mode, tight grotesk type and a 3D wireframe mark. No Trionn assets or copy are used.

## Run

```bash
npm install
npm run dev
```

Open http://localhost:3000.

## Pages

| Route | What it shows |
|---|---|
| `/` | Landing page: VIK mark, headline, Get started |
| `/knowledge` | Knowledge base: imported files as notes, folders, graph, Fill dashboard |
| `/dashboard` | Gross-margin ring, ARR card, readiness orb, MRR/burn chart, what the panel will ask first |
| `/simulation` | VC panel, slide view with claim checks, live/after interruption toggle, scoring and metrics, Q&A after the pitch |
| `/areopagus` | Investor personas and the builder |
| `/reports` | Every session written up, with the score trend per company |

## Screenshots

`npm run screenshots` captures every page in dark and light at desktop (1440px) and phone (390px) width, plus the preloader, into `docs/screenshots/pages/`. Start the app first:

```bash
npm run build && npm start
```

```bash
npm run screenshots
```

The script uses your installed Edge or Chrome. Set `BASE_URL` if the app isn't on port 3000.

`docs/screenshots/reference/` holds the trionn.com captures used as the style reference. They're for internal reference only; don't publish them.

## End-to-end tests

`e2e/` holds Playwright tests for the dashboard: every widget fits on one screen above the chat at 1366×768, 1440×900 and 1920×1080 with no overlaps, widgets explain their numbers, charts draw and show their tables, chat-added widgets fit and can be removed, zoom and reset work, and a battery of questions about the data gets footnoted answers that clear the prompt and never cover a widget. With the API and the web app running (see the repo README), run:

```bash
npm run test:e2e
```

Global setup signs in with `ACCESS_CODE` (default `vik-demo`) and, if nothing is confirmed, imports a sample company's files (`E2E_SAMPLE`, default `harbor-labs`) into the knowledge base, fills the dashboard from it and confirms. Tests share the dashboard, run one at a time, and remove any widget they add and restore the time range afterwards. Set `BASE_URL` if the app isn't on port 3000.

## Demo videos

`demo/` holds one Playwright spec per tab that clicks through the app at a human pace, with a visible cursor and captions. `npm run demo:record` saves the recordings and `npm run demo:videos` encodes the MP4s and GIFs in `../docs/demo/` (needs ffmpeg). See "Recording demos" in the [repo README](../README.md).

## The dashboard's building blocks

- `components/dashboard/registry.tsx`: one renderer per widget template (`kpi`, `gauge_ring`, `line`, `bar`, …) plus the missing-data tile. Add a template here and the grid, dashboard and chat use it.
- `components/dashboard/modules.tsx`: panels that aren't stored widgets (`readiness`, `attack_list`) and the `Module` renderer for `role:<role>` widgets.
- `components/dashboard/layout.ts`: the top row as data (columns, stacked modules, height shares). Every widget not placed there fills the row below, so all of them stay above the chat.

## Where things live

- `lib/court.ts`: the court engine's chair id, used by the Simulation's Q&A after the pitch.
- `components/court`: claim and knowledge chips and the score bars, shared by the Simulation and Reports.
- `components/fx`: the preloader, light streaks and WebGL scenes (the VIK mark and readiness orb).
- `components/ui`: pills with letter roll, panels with corner marks, VC glyphs.
- `public/brand/`: the VIK wordmark the lockup and landing use, written by `../brand/build.py` (as are `app/icon.svg`, `app/apple-icon.png` and `app/opengraph-image.png`).
- `app/globals.css`: theme tokens for `data-theme="dark"` and `data-theme="light"`.
