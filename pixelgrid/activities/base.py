"""Base class for display activities: animations, clocks, weather, tickers, ...

See pixelgrid/component.py for the lifecycle and class attributes. An activity
fills the whole panel; widgets (pixelgrid/widgets/) are drawn on top of it.

Screens: an activity can cycle through several full-panel screens (weather: "now",
"forecast"). List them in SCREENS and declare an optional "<screen>_seconds" option
for each (type optional(float); a "-" in a screen name becomes "_" in the option). Each screen gets its own value; screens left at
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

    # Data warm-up. Activities that show outside data (weather, tickers) keep it in a module-level
    # cache that outlives one play, so a new play can draw real data on its first frame.
    @classmethod
    def prefetch(cls, opts):
        """Fill caches for a play with these (merged) options. Called by the manager in a
        background thread at startup and shortly before this activity comes up. May block."""

    @classmethod
    def ready(cls, opts):
        """True if a play with these options can show real data right away. When the next
        item isn't ready, the manager keeps the current one up a little longer (READY_WAIT)."""
        return True

    @staticmethod
    def screen_option(screen):
        """The option holding a screen's seconds: "<screen>_seconds", with any "-" in the
        screen name as "_" (screen "christmas-lights" -> option "christmas_lights_seconds")."""
        return screen.replace("-", "_") + "_seconds"

    def screen_times(self):
        """[(screen, seconds)] for one cycle, skipping screens set to 0."""
        fixed = {s: self.opts.get(self.screen_option(s)) for s in self.SCREENS}
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
            v = self.opts.get(self.screen_option(s))
            if v is not None and v < 0:
                raise ValueError(f"{self.name}: {self.screen_option(s)} must be 0 or more (or null to share evenly)")
        if self.SCREENS and all(self.opts.get(self.screen_option(s)) == 0 for s in self.SCREENS):
            raise ValueError(f"{self.name}: every screen is set to 0 seconds")
