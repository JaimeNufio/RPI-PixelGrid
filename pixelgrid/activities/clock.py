"""Clock activity: the time centered on the panel, AM/PM beside it, the date along the bottom.

    +----------------------------------+
    |                                  |
    |        1:55 AM    <- time large, AM/PM small and top-aligned
    |          Wed Nov 18   <- date small, date_gap rows below
    |                                  |
    +----------------------------------+

The time + date block is centered vertically as a unit. If the date is too
wide for the panel in small_font, it falls back to the 4x6 font.

Uses an explicit IANA timezone (default America/New_York) via zoneinfo, so
daylight-saving changes are handled automatically and the clock doesn't
depend on the Pi's system timezone.

Layout uses the visible pixels (ink), not font cell boxes. Positions are
measured on a reference string with every digit replaced by "8" (the widest
digit), so text doesn't shift sideways as digits change; it only re-centers
when the number of characters changes (e.g. 9:59 -> 10:00).
"""
import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pixelgrid.matrix import SIZE
from pixelgrid.activities.base import Activity
from pixelgrid.activities.text import font_path, ink_bounds, load_font

AMPM_GAP = 2            # minimum pixels between the time and AM/PM (2 or 3, see layout)
FALLBACK_FONT = "4x6"   # used for the date when it doesn't fit in small_font


def parse_color(value):
    """'#ffffff' or 'ffffff' -> (255, 255, 255)."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", value.strip())
    if not m:
        raise ValueError(f"color must look like #rrggbb, got {value!r}")
    h = m.group(1)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def reference(text):
    return re.sub(r"\d", "8", text)


def render_line(font, text, space, bump):
    """Render with `space`-pixel spaces; bump=1 widens the first space by a pixel
    (used to make a line's width even so it centers exactly)."""
    pixels = font.render(text, space=space)
    cut = text.find(" ")
    if not bump or cut < 0:
        return pixels
    split_x = max((x for x, _ in font.render(text[:cut], space=space)), default=-1) + 1
    return [(x + 1 if x >= split_x else x, y) for x, y in pixels]


class ClockActivity(Activity):
    name = "clock"
    FPS = 2  # plenty for a minute display; keeps CPU use near zero
    OPTIONS = {
        "timezone": (str, "IANA timezone, e.g. America/New_York (handles DST automatically)"),
        "time_format": (str, "strftime format for the big time; %-I:%M = 12-hour, no leading zero"),
        "ampm_format": (str, "strftime format shown small beside the time (%p = AM/PM); empty hides it"),
        "date_format": (str, "strftime format for the date line (e.g. %a %b %-d); empty hides it"),
        "font": (str, "BDF font for the time, from fonts/ (e.g. 10x20, 9x18B) or a .bdf path"),
        "small_font": (str, "BDF font for AM/PM and the date (e.g. 5x7, 4x6, 6x10)"),
        "color": (str, "time and AM/PM color as #rrggbb"),
        "date_color": (str, "date color as #rrggbb"),
        "date_gap": (int, "empty rows between the time and the date"),
        "date_space": (int, "width in pixels of a space in the date (the font's own is 5)"),
    }

    def validate(self):
        try:
            ZoneInfo(self.opts["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"clock: unknown timezone {self.opts['timezone']!r}") from None
        for key in ("font", "small_font"):
            if not font_path(self.opts[key]).is_file():
                raise ValueError(f"clock: {key} not found: {font_path(self.opts[key])}")
        if self.opts["date_gap"] < 0 or self.opts["date_space"] < 0:
            raise ValueError("clock: date_gap and date_space must be 0 or more")
        if not self.opts["time_format"].strip():
            raise ValueError("clock: time_format can't be empty")
        self.color = parse_color(self.opts["color"])
        self.date_color = parse_color(self.opts["date_color"])
        now = datetime.now()
        for key in ("time_format", "ampm_format", "date_format"):
            now.strftime(self.opts[key])  # raises ValueError on a bad format

    def enter(self):
        self.tz = ZoneInfo(self.opts["timezone"])
        self.big = load_font(self.opts["font"])
        self.small = load_font(self.opts["small_font"])
        self.fallback = load_font(FALLBACK_FONT)
        self.shown = None
        self.pixels = []  # [(x, y, (r, g, b)), ...]
        self.warned = set()

    def layout(self, now, top=None):
        """Pixels for the time, AM/PM and date at `now`, positioned on the panel.
        top: row for the top of the time's ink; None centers the whole block vertically."""
        o = self.opts
        time_text = now.strftime(o["time_format"])
        ampm_text = now.strftime(o["ampm_format"]).strip() if o["ampm_format"] else ""
        date_text = now.strftime(o["date_format"]).strip() if o["date_format"] else ""

        # Date first, to know how tall the whole block is.
        date_font = date_box = None
        if date_text:
            date_bump = 0
            for font in (self.small, self.fallback):
                date_box = ink_bounds(font.render(reference(date_text), space=o["date_space"]))
                date_font = font
                if date_box[2] - date_box[0] + 1 <= SIZE:
                    break
            if (SIZE - (date_box[2] - date_box[0] + 1)) % 2 and " " in date_text:
                date_bump = 1  # odd width: widen the first space so the margins match exactly
                date_box = ink_bounds(render_line(date_font, reference(date_text), o["date_space"], 1))
            # Height from a fixed sample with ascenders and descenders ("May" vs "Nov"
            # would otherwise shift the layout by a pixel between months).
            _, vy0, _, vy1 = ink_bounds(date_font.render("Mgy8"))
            date_box = (date_box[0], vy0, date_box[2], vy1)
        # Time + AM/PM group, centered horizontally as a unit.
        tx0, ty0, tx1, ty1 = ink_bounds(self.big.render(reference(time_text)))
        time_h = ty1 - ty0 + 1
        group_w = tx1 - tx0 + 1
        gap = AMPM_GAP
        if ampm_text:
            ax0, ay0, ax1, _ = ink_bounds(self.small.render(reference(ampm_text)))
            group_w += gap + (ax1 - ax0 + 1)
            if (SIZE - group_w) % 2:  # widen the gap a pixel so left and right margins match exactly
                gap += 1
                group_w += 1
        # Vertically, center the whole block: time, gap, date.
        block_h = time_h
        if date_text:
            block_h += o["date_gap"] + (date_box[3] - date_box[1] + 1)
        left = (SIZE - group_w) // 2
        if top is None:
            top = (SIZE - block_h) // 2
        dx, dy = left - tx0, top - ty0
        pixels = [(x + dx, y + dy, self.color) for x, y in self.big.render(time_text)]
        if ampm_text:
            adx = left + (tx1 - tx0 + 1) + gap - ax0
            ady = top - ay0  # top-aligned with the time
            pixels += [(x + adx, y + ady, self.color) for x, y in self.small.render(ampm_text)]
        self.check_fits(group_w, f"{time_text} {ampm_text}".strip())

        # Date: centered horizontally, date_gap rows below the time.
        if date_text:
            dx0, dy0, dx1, _ = date_box
            ddx = (SIZE - (dx1 - dx0 + 1)) // 2 - dx0
            ddy = top + time_h + o["date_gap"] - dy0
            pixels += [(x + ddx, y + ddy, self.date_color)
                       for x, y in render_line(date_font, date_text, o["date_space"], date_bump)]
            self.check_fits(dx1 - dx0 + 1, date_text)
        return pixels

    def check_fits(self, width, text):
        if width > SIZE and text not in self.warned:
            self.warned.add(text)
            print(f"Clock: warning, {text!r} is {width}px wide; the panel is {SIZE}px", flush=True)

    def update(self, dt):
        now = datetime.now(self.tz)
        key = now.strftime("%Y%m%d%H%M")
        if key != self.shown:
            self.shown = key
            self.pixels = self.layout(now)

    def draw(self, canvas):
        for x, y, (r, g, b) in self.pixels:
            if 0 <= x < SIZE and 0 <= y < SIZE:
                canvas.SetPixel(x, y, r, g, b)
