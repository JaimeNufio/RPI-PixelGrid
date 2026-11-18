"""Tiny BDF bitmap-font renderer shared by text activities (clock, weather, tickers, ...).

Renders text to a list of pixel offsets so activities can measure the exact ink
bounds (for precise centering) and draw with plain SetPixel calls.
Fonts live in fonts/ (public-domain X11 misc-fixed fonts; see fonts/LICENSE-README).
"""
from functools import lru_cache
from pathlib import Path

from pixelgrid.config import FONT_DIR


def font_path(name):
    """'10x20' -> fonts/10x20.bdf; a path to a .bdf file is used as-is."""
    p = Path(name)
    return p if p.suffix == ".bdf" else FONT_DIR / f"{name}.bdf"


class BDFFont:
    """Glyph bitmaps are decoded on first use: the bundled fonts hold thousands of
    Unicode glyphs (10x20 has 5,205), and decoding them all up front takes ~1.5s on a Pi 4."""

    def __init__(self, path):
        self._raw = {}     # codepoint -> (advance, bbx, [hex rows]), straight from the file
        self._cache = {}   # codepoint -> (advance, [(x, y), ...]) with y relative to the baseline (up is negative)
        self._parse(Path(path))

    def _parse(self, path):
        code = advance = bbx = rows = None
        with open(path, encoding="latin-1") as f:
            for line in f:
                if rows is not None:
                    if line.startswith("ENDCHAR"):
                        if code is not None and code >= 0 and bbx:
                            self._raw[code] = (advance, bbx, rows)
                        code = advance = bbx = rows = None
                    else:
                        rows.append(line.strip())
                elif line.startswith("ENCODING"):
                    code = int(line.split()[1])
                elif line.startswith("DWIDTH"):
                    advance = int(line.split()[1])
                elif line.startswith("BBX"):
                    bbx = tuple(int(v) for v in line.split()[1:5])  # width, height, x offset, y offset
                elif line.startswith("BITMAP"):
                    rows = []

    def glyph(self, code):
        """(advance, pixels) for a codepoint, or None if the font doesn't have it."""
        if code not in self._cache:
            raw = self._raw.get(code)
            if raw is None:
                return None
            advance, bbx, rows = raw
            self._cache[code] = (advance, self._pixels(bbx, rows))
        return self._cache[code]

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
        fallback = self.glyph(ord("?")) or (0, [])
        for ch in text:
            if ch == " " and space is not None:
                pen += space
                continue
            advance, glyph = self.glyph(ord(ch)) or fallback
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
