"""Clock widget: the clock activity's exact layout, drawn over any activity.

Defaults come from activities.clock (INHERITS), so it always matches the clock
activity, with widgets.clock on top: date_format "" hides the date, and top /
outline / outline_color are widget-only.

The outline is a ring of outline_color pixels around every character, so
whatever the activity draws underneath (falling snow, ...) never touches the
text.
"""
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
        "top": (int, "row of the top of the time's digits; -1 centers the clock vertically"),
        "outline": (int, f"outline thickness in pixels around every character, 0-{MAX_OUTLINE} (0 = none)"),
        "outline_color": (str, "outline color as #rrggbb (black keeps other content off the text)"),
    }

    def validate(self):
        self.clock = ClockActivity({k: self.opts[k] for k in ClockActivity.OPTIONS})  # validates the clock options
        if not -1 <= self.opts["top"] <= SIZE - 1:
            raise ValueError(f"clock widget: top must be -1 (centered) or 0-{SIZE - 1}")
        if not 0 <= self.opts["outline"] <= MAX_OUTLINE:
            raise ValueError(f"clock widget: outline must be 0-{MAX_OUTLINE}")
        self.outline_color = parse_color(self.opts["outline_color"])

    def enter(self):
        self.clock.enter()
        self.shown = None
        self.text = []
        self.ring = []

    def exit(self):
        self.clock.exit()

    def update(self, dt):
        now = datetime.now(self.clock.tz)
        key = now.strftime("%Y%m%d%H%M")
        if key == self.shown:
            return
        self.shown = key
        top = None if self.opts["top"] < 0 else self.opts["top"]
        self.text = [p for p in self.clock.layout(now, top=top) if 0 <= p[0] < SIZE and 0 <= p[1] < SIZE]
        self.ring = self.outline_pixels({(x, y) for x, y, _ in self.text}, self.opts["outline"])

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
