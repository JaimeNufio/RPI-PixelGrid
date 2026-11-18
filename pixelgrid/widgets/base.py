"""Base class for widgets: overlays drawn on top of any mode.

A widget has the same lifecycle and option handling as a mode (see
pixelgrid/component.py). Its defaults live in config.json under
"widgets" -> <name>. The manager draws widgets after the mode, in the order
they are listed, and then masks bad pixels.
"""
from pixelgrid.component import Component


class Widget(Component):
    SECTION = "widgets"
