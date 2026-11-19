"""Registry of display activities. Add new activities here."""
from pixelgrid.activities.christmas import ChristmasActivity
from pixelgrid.activities.clock import ClockActivity
from pixelgrid.activities.selftest import SelfTestActivity
from pixelgrid.activities.snow import SnowActivity
from pixelgrid.activities.weather import WeatherActivity

ACTIVITIES = {cls.name: cls for cls in (SnowActivity, ClockActivity, SelfTestActivity, WeatherActivity, ChristmasActivity)}
