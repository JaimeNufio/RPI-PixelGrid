"""Registry of widgets (overlays drawn on top of any activity). Add new widgets here."""
from pixelgrid.widgets.clock import ClockWidget

WIDGETS = {cls.name: cls for cls in (ClockWidget,)}
