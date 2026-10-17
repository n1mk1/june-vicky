# JUNE × VICKY frontend

Next.js 16 app for Vicky, the AI venture capitalist. Its look is inspired by trionn.com: dark space scenes with light streaks, grey "paper" light mode, tight grotesk type and a 3D wireframe mark. No Trionn assets or copy are used. Screens follow the wireframe in `../docs/design/wireframe.png`.

## Run

```bash
npm install
npm run dev
```

Open http://localhost:3000.

## Pages

| Route | What it shows |
|---|---|
| `/` | Landing page: 3D VICKY mark, headline, "Insights · Prep · Sim" links, prompt bar |
| `/dashboard` | Gross-margin ring, ARR card, readiness orb, MRR/burn chart, what the panel will ask first |
| `/preparation` | VC panel, court chat filtered by feedback, slide design and knowledge, Q&A list to repeat or study |
| `/simulation` | VC panel, slide view with claim checks, live/after interruption toggle, scoring and metrics |

## Screenshots

`docs/screenshots/pages/` holds every page in dark and light at desktop (1440px) and phone (390px) width, plus the preloader. To regenerate, start the app, then capture:

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

Global setup signs in with `ACCESS_CODE` (default `vicky-demo`) and loads a sample if nothing is confirmed. Tests share the dashboard, run one at a time, and remove any widget they add and restore the time range afterwards. Set `BASE_URL` if the app isn't on port 3000.

## The dashboard's building blocks

- `components/dashboard/registry.tsx`: one renderer per widget template (`kpi`, `gauge_ring`, `line`, `bar`, …) plus the missing-data tile. Add a template here and the grid, dashboard and chat use it.
- `components/dashboard/modules.tsx`: panels that aren't stored widgets (`readiness`, `attack_list`) and the `Module` renderer for `role:<role>` widgets.
- `components/dashboard/layout.ts`: the top row as data (columns, stacked modules, height shares). Every widget not placed there fills the row below, so all of them stay above the chat.

## Where things live

- `lib/tidewell.ts`: Tidewell monthly actuals from CSV 01, and every derived figure with its formula and source.
- `lib/panel.ts`: the James / Alex / Mark personas and the scripted Prepare and Simulation sessions. These are mock data until the FastAPI backend exists.
- `components/fx`: the preloader, light streaks and WebGL scenes (the VICKY mark and readiness orb).
- `components/ui`: pills with letter roll, panels with corner marks, the VICKY mark, VC glyphs.
- `app/globals.css`: theme tokens for `data-theme="dark"` and `data-theme="light"`.
