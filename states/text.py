"""Tiny BDF bitmap-font renderer shared by text modes (clock, weather, tickers, ...).

Renders text to a list of pixel offsets so modes can measure the exact ink
bounds (for precise centering) and draw with plain SetPixel calls.
Fonts live in fonts/ (public-domain X11 misc-fixed fonts; see fonts/LICENSE-README).
"""
from functools import lru_cache
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"


def font_path(name):
    """'10x20' -> fonts/10x20.bdf; a path to a .bdf file is used as-is."""
    p = Path(name)
    return p if p.suffix == ".bdf" else FONT_DIR / f"{name}.bdf"


class BDFFont:
    def __init__(self, path):
        self.glyphs = {}  # codepoint -> (advance, [(x, y), ...]) with y relative to the baseline (up is negative)
        self._parse(Path(path))

    def _parse(self, path):
        code = advance = None
        bbx = None
        rows = None
        with open(path, encoding="latin-1") as f:
            for line in f:
                parts = line.split()
                if not parts:
                    continue
                key = parts[0]
                if key == "ENCODING":
                    code = int(parts[1])
                elif key == "DWIDTH":
                    advance = int(parts[1])
                elif key == "BBX":
                    bbx = tuple(int(v) for v in parts[1:5])  # width, height, x offset, y offset
                elif key == "BITMAP":
                    rows = []
                elif key == "ENDCHAR":
                    if code is not None and code >= 0 and bbx:
                        self.glyphs[code] = (advance, self._pixels(bbx, rows or []))
                    code = advance = bbx = rows = None
                elif rows is not None:
                    rows.append(key)

    @staticmethod
    def _pixels(bbx, rows):
        w, h, xoff, yoff = bbx
        top = -(yoff + h)  # row 0 of the bitmap, relative to the baseline
        pixels = []
        for r, hexrow in enumerate(rows):
            bits = int(hexrow, 16)
            nbits = len(hexrow) * 4
            for c in range(w):
                if bits & (1 << (nbits - 1 - c)):
                    pixels.append((xoff + c, top + r))
        return pixels

    def render(self, text, space=None):
        """Pixels for `text` with the pen starting at x=0 on the baseline (y=0).
        space: width in pixels for ' ' (default: the font's own, usually a full cell)."""
        pixels = []
        pen = 0
        fallback = self.glyphs.get(ord("?"), (0, []))
        for ch in text:
            if ch == " " and space is not None:
                pen += space
                continue
            advance, glyph = self.glyphs.get(ord(ch), fallback)
            pixels.extend((pen + x, y) for x, y in glyph)
            pen += advance
        return pixels


@lru_cache(maxsize=None)
def load_font(name):
    return BDFFont(font_path(name))


def ink_bounds(pixels):
    """(min_x, min_y, max_x, max_y) of a pixel list."""
    xs = [x for x, _ in pixels]
    ys = [y for _, y in pixels]
    return min(xs), min(ys), max(xs), max(ys)
