"""Base class for display activities: animations, clocks, weather, tickers, ...

See pixelgrid/component.py for the lifecycle and class attributes. An activity
fills the whole panel; widgets (pixelgrid/widgets/) are drawn on top of it.

Screens: an activity can cycle through several full-panel screens (weather: "now",
"forecast"). List them in SCREENS and declare an optional "<screen>_seconds" option
for each (type optional(float)). Each screen gets its own value; screens left at
null share the play time evenly: (duration - fixed screens) / unset screens, so
weather playing for 120s shows each screen for 60s. With no duration (until
replaced), unset screens get SCREEN_FALLBACK seconds each. 0 skips a screen.
"""
from pixelgrid.component import Component

SCREEN_FALLBACK = 30.0   # seconds per unset screen when the play has no duration


class Activity(Component):
    SECTION = "activities"
    MASK_BAD_PIXELS = True  # the selftest turns this off so bad pixels stay visible
    SCREENS = ()            # screen names, in play order
    duration = None         # seconds this play lasts, set by the manager before enter(); None = until replaced

    def update(self, dt):
        raise NotImplementedError

    def screen_times(self):
        """[(screen, seconds)] for one cycle, skipping screens set to 0."""
        fixed = {s: self.opts.get(f"{s}_seconds") for s in self.SCREENS}
        unset = [s for s, v in fixed.items() if v is None]
        share = SCREEN_FALLBACK
        if unset and self.duration:
            left = self.duration - sum(v for v in fixed.values() if v)
            share = left / len(unset) if left > 0 else SCREEN_FALLBACK
        times = [(s, share if v is None else v) for s, v in fixed.items()]
        return [(s, sec) for s, sec in times if sec > 0]

    def screen_at(self, t):
        """The screen showing `t` seconds into the play."""
        times = self.screen_times()
        t %= sum(sec for _, sec in times)
        for s, sec in times:
            if t < sec:
                return s
            t -= sec
        return times[-1][0]

    def validate_screens(self):
        for s in self.SCREENS:
            v = self.opts.get(f"{s}_seconds")
            if v is not None and v < 0:
                raise ValueError(f"{self.name}: {s}_seconds must be 0 or more (or null to share evenly)")
        if self.SCREENS and all(self.opts.get(f"{s}_seconds") == 0 for s in self.SCREENS):
            raise ValueError(f"{self.name}: every screen is set to 0 seconds")
