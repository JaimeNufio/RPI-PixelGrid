"""Registry of display states. Add new states here."""
from states.clock import ClockState
from states.snow import SnowState

STATES = {cls.name: cls for cls in (SnowState, ClockState)}
