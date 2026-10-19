"""Knowledge base: one global vault of markdown and CSV notes made from whatever the founder drops in.

- `convert` turns any file (CSV, XLSX, PDF, DOCX, PPTX, images, HTML, JSON, text, zips) into notes,
  by code: text layers, OCR (tesseract) where there is none, chart data read from the Office XML.
- `organize` files the notes into folders, tags and summarizes them, links related notes and
  writes hub notes. Gemini does this when a key is set; a keyword heuristic otherwise. Any number in
  model-written text must appear in the notes it describes, or that sentence is dropped.
- `autofill` builds a draft engagement (profile, uploads → column mappings, document facts) from
  the vault for the founder to review in the intake flow.
- `tools` gives the agents read-only `kb_search` / `kb_read`; they quote notes verbatim, cited by path.
"""
