"""Weather icon sets for the weather activity (see assets/icons/README.md for sources and licenses).

Every set answers icon(condition, night, size) -> list of frames, where a frame is
[(x, y, (r, g, b)), ...] inside a size x size box. Static sets return one frame.

Conditions (from WMO weather codes, see condition()):
    clear, partly, cloudy, fog, drizzle, rain, snow, thunder
"""
from functools import lru_cache

from pixelgrid.config import ROOT

ICON_DIR = ROOT / "assets" / "icons"
CONDITIONS = ("clear", "partly", "cloudy", "fog", "drizzle", "rain", "snow", "thunder")


def condition(code):
    """WMO weather code (Open-Meteo `weather_code`) -> one of CONDITIONS."""
    code = int(code)
    if code == 0:
        return "clear"
    if code in (1, 2):
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "thunder"
    return "cloudy"


# --- pixel: hand-drawn 9x9 art, scaled up by whole multiples (crisp at any size) ---

PALETTE = {
    "Y": (255, 190, 0),     # sun
    "O": (255, 110, 0),     # sun rays
    "W": (210, 210, 215),   # light cloud
    "G": (110, 110, 125),   # dark cloud
    "B": (30, 110, 255),    # rain
    "S": (255, 255, 255),   # snow
    "L": (255, 230, 0),     # lightning
    "M": (240, 220, 140),   # moon
    "F": (120, 120, 130),   # fog
}

PIXEL_ART = {
    "clear": """
        ....O....
        .O.....O.
        ...YYY...
        ..YYYYY..
        O.YYYYY.O
        ..YYYYY..
        ...YYY...
        .O.....O.
        ....O....""",
    "clear-night": """
        ...MMM...
        ..MM.....
        .MM......
        .MM......
        .MM......
        .MM.....M
        ..MM...MM
        ...MMMMM.
        .........""",
    "partly": """
        .....O..O
        ....YYY..
        ...YYYYYO
        ..GGYYYY.
        GGWWWYYY.
        GWWWWWWWW
        .WWWWWWW.
        .........
        .........""",
    "partly-night": """
        .....MMM.
        ....MM...
        ....M....
        ..GGM...M
        GGWWWMMM.
        GWWWWWWWW
        .WWWWWWW.
        .........
        .........""",
    "cloudy": """
        .........
        .........
        ...GG....
        .GGWWW...
        GGWWWWWW.
        GWWWWWWWW
        .WWWWWWW.
        .........
        .........""",
    "fog": """
        .........
        FFFFFFF..
        .........
        ..FFFFFFF
        .........
        FFFFFFF..
        .........
        ..FFFFFFF
        .........""",
    "drizzle": """
        ...GG....
        .GGGGGG..
        GGGGGGGGG
        .GGGGGGG.
        .........
        ..B...B..
        .........
        ....B....
        .........""",
    "rain": """
        ...GG....
        .GGGGGG..
        GGGGGGGGG
        .GGGGGGG.
        .........
        .B..B..B.
        B..B..B..
        .........
        .B..B..B.""",
    "snow": """
        ...WW....
        .WWWWWW..
        WWWWWWWWW
        .WWWWWWW.
        .........
        .S...S...
        ...S...S.
        .S...S...
        .........""",
    "thunder": """
        ...GG....
        .GGGGGG..
        GGGGGGGGG
        GGGLGGGGG
        .GLLGGGG.
        ..LL.....
        ...LL....
        ...L.....
        ..L......""",
}


def _art(name):
    rows = [r.strip() for r in PIXEL_ART[name].strip().splitlines()]
    return [(x, y, PALETTE[ch]) for y, row in enumerate(rows) for x, ch in enumerate(row) if ch != "."]


def pixel_icon(cond, night, size):
    key = f"{cond}-night" if night and f"{cond}-night" in PIXEL_ART else cond
    art = _art(key)
    scale = max(1, size // 9)
    pad = (size - 9 * scale) // 2 if size >= 9 else 0
    return [[(pad + x * scale + dx, pad + y * scale + dy, c)
             for x, y, c in art for dy in range(scale) for dx in range(scale)]]


# --- twemoji: 72x72 color emoji, smoothly downscaled ---

TWEMOJI = {
    "clear": "2600", "clear-night": "1f319", "partly": "26c5", "partly-night": "2601",
    "cloudy": "2601", "fog": "1f32b", "drizzle": "1f326", "rain": "1f327",
    "snow": "1f328", "thunder": "26c8",
}


def _flatten(img, min_level=24):
    """RGBA image -> [(x, y, rgb)] composited on black, dropping near-black pixels."""
    out = []
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = img.getpixel((x, y))
            rgb = (r * a // 255, g * a // 255, b * a // 255)
            if sum(rgb) >= min_level:
                out.append((x, y, rgb))
    return out


def twemoji_icon(cond, night, size):
    from PIL import Image
    key = f"{cond}-night" if night and f"{cond}-night" in TWEMOJI else cond
    img = Image.open(ICON_DIR / "twemoji" / f"{TWEMOJI[key]}.png").convert("RGBA")
    return [_flatten(img.resize((size, size), Image.LANCZOS))]


# --- lbc: LoveBootCaptain's animated Unicorn HAT icons (16x16 HD, 8x8 SD) ---

LBC = {
    "clear": "clear-day", "clear-night": "clear-night", "partly": "partly-cloudy-day",
    "partly-night": "partly-cloudy-night", "cloudy": "cloudy", "fog": "fog",
    "drizzle": "rain", "rain": "rain", "snow": "snow", "thunder": "rain",  # no thunder art
}


def lbc_icon(cond, night, size):
    from PIL import Image
    key = f"{cond}-night" if night and f"{cond}-night" in LBC else cond
    tile = 8 if size <= 8 else 16
    strip = Image.open(ICON_DIR / "lbc" / ("SD" if tile == 8 else "HD") / f"{LBC[key]}.png").convert("RGBA")
    frames = []
    for i in range(strip.width // tile):
        frame = strip.crop((i * tile, 0, (i + 1) * tile, tile))
        if size != tile:
            frame = frame.resize((size, size), Image.NEAREST if size % tile == 0 else Image.LANCZOS)
        frames.append(_flatten(frame))
    return frames


ICON_SETS = {"pixel": pixel_icon, "twemoji": twemoji_icon, "lbc": lbc_icon}


@lru_cache(maxsize=None)
def icon(icon_set, cond, night, size):
    """Frames for one icon, cached (decoding PNGs on a Pi takes a moment)."""
    return ICON_SETS[icon_set](cond, night, size)
