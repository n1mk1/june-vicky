"""OCR with tesseract (pytesseract) and PDF page rendering (pypdfium2).

Optional at runtime: the Docker image ships tesseract; a machine without it still converts every
text layer and marks the pages it could not read.
"""

import functools
import io
import logging
import math
from collections.abc import Iterator
from typing import Any

from vik.config import get_settings

log = logging.getLogger(__name__)
MIN_SIDE = 60  # skip icons and rules
MAX_PIXELS = 25_000_000  # tesseract slows to a crawl past this; downscale first


@functools.cache
def available() -> bool:
    try:
        import pytesseract

        cmd = get_settings().tesseract_cmd
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        pytesseract.get_tesseract_version()
        return True
    except Exception as e:
        log.info("OCR unavailable (tesseract not found): %s", e)
        return False


def _prepare(img: Any) -> Any | None:
    if img.width < MIN_SIDE or img.height < MIN_SIDE:
        return None
    if img.width * img.height > MAX_PIXELS:
        scale = (MAX_PIXELS / (img.width * img.height)) ** 0.5
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    return img


def image_text(img: Any, *, sparse: bool = False) -> str:
    """Text in a PIL image. `sparse` (psm 11) finds scattered labels: chart axes, data labels, slides."""
    if not available():
        return ""
    import pytesseract

    prepared = _prepare(img)
    if prepared is None:
        return ""
    try:
        text = pytesseract.image_to_string(prepared, config="--psm 11" if sparse else "--psm 3")
    except Exception as e:
        log.warning("OCR failed on an image: %s", e)
        return ""
    return _tidy(text, sparse=sparse)


def bytes_text(data: bytes, *, sparse: bool = False) -> str:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            return image_text(img, sparse=sparse)
    except Exception as e:
        log.info("not an image tesseract can read: %s", e)
        return ""


def render_scale(
    width_pt: float, height_pt: float, scale: float = 2.0, max_pixels: int = MAX_PIXELS
) -> float:
    """The render scale for a page of this size: `scale`, lowered so the bitmap stays within `max_pixels`.
    A PDF a few KB long can declare a page metres wide; rendering it at full scale would exhaust memory."""
    area = float(width_pt) * float(height_pt)
    if not area > 0:
        return scale
    return min(scale, math.sqrt(max_pixels / area))


def pdf_pages_as_images(data: bytes, pages: list[int], scale: float = 2.0) -> Iterator[tuple[int, Any]]:
    """(page number 1-based, PIL image) for each requested page, never larger than MAX_PIXELS."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        for n in pages:
            if 1 <= n <= len(pdf):
                page = pdf[n - 1]
                try:
                    w, h = page.get_size()
                    yield n, page.render(scale=render_scale(w, h, scale)).to_pil()
                finally:
                    page.close()
    finally:
        pdf.close()


def _tidy(text: str, *, sparse: bool) -> str:
    lines = [ln.rstrip() for ln in text.replace("\x0c", "").splitlines()]
    if sparse:
        lines = [ln for ln in lines if ln.strip()]
    out: list[str] = []
    for ln in lines:
        if not ln.strip() and out and not out[-1].strip():
            continue
        out.append(ln)
    return "\n".join(out).strip()
