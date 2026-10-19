# Vik — UI / UX Design

Version 1.0 — 17 Oct 2026. Companion to [01-PRD](01-PRD.md) and [04-App flow](04-APP-FLOW.md). The v1 concept frontend lives in [`frontend/`](../frontend/README.md) and is the baseline for everything below; layouts follow the original wireframe; the style reference is [`design/trionn-style-prompt.md`](design/trionn-style-prompt.md).

---

## 1. Design language

**One line:** cinematic, monochrome, engineered. Dark "space" scenes with a V drawn in flickering digits, grey "gallery paper" light mode, tight grotesk headlines, tiny mono technical labels, hairlines with "+" corner marks. One ember accent, used sparingly for emphasis and risk. No Trionn assets or copy are used.

### 1.1 Tokens (from `app/globals.css`)

| Token | Light (`[data-theme="light"]`) | Dark (`[data-theme="dark"]`) | Use |
|---|---|---|---|
| `--bg` | `#c8c8c8` | `#040508` | page |
| `--bg-grad` | `linear-gradient(180deg,#f4f4f4,#d6d6d6 55%,#c3c3c3)` | `radial-gradient(120% 90% at 72% -10%,#11131a,#040508 58%)` | body, fixed |
| `--surface` | `rgba(255,255,255,.58)` | `rgba(14,15,19,.62)` | glass panels |
| `--surface-solid` | `#f2f2f2` | `#0c0d10` | inputs, cards |
| `--ink` / `--ink-2` | `#111214` / `#434343` | `#e2e2e2` / `#a8a8aa` | text |
| `--dim` | `rgba(17,18,20,.5)` | `rgba(216,216,216,.48)` | labels, hints |
| `--line` / `--line-strong` | `.13` / `.34` alpha ink | `.11` / `.3` alpha white | hairlines |
| `--ember` | `#d9432b` | `#e0502f` | accent: active tab tick, contradictions, speaking dot, severity, score < 2.5 |
| `--invert-bg` / `--invert-ink` | `#111214` / `#f2f2f2` | `#ededed` / `#040508` | filled pills, send button |
| `--ease-soft` | `cubic-bezier(.22,1,.36,1)` | | all motion |

Theme lives on `<html data-theme>`; a boot script restores it before paint; `ThemeToggle` is a two-option radio pill (Dark · Light).

### 1.2 Type

| Role | Font (next/font) | Class | Spec |
|---|---|---|---|
| Display | Familjen Grotesk 400–600 | `.display` | `letter-spacing:-0.055em; line-height:.92`; hero `clamp(44px,6.4vw,104px)`; KPI numerals `clamp(48px,5.4vw,80px)`; VC lines `clamp(17px,1.5vw,21px)` |
| Body / UI | Inter Tight 400–500 | body | 13.5px, line-height 1.45 |
| Technical label | Martian Mono 400 | `.label` | 10.5px uppercase, `-0.04em`, `--dim` |

Numerals are always `tabular-nums`.

### 1.3 Signature details

- **Glass panels** (`.glass`): translucent surface, 1px line, 18px backdrop blur, radius 20px. Optional `CornerMarks` ("+" just outside each corner).
- **Pills**: 32px tall, fully rounded, display font 12.5px uppercase; `solid` (inverted), `outline`, `ghost`. Letter-roll on hover (`RollLabel`: each character holds two stacked copies, 16ms stagger).
- **Blur-to-sharp** word reveal (`BlurText`) on fresh VC lines; `rise` for hero elements; `draw-stroke` for the mark; `pulse-dot` for live indicators.
- **Preloader** (first visit per session): flat paper grey, framed mark drawing itself, rolling 000→100 counter, then a clip-path wipe. Skipped on repeat visits and under `prefers-reduced-motion`.
- **Digit V** (`AsciiV`) on the landing page: the wordmark's V drawn in flickering digits on a character grid, black and white whatever the theme.
- **3D**: React Three Fiber, DPR ≤ 1.5, `ssr:false`, pointer parallax: the readiness orb (icosahedron wireframe + point sphere + ember score arc) on the dashboard.

### 1.4 Brand

The product is **Vik**; its mark is the VIK wordmark (knife-cut "I", sliced "K"). `brand/build.py` generates every asset from the glyph outlines: the logo set in `brand/vik/` (`Vik_Logo.svg`/`.png`, `Vik_Logo_white.*`, `Vik_Logo_250x250.*`, `preview.png`), the copies the web app serves from `frontend/public/brand/` (`Vik_Logo.svg`, `Vik_Logo_white.svg`, `Vik_Logo_250x250.*`), and the app's icons and share image (`app/icon.svg`, `app/apple-icon.png`, `app/opengraph-image.png`).

- `Lockup` shows the VIK wordmark: `Vik_Logo.svg` (light) and `Vik_Logo_white.svg` (dark), both in the markup with the theme showing one, so a theme switch never flashes.
- The preloader draws the wordmark's paths (from `Vik_Logo.svg`); the landing title is `Vik_Logo_white.svg`.
- There is no co-brand lockup and no drawn placeholder mark.

## 2. Layout system

- App shell: `AppHeader` (lockup + theme toggle · `TabNav` · status pill) and `<main>` with 16px side padding on phones, 24px on desktop. Desktop locks the viewport (`lg:h-dvh`) so panels scroll internally; phones stack and scroll the page.
- Tabs: **Knowledge base · Dashboard · Simulation · Areopagus · Reports**. Active tab is an inverted pill with an ember tick under it; a hairline runs under the group (wireframe). Dashboard and Simulation, the flagship tabs, carry a full-ink outline and a small ember square.
- Status pill (right of header): engagement company name + TruthPack status with a pulsing dot. States: `No source of truth` (inverted), `Mapping…`, `Confirm facts`, `{Company} · confirmed`. Clicking opens the TruthPack drawer. No hard-coded company name.
- Three-column work layout (Simulation): `[minmax(220px,260px)] [1fr] [minmax(260px,320px)]`; the roster collapses to 64px.
- Dashboard: 12-column grid, three rows (`1fr 1fr auto`), orb in the centre 5 columns spanning two rows; replaced by `DashboardGrid` (react-grid-layout) once widgets are dynamic, with the wireframe layout as the default arrangement.

## 3. Screens

### 3.1 Access gate (new)
A single centred glass panel on the dark scene: label "ACCESS", one input, a solid pill "Enter". Wrong code shakes the panel and shows "That code didn't work." No sign-up language anywhere.

### 3.2 Landing (`/`)
Black and white whatever the app theme. Top to bottom: a mono tag (ember square · "Vik" · "AI venture capitalist"), the VIK wordmark as the title, the line "Know Your Numbers Before They Do", the digit V filling the middle, one **Get started** button (to `/knowledge`) and "No investment advice." under it.
- No prompt bar here and no attach button on any prompt bar: files go into the knowledge base, and Fill dashboard plus Confirm knowledge base bring them to the agents.
- The landing page calls `/api/health` on load, which probes the API's `/healthz` (warms a free-tier API).

### 3.3 TruthPack flow (new, drawer or full-page under `/truth`)
Steps shown as mono labels `01 PROFILE · 02 MAPPING · 03 FACTS · 04 CONFIRM` across the top with a hairline progress.

1. **Company profile form**: name, country (select), currency, fiscal year start, stage, round type/size, business model (Recurring · Other), granularity (Month · Quarter). Vik's inferred values are prefilled with a dashed "inferred" chip; the founder confirms.
2. **MappingTable** (`components/truth/MappingTable.tsx`): one row per source column: source name, sample values (mono), canonical field (select), unit, confidence bar. Rows under 0.6 confidence get an ember left border and sort to the top. "Keep as raw column" option. Wide layouts show a "Transposed: months were columns" note. The unit follows the field picked (Date for the date axis, locked; a currency for money; Count for counts); picking another column as the date axis re-reads the table on save. No button per table: each step ends in one **Save and continue** that saves every table.
3. **Facts table**: name, value, unit, period, kind chip (historical / forecast / founder claim), source chip (`CSV rows 3–26`, `PDF p.4`, `You said`). Rows from documents with unverifiable `cited_text` get a dashed ember chip "Couldn't verify on page". Edit and remove inline.
4. **Coverage checklist**: metric groups with ✓ / "Needs: cohort table". Confirm button (solid pill). Confirming shows a one-line notice when it starts a new engagement.

### 3.4 Dashboard (`/dashboard`)
Default widgets (wireframe): **Gross margin ring** (two concentric rings: booked = ink, incl. support = ember), **ARR card** with `SourceChip` and a 2×2 of growth-12m, growth-recent, burn, runway (non-historical values get a "summary" badge), **Readiness orb** with the score in display type and a one-line reason, **Trend chart** (ECharts: MRR solid, carry-forward dashed in ember, burn toggle), **What they'll ask first** (attack list with severity bars), and the **Vik prompt bar** centred below.

New behaviours:
- **Widget frame** (`WidgetFrame`): label title, aside actions (pin, ask, remove), drag handle on hover, resize corner. **Missing-data tile**: dashed border, the metric name, "Needs: {upload}", and an "Upload" link.
- **Click-to-explain**: clicking a point/bar opens a glass popover: value, formula, inputs (each a link), source (row range / page / URL) and "Open source".
- **Footnotes**: every number in Vik's chat gets a superscript `¹` (`components/ui/Footnote.tsx`) with a hover card of the same content.
- **Dashboard chat** (`DashboardChat`): Vik's replies stream in the feed style; a "Widget added · {title}" generative-UI card with **Undo** appears when a tool adds a widget; "Zoomed to last 6 months" cards for frontend tools.
- **Linked interaction**: hovering one chart shows the tooltip on all; dataZoom/brush on any chart sets the dashboard-wide range (a small "Oct 25 → Sep 26 · Reset" chip appears in the header); legend toggles.
- Realtime: a widget added in another tab fades in with a `rise` animation and a brief "Updated" label.

### 3.5 Preparation (removed)
The typed court page (`/preparation`) was removed. Its roster now lives in the Simulation (§3.6), and the court runs there as the spoken Q&A after the pitch.

### 3.6 Simulation (`/simulation`)
Three columns. Left: **VcRoster**. First card is the fixed **Chair** (VIK glyph, "Vik", "Chair · reviews and scores", dashed border, no checkbox). Then the investors: glyph, name (display 17px), firm, speaking dot (ember pulse), checkbox; up to 5 seated, locked while the pitch runs. The "+" opens the Areopagus builder and comes back with the new investor seated (§3.7). Centre: the pitch room, its panel header holding the segmented control **Interrupt live · Questions after** and a full-screen toggle. Right: scoring.
- **Setup state** (no deck): a dashed drop zone "Upload your deck (PDF or PowerPoint)" (or press Start to pitch without slides) with the TruthPack gate message when unconfirmed ("Confirm a source of truth first" + link). After upload: "Pre-scanning 5 slides…" progress with per-slide ticks.
- **Slide view** (`SlideStage`): rendered slide (a PDF page rendered to JPEG by the API; a PowerPoint slide as its title and lines) in a 16:9 frame with corner marks, slide counter, prev/next, and under it the claim line: quoted claim · `ClaimChip` · "Data says: …" (or "No figures on this slide."). A five-up slide strip with a 3px status bar (ember = contradicts, ink-2 = other issue, line = clean).
- **Presenting**: one button runs the room (**Start**, then **End**); the status line reads `Presenting · m:ss`. Captions show what is said; each checked segment updates the ledgers in the right panel and pops a toast on the stage.
- **Interrupt**: the speaking dot lights on the VC card, capture pauses (status "Paused · {Name} is asking"), the question plays (TTS) with a caption; the founder's spoken answer transcribes and is judged; the investor hands back and presenting resumes automatically.
- **Q&A after** (Questions after): End → Vik's "compare notes" line while the panel confers ("The panel is conferring"); each question then plays in the asker's voice with a caption (`Q&A · question n of 6`), the mic reopens and a pause ends the answer; the button reads **End Q&A**. At the end Vik's debrief plays and an "Open the report" pill links to `/reports/{id}`.
- Right: **Scoring & metrics**: overall `x.x / 5` in display type, five dimension bars, Claims ledger, Against your notes, Delivery (talk time, filler words, seconds-per-slide bars with the worst slide in ember). Scores arrive as answers are judged; the ledgers are always live.

### 3.7 Areopagus (`/areopagus`, new)
- Header line: "The Areopagus" display headline, body intro, "+ New investor" solid pill, "Import YAML" ghost pill.
- Grid of **persona cards** (glass, 20px radius): glyph, name, archetype, main lens → secondary (mono), signature move (body), kit chips, interrupt/depth as two tiny bars, voice preview ▷ button, "Built-in" or "Custom" label. Hover: letter-roll on the "Open" link. Built-ins have Fork; custom have Edit · Duplicate · Delete.
- **Builder** (right-side sheet, ~480px, full-screen on phones):
  1. Describe: textarea + "Generate" → preview card fills in with a blur reveal.
  2. Edit form: name, archetype, cheque role; **lens-weight sliders** (12 lenses, each a hairline track with an ink thumb; kits auto-check as weights rise); tone / interrupt tendency / follow-up depth / aggression sliders; dealbreaker and question-seed chips (type + Enter); signature move; voice picker (list with ▷ preview).
  3. "How would they open?" → a VC-style message card generated against the current TruthPack.
  4. Save (solid pill) · Export YAML (ghost).
- Templates row: the 10 built-ins plus excluded archetypes (impact/ESG, family office, accelerator partner, revenue-based lender) as outline chips.
- From the Simulation roster's "+" the builder opens with `?build=1&return=simulation&panel=…`; Save goes back to `/simulation?panel=…&added=…` with the new investor seated (when a seat is free). Cancel goes back with the panel unchanged.

### 3.8 Reports (`/reports` and `/reports/[id]`, new)
- **Reports list**: engagements as sections (company name; the current one marked `ACTIVE`); each session as a row: mode chip (Simulation), date and readiness, a one-line summary (the two lenses most asked about), panel names, overall score, readiness delta (`+0.6` ink, `−0.4` ember), "Open" link. A small readiness trend sparkline per engagement.
- **Report page**: long-form document in the paper style. Left rail (desktop) with the section anchors in mono (a section with nothing in it is left out). Sections: readiness verdict with a radar (ECharts, monochrome, five axes); per-VC verdict cards with glyphs; question-by-question blocks (question · why asked · your answer · five dim bars · good / missing · correct figure with formula and source chip · strong answer with footnotes); claims ledger table; slide notes; delivery stats; knowledge gaps (term cards); action plan (numbered, each with its lens as a chip); audit notes; **Sources** (numbered, URL or row/page). Header actions: "Download Markdown", "Pitch again" (to `/simulation`).

## 4. Component inventory

| Area | Existing (keep) | New |
|---|---|---|
| `components/app` | `AppHeader`, `Lockup`, `PromptBar`, `TabNav`, `ThemeToggle`, `VcRoster` | `StatusPill`, `AccessGate` |
| `components/ui` | `Panel`+`CornerMarks`, `Pill`, `RollLabel`, `BlurText`, `VcGlyph` (squares/orbit/slash/custom + 7 more glyphs) | `Footnote`, `Segmented`, `Slider`, `Chip`, `Sheet` |
| `components/dashboard` | `KpiRing`, `StatCard`, `SourceChip` | `WidgetFrame`, `EChartWidget`, `KpiWidget`, `MissingDataTile`, `DashboardGrid`, `DashboardChat`, `ExplainPopover` |
| `components/charts` | — (replaces `TrendChart` on recharts) | `EChart` wrapper, `lib/echarts-theme.ts` |
| `components/truth` | — | `ProfileForm`, `MappingTable`, `FactsTable`, `CoverageList`, `SamplePicker` |
| `components/court` | `ClaimChip` | `DimBars`, `KnowledgeChip` |
| `components/sim` | `SlideStage`, `ScorePanel` | `DeckDropZone`, `PdfSlide` (pdf.js), `LedgerLive`, `InterruptBanner` |
| `components/areopagus` | — | `PersonaCard`, `PersonaBuilder`, `LensSliders`, `VoicePicker` |
| `components/reports` | — | `EngagementList`, `ReportDoc`, `RadarChart`, `SourcesList` |
| `components/fx` | `Preloader` (draws the VIK wordmark), `ReadinessOrb`, `scenes` | `AsciiV` (the landing's digit V) |

## 5. States and feedback

| Situation | Treatment |
|---|---|
| Loading (jobs) | Mono label + pulse dot ("Extracting facts · p.3/12"); job rows with Retry when stale |
| Missing data | Dashed tiles/chips, never blank; the copy names the upload that unlocks it |
| Non-historical figure | "summary" / "forecast" / "you said" badge beside the number |
| Contradiction | Filled ember chip; only contradictions are filled |
| Budget exceeded | Banner "Daily budget reached. Dashboards and reports still work; new VC turns resume tomorrow." |
| Offline backend (`API_INTERNAL_URL` unset) | Mocks from `lib/sample.ts`; a dim "Offline preview" label in the header |
| Declined request (valuation) | Vik's reply in normal style with a "Why I can't answer that" knowledge card explaining valuation and SAFE conversion |
| Reconnecting | Thin ember line under the header until the WebSocket resumes; no lost messages |

## 6. Motion

Only five reveal vocabularies: blur-to-sharp per word, line rise, rolling digits, stroke draw, clip-path wipe. Hover: letter roll, underline wipe, 1.0→1.05 image scale. Durations 0.35 s (UI) to 0.9 s (reveals). Under `prefers-reduced-motion`: animations collapse to ~0 ms, the preloader is skipped, 3D canvases render on demand.

## 7. Responsive

| Breakpoint | Behaviour |
|---|---|
| ≥ 1024 (lg) | Locked viewport; three columns; roster collapsible; dashboard 12-col grid |
| 768–1023 (md) | Two columns; dashboard 2-col; header grid `1fr auto 1fr` |
| < 768 | Single column; tabs scroll horizontally; orb first; roster becomes a horizontal chip row; builder sheet full-screen; minimum panel heights (300–620px) keep scroll areas usable |

Screens are captured at 1440×900 and 390×844 in both themes by `npm run screenshots`.

## 8. Accessibility

- Semantic roles already in place: `radiogroup` (theme, segmented), `tablist` (chart view, fact kinds), `aria-pressed` on roster cards, `aria-current` on tabs and slides, `aria-live="polite"` on the dashboard chat and the pitch captions, `role="img"` + labels on severity and delivery bars, `sr-only` labels for inputs and roll labels.
- Focus ring: 1px ember outline, 3px offset. Minimum tap target 32px.
- Contrast: ink on surface ≥ 7:1 in both themes; dim text used only for labels, never for essential values.
- Every chart has a text alternative: the explain popover content is also available from a keyboard-focusable "Explain" button in the widget header; tables available for every series ("View as table").
- Audio: TTS is optional and always accompanied by the text; STT has a typed fallback in every mode.

## 9. Copy rules

- Sentence case, short. Labels in mono uppercase. No exclamation marks.
- Never name the sample company in UI strings; use `{company}`.
- Every number shown gets its source; every non-historical number gets a badge.
- Vik speaks first person, warm and direct; VCs speak in their persona; scores are shown, never spoken.
- Standing footer line: "No investment advice."
