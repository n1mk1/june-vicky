# Vicky — Knowledge base

The founder drops in whatever they have: spreadsheets, decks, board packs, scans, screenshots, exports, a zip of a whole drive. Vicky turns it into one vault of markdown and CSV notes, files and links it, shows it as an Obsidian-style graph, and fills the intake flow (profile, column mappings, document facts) from it. The vault is the readable source the AI works from; the confirmed TruthPack is still what every figure is computed from.

Code: `backend/vicky/kb/`, `frontend/components/kb/`. Routes: [API.md §Knowledge base](API.md#knowledge-base). Tables: [05 §2.21–2.22](05-BACKEND-SCHEMA.md).

## Decisions

| Decision | Why |
|---|---|
| One global vault, not one per engagement | The founder keeps adding to it across engagements; "Fill dashboard" makes a new draft engagement from whatever is there now. |
| Notes and originals in Postgres (`kb_notes`, `kb_files`) | Render's disk is ephemeral and the image is read-only; the database is already backed up. |
| Conversion is code only | Rule 1: numbers come from code. Text layers (pypdf, python-docx, python-pptx, openpyxl), OCR (tesseract) for pages and images without one, and chart values read from the chart XML's cached series. No model writes or reads a number into a note. |
| The organizer may write prose, never figures | Claude writes titles, tags, summaries, related links and hub notes. `scrub_numbers` drops any sentence whose numbers aren't in the notes it describes. Offline, a keyword heuristic does the same job. |
| Autofill reuses the intake pipeline | Tables go through `POST /uploads` (so the column mapper runs as before), documents through FR-7 fact extraction (PDF/DOCX originals keep page citations; OCR'd ones go as their markdown). The founder still confirms every step. |
| Profile values carry a quote | Each autofilled field names its note and a verbatim quote; code checks the quote is in the note, and that a round size's number is in the quote. Unverified values are left blank. The intake form shows the source under each field. |
| Wikilinks are parsed on read | `[[target]]`, `[[target|alias]]`, `[[target#heading]]` resolve like Obsidian (path, path without extension, file name, title). Renames never leave stale edges; unresolved links show as ghost nodes and create the note when clicked. |
| Export is an Obsidian vault | A zip of `.md` (with YAML frontmatter: title, tags, summary, related) and `.csv` files plus `.vicky/meta.json`. Importing that zip restores paths, titles, tags, summaries, links and authorship. |

## Pipeline

```
POST /kb/import (files, folders, zips)
  └─ store_files: expand zips (≤ KB_UNZIP_MAX_BYTES, 1000 entries, no dotfiles / __MACOSX),
     skip bytes already in the vault (sha256), store originals in kb_files
  └─ job kb_ingest
       convert (in a thread: OCR blocks) → notes in inbox/ (or the zip's own folders)
       organize → move inbox notes into folders, title/tag/summarize/link, rewrite AI hubs
```

| In | Notes |
|---|---|
| CSV / TSV / JSON records | one CSV note (comma-separated, trimmed) |
| XLSX | one CSV note per sheet; a `… - charts.md` note when the workbook has charts |
| PDF | `## Page n` per page: text layer; OCR when a page has none (up to `OCR_MAX_PAGES`); OCR of embedded figures as fenced text |
| DOCX | headings, lists and tables in order; chart tables and image OCR appended |
| PPTX | `## Slide n: title` per slide: text, tables, chart values as tables, picture OCR, speaker notes |
| Images | OCR text (dense, then sparse for charts and screenshots) |
| HTML / markdown / text / YAML / XML | markdown (frontmatter title/tags/summary kept on markdown) |

Folders the organizer uses: company, financials, customers, product, market, team, fundraising, legal, operations, other. A note it files moves only if it is in `inbox/` and the founder didn't write it; notes imported inside a folder keep their path. Hub notes (`kind = hub`, `author = ai`) are rewritten after every import; editing one makes it the founder's and it is never rewritten.

## Operations

- **OCR** needs the `tesseract` binary (installed in the API image). Without it every text layer still converts, pages without one are marked unread, and `GET /kb/status` reports `ocr: false`. `TESSERACT_CMD` points at a non-PATH binary.
- **Limits:** `KB_UPLOAD_MAX_BYTES` per file (50 MB), `KB_UNZIP_MAX_BYTES` per zip (200 MB). The web app sends files in batches of 20 / 40 MB.
- **Spend:** organize calls Sonnet (medium) once per 40 new notes plus once for the hubs; autofill one Sonnet call for the profile, then the existing mapper and FR-7 calls per file.

## Agents read the vault

`backend/vicky/kb/tools.py` gives the agents two read-only tools for the Claude tool runner: `kb_search(query)` (Postgres full-text search, then an any-word keyword search with prefixes; returns each note's id, title, path, kind, summary, up to three verbatim excerpt lines and its cite token) and `kb_read(note)` (one note by id or path, up to 12 000 characters). A `Vault` object records every note its tools returned in the turn; only those can be cited.

| Agent | What it gets |
|---|---|
| Ask Vicky (`qa.answer_any`) | With a key and notes in the vault, Claude answers through `run_tools` with the kb tools next to the fact sheet. Offline (or when Claude's answer fails the audit), a question the data can't answer (`topic: not_found`) is answered by quoting the best-matching note lines, verbatim and cited (`topic: notes`). |
| Court memos (`llm.minds.build_memos`) | The kb tools are added to the investor's kit tools. Thesis, opening question, mind changers and new claims may quote notes; memos that do list them under `kb_notes`. Hypothesis evidence stays figure ids, so the no-concession rule is unchanged. |

The citation rule (rule 4 of `audit_text`, given `notes=`): `[kb:path]` must follow a quote, in double quotes, that is in that note word for word (case, whitespace, curly quotes and markdown marks don't count). Numbers inside that quote are the note's text and pass; the citation (`kind: "note"`) spans the quote and the token. A number restated outside a quote, a quote the note doesn't contain, or a path the tools never returned is a finding, so the reply falls back as before. Valuation and benchmark rules still apply inside note quotes.

## Not built yet

- The live court (spoken lines, the judge, belief updates) doesn't call the kb tools; only the pre-meeting memos do, and a line has to pass the audit without note quotes.
- No semantic (embedding) search: `kb_search` is full-text and keyword only.
- No chart reading from images by a model: chart images are OCR'd (axis labels and data labels as printed), and Office charts are read from their XML.
