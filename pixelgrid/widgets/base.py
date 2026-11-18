"""Base class for widgets: overlays drawn on top of any activity.

A widget has the same lifecycle and option handling as an activity (see
pixelgrid/component.py). Its defaults live in config.json under
"widgets" -> <name>. The manager draws widgets after the activity, in the order
they are listed, and then masks bad pixels.
"""
from pixelgrid.component import Component


class Widget(Component):
    SECTION = "widgets"
