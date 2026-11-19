"""Clock widget: the clock activity's exact layout, drawn over any activity.

Defaults come from activities.clock (INHERITS), so it always matches the clock
activity, with widgets.clock on top: date_format "" hides the date, and the
position and outline options are widget-only.

Position, CSS-style (-1 = auto): `top` puts the top of the time's digits on that
row, or `bottom` keeps the block's lowest pixel that many rows above the bottom
edge; `left` / `right` keep the block that many pixels from that edge. With
neither set, it's centered on that axis. If both are set, `bottom` wins over
`top` (so `bottom` alone works despite the config's default `top`), and `left`
wins over `right`. The block is the clock's visible pixels
(time, AM/PM, date), so a left- or right-anchored clock keeps that edge fixed as
the time gets wider (9:59 -> 10:00). The widget can be listed more than once
(e.g. two timezones), each with its own options.

The outline is a ring of outline_color pixels around every character, so
whatever the activity draws underneath (falling snow, ...) never touches the
text.
"""
import math
from datetime import datetime

from pixelgrid.matrix import SIZE
from pixelgrid.activities.clock import ClockActivity, parse_color
from pixelgrid.widgets.base import Widget

MAX_OUTLINE = 3


class ClockWidget(Widget):
    name = "clock"
    INHERITS = ("clock",)
    OPTIONS = {
        **ClockActivity.OPTIONS,
        "top": (int, "row of the top of the time's digits; -1 = auto (centered, unless bottom is set)"),
        "bottom": (int, "rows between the clock's lowest pixel and the bottom edge; -1 = auto (wins over top)"),
        "left": (int, "pixels between the left edge and the clock; -1 = auto (centered, unless right is set)"),
        "right": (int, "pixels between the clock and the right edge; -1 = auto"),
        "outline": (int, f"outline thickness in pixels around every character, 0-{MAX_OUTLINE} (0 = none)"),
        "outline_color": (str, "outline color as #rrggbb (black keeps other content off the text)"),
        "digit_bounce": (int, "how high (pixels) each digit of the time rides a sine wave that runs across "
                              "the time; their normal place is the bottom of the wave; 0 = still"),
        "colon_bounce": (int, "the same for the colon(s); 0 = still"),
        "colon_raise": (int, "pixels the colon's resting place sits above where the font puts it"),
        "bounce_period": (float, "seconds for one bob up and down (1 = a digital clock's blink pace)"),
        "bounce_every": (float, "seconds between ripples: each character bobs once, then all rest until the "
                                "next (in step with the clock's seconds); 0 = a continuous wave"),
        "bounce_stagger": (float, "seconds each character lags the one to its left, so the wave travels "
                                  "left to right (0 = all together)"),
    }

    def validate(self):
        self.clock = ClockActivity({k: self.opts[k] for k in ClockActivity.OPTIONS})  # validates the clock options
        for key in ("top", "bottom", "left", "right"):
            if not -1 <= self.opts[key] <= SIZE - 1:
                raise ValueError(f"clock widget: {key} must be -1 (auto) or 0-{SIZE - 1}")
        if not 0 <= self.opts["colon_raise"] <= 4:
            raise ValueError("clock widget: colon_raise must be 0-4")
        if not 0 <= self.opts["colon_bounce"] <= 4 or not 0 <= self.opts["digit_bounce"] <= 4:
            raise ValueError("clock widget: colon_bounce and digit_bounce must be 0-4")
        if self.opts["bounce_period"] <= 0 or self.opts["bounce_stagger"] < 0 or self.opts["bounce_every"] < 0:
            raise ValueError("clock widget: bounce_period must be > 0 and bounce_stagger 0 or more")
        if not 0 <= self.opts["outline"] <= MAX_OUTLINE:
            raise ValueError(f"clock widget: outline must be 0-{MAX_OUTLINE}")
        self.outline_color = parse_color(self.opts["outline_color"])

    def enter(self):
        self.clock.enter()
        self.shown = None
        self.text = []
        self.ring = []
        self.chars = []    # [(amplitude, {(x, y), ...})] per character of the time, left to right
        self.base = []     # the laid-out text with nothing raised
        self.frames = {}   # (lift per character) -> (text, ring), filled as the wave reaches each shape

    def exit(self):
        self.clock.exit()

    def update(self, dt):
        now = datetime.now(self.clock.tz)
        key = now.strftime("%Y%m%d%H%M")
        if key != self.shown:
            self.shown = key
            self.layout(now)
        lifts = self.lifts(now)
        if lifts not in self.frames:
            self.frames[lifts] = self.render(lifts)
        self.text, self.ring = self.frames[lifts]

    def lifts(self, now):
        """Pixels each time character is raised right now. Each bobs up and back down once per
        bounce_period (1 - cos, so it eases out of and back into rest at the bottom), lagging
        its left neighbor by bounce_stagger, so a ripple runs left to right. With bounce_every,
        a single ripple starts every bounce_every seconds (on the clock's own seconds: :00, :05,
        ...) and the characters rest in between; with 0, the wave never stops."""
        o = self.opts
        t = now.minute * 60 + now.second + now.microsecond / 1e6
        if o["bounce_every"] > 0:
            t %= o["bounce_every"]
        out = []
        for k, (amp, _) in enumerate(self.chars):
            p = (t - k * o["bounce_stagger"]) / o["bounce_period"]
            if o["bounce_every"] > 0 and not 0 <= p < 1:
                out.append(0)   # waiting for the ripple to reach it, or done for this round
                continue
            out.append(round(amp * (1 - math.cos(2 * math.pi * p)) / 2))
        return tuple(out)

    def layout(self, now):
        """Place the clock (top/bottom/left/right) and note each time character's pixels."""
        o = self.opts
        pixels = self.clock.layout(now, top=None if o["top"] < 0 or o["bottom"] >= 0 else o["top"])
        xs = [x for x, _, _ in pixels]
        ys = [y for _, y, _ in pixels]
        dx = dy = 0
        if o["left"] >= 0:
            dx = o["left"] - min(xs)
        elif o["right"] >= 0:
            dx = (SIZE - 1 - o["right"]) - max(xs)
        if o["bottom"] >= 0:
            dy = (SIZE - 1 - o["bottom"]) - max(ys)
        # The colon rests colon_raise pixels above where the font puts it.
        colon = {(x + dx, y + dy) for ch, pts in self.clock.time_chars if ch == ":" for x, y in pts}
        up = o["colon_raise"]
        self.base = [(x + dx, y + dy - (up if (x + dx, y + dy) in colon else 0), c) for x, y, c in pixels]
        self.chars = [(o["colon_bounce"] if ch == ":" else o["digit_bounce"],
                       {(x + dx, y + dy - (up if ch == ":" else 0)) for x, y in pts})
                      for ch, pts in self.clock.time_chars]
        self.frames = {}

    def render(self, lifts):
        """(text, outline) with each time character raised by its lift."""
        lift_at = {}
        for (_, pts), lift in zip(self.chars, lifts):
            for p in pts:
                lift_at[p] = lift
        text = [(x, y - lift_at.get((x, y), 0), c) for x, y, c in self.base]
        text = [(x, y, c) for x, y, c in text if 0 <= x < SIZE and 0 <= y < SIZE]
        return text, self.outline_pixels({(x, y) for x, y, _ in text}, self.opts["outline"])

    def bounds(self):
        """Box around the clock's text (not its outline), covering both ends of the bounce;
        laid out now if it hasn't been yet."""
        if not self.base:
            self.update(0)
        if not self.base:
            return None
        rise = max((amp for amp, _ in self.chars), default=0)
        xs = [x for x, _, _ in self.base]
        ys = [y for _, y, _ in self.base]
        return min(xs), max(0, min(ys) - rise), max(xs), max(ys)

    @staticmethod
    def outline_pixels(ink, width):
        """Every panel pixel within `width` (including diagonals) of the ink, minus the ink itself."""
        ring = set()
        for x, y in ink:
            for dy in range(-width, width + 1):
                for dx in range(-width, width + 1):
                    ring.add((x + dx, y + dy))
        return [(x, y) for x, y in ring - ink if 0 <= x < SIZE and 0 <= y < SIZE]

    def draw(self, canvas):
        r, g, b = self.outline_color
        for x, y in self.ring:
            canvas.SetPixel(x, y, r, g, b)
        for x, y, (r, g, b) in self.text:
            canvas.SetPixel(x, y, r, g, b)
