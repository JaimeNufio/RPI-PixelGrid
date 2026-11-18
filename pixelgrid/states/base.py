"""Base class for display modes: animations, clocks, weather, tickers, ...

See pixelgrid/component.py for the lifecycle and class attributes. A mode
fills the whole panel; widgets (pixelgrid/widgets/) are drawn on top of it.
"""
from pixelgrid.component import Component


class State(Component):
    SECTION = "states"
    MASK_BAD_PIXELS = True  # the selftest turns this off so bad pixels stay visible

    def update(self, dt):
        raise NotImplementedError
