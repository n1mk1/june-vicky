"""Build the Vik brand assets from the glyph outlines below: the SVG and PNG logos in `brand/vik/`, the copies
the web app serves (`frontend/public/brand/`), and its icons and share image (`frontend/app/`).

Run from the repo root (Pillow comes with the backend's environment):

    uv --directory backend run python ../brand/build.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "brand" / "vik"
PUBLIC = ROOT / "frontend" / "public" / "brand"
APP = ROOT / "frontend" / "app"

# Cap height 142, stroke ~27; the I's top and the K's leg are cut by "/" knife cuts.
CAP = 142
GLYPHS: list[tuple[str, float, list[list[tuple[float, float]]]]] = [
    ("V", 0, [[(0, 0), (30, 0), (62, 94.7), (94, 0), (124, 0), (76, 142), (48, 142)]]),
    ("I: knife-cut top", 158, [[(27, 0), (27, 142), (0, 142), (0, 33)]]),
    (
        'K: leg sliced off by a "/" gap',
        229,  # straight stem after a straight stem: a wider gap than the I-C pair it had before
        [
            [(0, 0), (27, 0), (27, 142), (0, 142)],
            [(86, 0), (124, 0), (27, 98.7), (27, 60)],
            [(58.3, 81.1), (77.5, 61.6), (137.8, 142), (104, 142)],
        ],
    ),
]
WIDTH = 366.8  # the K's right edge
PAD_X, PAD_Y = 46, 53  # the wordmark's clear space


def _pts(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:g},{y:g}" for x, y in points)


def svg_body(indent: str = "    ", comments: bool = True) -> str:
    lines = []
    for name, dx, polys in GLYPHS:
        if comments:
            lines.append(f"{indent}<!-- {name} -->")
        if len(polys) == 1:
            lines.append(f'{indent}<polygon transform="translate({dx:g} 0)" points="{_pts(polys[0])}"/>')
        else:
            lines.append(f'{indent}<g transform="translate({dx:g} 0)">')
            lines += [f'{indent}  <polygon points="{_pts(p)}"/>' for p in polys]
            lines.append(f"{indent}</g>")
    return "\n".join(lines)


def wordmark_svg(fill: str) -> str:
    w, h = round(WIDTH + 2 * PAD_X), CAP + 2 * PAD_Y
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">\n'
        "  <title>VIK</title>\n"
        f'  <g fill="{fill}" transform="translate({PAD_X} {PAD_Y})">\n{svg_body()}\n  </g>\n</svg>\n'
    )


def square_fit(size: float = 250, margin: float = 28) -> tuple[float, float, float]:
    scale = (size - 2 * margin) / WIDTH
    return margin, (size - CAP * scale) / 2, scale


def square_svg(style: str | None = None) -> str:
    x, y, k = square_fit()
    head = f"  <style>{style}</style>\n" if style else ""
    fill = "" if style else ' fill="#000"'
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 250 250" width="250" height="250">\n'
        "  <title>VIK</title>\n"
        f"{head}"
        f'  <g{fill} transform="translate({x:g} {y:.2f}) scale({k:.5f})">\n{svg_body()}\n  </g>\n</svg>\n'
    )


# ---------------------------------------------------------------- raster

SS = 4  # supersampling for smooth edges


def draw_wordmark(img: Image.Image, x: float, y: float, scale: float, color: tuple) -> Image.Image:
    """The wordmark drawn onto `img` (RGBA) with its top-left at (x, y), `scale` px per unit."""
    big = Image.new("L", (img.width * SS, img.height * SS), 0)
    d = ImageDraw.Draw(big)
    for _name, dx, polys in GLYPHS:
        for poly in polys:
            d.polygon([((x + (dx + px) * scale) * SS, (y + py * scale) * SS) for px, py in poly], fill=255)
    mask = big.resize(img.size, Image.LANCZOS)
    layer = Image.new("RGBA", img.size, color[:3] + (255,))
    out = img.copy()
    out.paste(layer, (0, 0), mask)
    return out


def logo_png(color: tuple) -> Image.Image:
    w, h = round(WIDTH + 2 * PAD_X), CAP + 2 * PAD_Y
    base = Image.new("RGBA", (w, h), color[:3] + (0,))
    return draw_wordmark(base, PAD_X, PAD_Y, 1, color)


def square_png(size: int, color: tuple, bg: tuple | None = None) -> Image.Image:
    x, y, k = square_fit(size, size * 28 / 250)
    base = Image.new("RGBA", (size, size), bg or color[:3] + (0,))
    return draw_wordmark(base, x, y, k, color)


def dark_backdrop(w: int, h: int) -> Image.Image:
    """Near-black with a faint light from the top right, as on the landing page."""
    img = Image.new("RGBA", (w, h))
    px = img.load()
    for j in range(h):
        for i in range(w):
            t = max(0.0, 1 - ((w - i) ** 2 + j**2) ** 0.5 / (1.2 * (w**2 + h**2) ** 0.5))
            px[i, j] = (3 + round(14 * t), 4 + round(16 * t), 7 + round(22 * t), 255)
    return img


def preview() -> Image.Image:
    """The logo set at a glance: black on white, white on black, the square mark on transparency."""
    w = 700
    img = Image.new("RGB", (w, 510), (255, 255, 255))
    img.paste(Image.new("RGB", (w, 125), (0, 0, 0)), (0, 125))
    check = Image.new("RGB", (250, 250), (255, 255, 255))
    d = ImageDraw.Draw(check)
    for j in range(0, 250, 10):
        for i in range(0, 250, 10):
            if (i + j) // 10 % 2:
                d.rectangle([i, j, i + 9, j + 9], fill=(230, 230, 230))
    img.paste(check, (0, 250))
    rgba = img.convert("RGBA")
    rgba = draw_wordmark(rgba, 24, 26, 72 / CAP, (0, 0, 0))
    rgba = draw_wordmark(rgba, 24, 151, 72 / CAP, (255, 255, 255))
    x, y, k = square_fit()
    rgba = draw_wordmark(rgba, x, 250 + y, k, (0, 0, 0))
    return rgba.convert("RGB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    black, white = (0, 0, 0), (255, 255, 255)
    files = {
        OUT / "Vik_Logo.svg": wordmark_svg("#000"),
        OUT / "Vik_Logo_white.svg": wordmark_svg("#fff"),
        OUT / "Vik_Logo_250x250.svg": square_svg(),
        APP / "icon.svg": square_svg("g{fill:#000}@media (prefers-color-scheme:dark){g{fill:#fff}}"),
    }
    for name in ("Vik_Logo.svg", "Vik_Logo_white.svg", "Vik_Logo_250x250.svg"):
        files[PUBLIC / name] = files[OUT / name]
    for path, text in files.items():
        path.write_text(text, encoding="utf-8", newline="\n")
    logo_png(black).save(OUT / "Vik_Logo.png")
    logo_png(white).save(OUT / "Vik_Logo_white.png")
    square_png(250, black).save(OUT / "Vik_Logo_250x250.png")
    square_png(250, black).save(PUBLIC / "Vik_Logo_250x250.png")
    preview().save(OUT / "preview.png")
    icon = square_png(180, white, bg=(4, 5, 8, 255))
    icon.convert("RGB").save(APP / "apple-icon.png")
    og = dark_backdrop(1200, 630)
    k = 120 / CAP  # a 120 px cap height
    og = draw_wordmark(og, (1200 - WIDTH * k) / 2, (630 - CAP * k) / 2, k, white)
    og.convert("RGB").save(APP / "opengraph-image.png")
    print("wrote", len(files) + 7, "files")


if __name__ == "__main__":
    main()
