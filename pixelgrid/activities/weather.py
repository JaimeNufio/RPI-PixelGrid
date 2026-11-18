"""Weather activity, using Open-Meteo (https://open-meteo.com, free, no API key).

Alternates between two screens, always together: "now", then "forecast". By default
(now_seconds/forecast_seconds null) they split the play time evenly, e.g. 60s each of
a 120s play; set either to a number of seconds, or 0 to show only the other.

now: current conditions, today's range, the next few hours.

    +----------------------------------+
    |      [icon]  50°                 |   <- icon_set at icon_size, temp in `font`
    |        H62°   L35°               |   <- today's high / low
    |     11AM          12PM           |   <- the next `hours` whole hours
    |     [i]           [i]            |
    |     52°           55°            |
    +----------------------------------+

forecast: the next `days` days, starting tomorrow, filling the panel.

    +----------------------------------+
    |    Thu      Fri      Sat         |   <- forecast_font
    |   [icon]   [icon]   [icon]       |   <- forecast_icon_set at forecast_icon_size
    |    64°      64°      57°         |   <- high
    |    48°      50°      41°         |   <- low, in low_color
    +----------------------------------+

Data is fetched in a background thread every `refresh` seconds. Icon sets live
in weather_icons.py.

demo > 0 skips the network and cycles through every condition (and the night
variants) every `demo` seconds with made-up temperatures, for judging the icons.
"""
import json
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime

from pixelgrid.matrix import SIZE
from pixelgrid.activities.base import Activity
from pixelgrid.component import optional
from pixelgrid.activities.clock import parse_color
from pixelgrid.activities.text import font_path, ink_bounds, load_font
from pixelgrid.activities.weather_icons import CONDITIONS, ICON_SETS, condition, icon

API_URL = "https://api.open-meteo.com/v1/forecast"
ANIM_FPS = 10      # frame rate for animated icon sets
FALLBACK_FONT = "4x6"  # forecast temperatures that don't fit their column
LINE_SAMPLE = "Mgy8°"
CAPS_SAMPLE = "MT8°"  # lines without descenders (forecast day names, temperatures)  # fixed sample for text line height, so rows don't shift with content

DEMO = [(c, False) for c in CONDITIONS] + [("clear", True), ("partly", True)]
DEMO_TEMPS = [-15, 15, 45, 75, 100]   # -15 to 100 in steps of 30, plus 100 for the widest text

COMMON_OPTIONS = {
    "latitude": (float, "location latitude (decimal degrees)"),
    "longitude": (float, "location longitude (decimal degrees)"),
    "units": (str, "fahrenheit or celsius"),
    "refresh": (int, "seconds between weather fetches (Open-Meteo updates every 15 min)"),
    "icon_set": (str, "main icons: " + ", ".join(ICON_SETS)),
    "icon_size": (int, "main icon size in pixels"),
    "font": (str, "BDF font for the big temperature"),
    "small_font": (str, "BDF font for labels and small temperatures"),
    "color": (str, "temperature color as #rrggbb"),
    "label_color": (str, "label color (day names, hours, H/L) as #rrggbb"),
    "demo": (float, "seconds per condition when cycling through all icons with fake data; 0 = live"),
}


# Shared across plays (and prefetched by the manager before weather comes up), so a
# new play shows data immediately instead of a blank "--°" while the first fetch runs.
_cache = {}                  # (latitude, longitude, units) -> (time.monotonic() of fetch, data)
_cache_lock = threading.Lock()
_fetch_lock = threading.Lock()   # one network fetch at a time (prefetch + a playing instance)


def cache_key(opts):
    return round(opts["latitude"], 4), round(opts["longitude"], 4), opts["units"]


def cache_get(opts):
    """(age in seconds, data) from the shared cache, or None."""
    with _cache_lock:
        hit = _cache.get(cache_key(opts))
    return (time.monotonic() - hit[0], hit[1]) if hit else None


def cached_or_fetch(opts):
    """Data no older than opts["refresh"], fetching (and caching) if needed."""
    with _fetch_lock:
        hit = cache_get(opts)
        if hit and hit[0] < opts["refresh"]:
            return hit[1]
        data = fetch_weather(opts)
        with _cache_lock:
            _cache[cache_key(opts)] = (time.monotonic(), data)
        return data


def fetch_weather(o):
    """{"temp", "cond", "night", "high", "low",
        "hours": [(label, cond, night, temp)],   # whole hours after now
        "days": [(label, cond, high, low)]}      # today first"""
    query = urllib.parse.urlencode({
        "latitude": o["latitude"], "longitude": o["longitude"],
        "current": "temperature_2m,weather_code,is_day",
        "hourly": "temperature_2m,weather_code,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "temperature_unit": o["units"], "timezone": "auto",
        "forecast_hours": 6, "forecast_days": 4,
    })
    with urllib.request.urlopen(f"{API_URL}?{query}", timeout=15) as resp:
        raw = json.load(resp)
    cur, hourly, daily = raw["current"], raw.get("hourly") or {}, raw["daily"]
    now = datetime.fromisoformat(cur["time"])
    hours = []
    for t, temp, code, is_day in zip(hourly.get("time", []), hourly.get("temperature_2m", []),
                                     hourly.get("weather_code", []), hourly.get("is_day", [])):
        t = datetime.fromisoformat(t)
        if t > now and temp is not None and code is not None:
            hours.append((t.strftime("%-I%p"), condition(code), not is_day, round(temp)))
    days = [(date.fromisoformat(d).strftime("%a"), condition(code), round(hi), round(lo))
            for d, code, hi, lo in zip(daily["time"], daily["weather_code"],
                                       daily["temperature_2m_max"], daily["temperature_2m_min"])]
    return {"temp": round(cur["temperature_2m"]), "cond": condition(cur["weather_code"]),
            "night": not cur["is_day"], "high": days[0][2], "low": days[0][3],
            "hours": hours, "days": days}


class WeatherBase(Activity):
    FPS = 2
    ICON_KEYS = ("icon_set",)   # options naming an icon set (validated, and set FPS for animated ones)

    def validate(self):
        o = self.opts
        if not (-90 <= o["latitude"] <= 90 and -180 <= o["longitude"] <= 180):
            raise ValueError(f"{self.name}: latitude/longitude out of range")
        if o["units"] not in ("fahrenheit", "celsius"):
            raise ValueError(f"{self.name}: units must be fahrenheit or celsius")
        for key in self.ICON_KEYS:
            if o[key] not in ICON_SETS:
                raise ValueError(f"{self.name}: {key} must be one of {', '.join(ICON_SETS)}")
        if not 4 <= o["icon_size"] <= SIZE:
            raise ValueError(f"{self.name}: icon_size out of range")
        if o["refresh"] < 60:
            raise ValueError(f"{self.name}: refresh must be at least 60 seconds")
        for key in ("font", "small_font"):
            if not font_path(o[key]).is_file():
                raise ValueError(f"{self.name}: {key} not found: {font_path(o[key])}")
        self.color = parse_color(o["color"])
        self.label_color = parse_color(o["label_color"])

    def enter(self):
        o = self.opts
        self.big = load_font(o["font"])
        self.small = load_font(o["small_font"])
        _, y0, _, y1 = ink_bounds(self.small.render(LINE_SAMPLE))
        self.line_top, self.line_h = y0, y1 - y0 + 1
        if any(o[k] == "lbc" for k in self.ICON_KEYS):
            self.FPS = ANIM_FPS
        cached = cache_get(o)
        self.data = cached[1] if cached else None   # shown immediately; fetch() refreshes it (see fetch_weather())
        self.t = 0.0
        self.pixels = []
        if o["demo"] <= 0:
            self.every(o["refresh"], self.fetch)

    def fetch(self):
        """Background refresh while playing: reuse the shared cache while it's fresh."""
        self.data = cached_or_fetch(self.opts)

    @classmethod
    def prefetch(cls, opts):
        """Warm the shared cache before this activity plays (called by the manager)."""
        if opts["demo"] <= 0:
            cached_or_fetch(opts)

    @classmethod
    def ready(cls, opts):
        """True when there's data to show right away (any age; a stale cache beats a blank screen)."""
        return opts["demo"] > 0 or cache_get(opts) is not None

    def demo_data(self):
        """Fake data for step int(t / demo): every slot steps through all conditions, and every
        temperature slot through all DEMO_TEMPS (offset per slot, so each screen shows a mix)."""
        step = int(self.t // self.opts["demo"])
        pick = lambda k: DEMO[(step + k) % len(DEMO)]
        temp = lambda k: DEMO_TEMPS[(step + k) % len(DEMO_TEMPS)]
        cond, night = pick(0)
        hours = [(label, *pick(k), temp(k)) for k, label in enumerate(("10AM", "11AM", "12PM"), 1)]
        days = [(("Wed", "Thu", "Fri", "Sat")[k], pick(k)[0], temp(k), temp(k + 2)) for k in range(4)]
        return {"temp": temp(0), "cond": cond, "night": night, "high": temp(3), "low": temp(4),
                "hours": hours, "days": days}

    # --- drawing helpers ---

    def frame(self, icon_set, cond, night, size):
        frames = icon(icon_set, cond, night, size)
        return frames[int(self.t * ANIM_FPS) % len(frames)]

    def text(self, font, text, cx, top, color, line_top=None):
        """Text with its ink centered on column cx and its line top at row `top`."""
        pts = font.render(text)
        x0, y0, x1, _ = ink_bounds(pts)
        if line_top is None:
            line_top = y0
        dx = cx - (x1 - x0 + 1) // 2 - x0
        return [(x + dx, y + top - line_top, color) for x, y in pts]

    def small_text(self, text, cx, top, color):
        return self.text(self.small, text, cx, top, color, self.line_top)

    def icon_at(self, icon_set, cond, night, size, cx, top):
        left = cx - size // 2
        return [(left + x, top + y, c) for x, y, c in self.frame(icon_set, cond, night, size)]

    def update(self, dt):
        self.t += dt
        data = self.demo_data() if self.opts["demo"] > 0 else self.data
        self.pixels = self.layout(data) if data else self.text(self.big, "--°", SIZE // 2, 22, self.color)

    def draw(self, canvas):
        for x, y, (r, g, b) in self.pixels:
            if 0 <= x < SIZE and 0 <= y < SIZE:
                canvas.SetPixel(x, y, r, g, b)


class WeatherActivity(WeatherBase):
    name = "weather"
    ICON_KEYS = ("icon_set", "hour_icon_set", "forecast_icon_set")
    SCREENS = ("now", "forecast")
    OPTIONS = {
        **COMMON_OPTIONS,
        "now_seconds": (optional(float), "seconds on the now screen each cycle; null = share the "
                                         "play time evenly with other unset screens; 0 = never"),
        "forecast_seconds": (optional(float), "seconds on the forecast screen each cycle; null = share "
                                              "evenly; 0 = never"),
        "icon_gap": (int, "pixels between the big icon and the temperature"),
        "hours": (int, "upcoming whole hours on the now screen (0-3)"),
        "hour_icon_set": (str, "icons for the hourly row: " + ", ".join(ICON_SETS)),
        "hour_icon_size": (int, "hourly icon size in pixels (pixel set: 9 is native)"),
        "days": (int, "forecast days, starting tomorrow (1-3)"),
        "forecast_icon_set": (str, "forecast screen icons: " + ", ".join(ICON_SETS)),
        "forecast_icon_size": (int, "forecast screen icon size in pixels"),
        "forecast_font": (str, "BDF font for forecast day names and temperatures"),
        "low_color": (str, "forecast low temperature color as #rrggbb"),
    }
    # Fine-tuning of the now screen (pixels; + is down).
    CURRENT_SHIFT = 2   # icon + temperature
    HOURS_SHIFT = -2    # hourly row
    RANGE_SPACE = 3     # spaces between H.. and L..

    def validate(self):
        super().validate()
        o = self.opts
        if not 0 <= o["hours"] <= 3:
            raise ValueError("weather: hours must be 0-3")
        if not 1 <= o["days"] <= 3:
            raise ValueError("weather: days must be 1-3")
        if not 4 <= o["hour_icon_size"] <= SIZE // 2 or not 4 <= o["forecast_icon_size"] <= SIZE // 2:
            raise ValueError("weather: hour/forecast icon sizes out of range")
        self.validate_screens()
        if not font_path(o["forecast_font"]).is_file():
            raise ValueError(f"weather: forecast_font not found: {font_path(o['forecast_font'])}")
        self.low_color = parse_color(o["low_color"])

    def enter(self):
        super().enter()
        self.fc_font = load_font(self.opts["forecast_font"])
        # Day names and temperatures have no descenders, so measure their line on caps + digits;
        # with LINE_SAMPLE's g/y the block sat a pixel high (top margin 9, bottom 11).
        _, y0, _, y1 = ink_bounds(self.fc_font.render(CAPS_SAMPLE))
        self.fc_top, self.fc_h = y0, y1 - y0 + 1
        self.fc_fallback = load_font(FALLBACK_FONT)
        _, y0, _, y1 = ink_bounds(self.fc_fallback.render(CAPS_SAMPLE))
        self.fb_top, self.fb_h = y0, y1 - y0 + 1

    def layout(self, data):
        return self.layout_now(data) if self.screen_at(self.t) == "now" else self.layout_forecast(data)

    def layout_now(self, data):
        o = self.opts
        size, hsize = o["icon_size"], o["hour_icon_size"]
        temp_text = f"{data['temp']}°"
        tx0, ty0, tx1, ty1 = ink_bounds(self.big.render(temp_text))
        temp_w, temp_h = tx1 - tx0 + 1, ty1 - ty0 + 1
        cur_h = max(size, temp_h)
        hours = data["hours"][:o["hours"]]
        range_gap, hours_gap, row_gap = 4, 6, 2
        col_h = self.line_h + row_gap + hsize + row_gap + self.line_h
        block_h = cur_h + range_gap + self.line_h + (hours_gap + col_h if hours else 0)
        top = (SIZE - block_h) // 2
        pixels = []

        # Icon + temperature, centered as a group, vertically centered on each other.
        ctop = top + self.CURRENT_SHIFT
        left = (SIZE - (size + o["icon_gap"] + temp_w)) // 2
        pixels += [(left + x, ctop + (cur_h - size) // 2 + y, c)
                   for x, y, c in self.frame(o["icon_set"], data["cond"], data["night"], size)]
        left += size + o["icon_gap"]
        ty = ctop + (cur_h - temp_h) // 2
        pixels += [(x + left - tx0, y + ty - ty0, self.color) for x, y in self.big.render(temp_text)]

        # Today's high / low: "H" and "L" in the label color, numbers in the temperature color.
        y = top + cur_h + range_gap
        parts = [("H", self.label_color), (f"{data['high']}°", self.color), (" " * self.RANGE_SPACE, None),
                 ("L", self.label_color), (f"{data['low']}°", self.color)]
        pixels += self.colored_line(parts, y)

        # Next hours: label, icon, temperature, in equal columns.
        if hours:
            col_w = SIZE // len(hours)
            y0 = y + self.line_h + hours_gap + self.HOURS_SHIFT
            for k, (label, cond, night, temp) in enumerate(hours):
                cx = k * col_w + col_w // 2
                pixels += self.small_text(label, cx, y0, self.label_color)
                iy = y0 + self.line_h + row_gap
                pixels += self.icon_at(o["hour_icon_set"], cond, night, hsize, cx, iy)
                pixels += self.small_text(f"{temp}°", cx, iy + hsize + row_gap, self.color)
        return pixels

    def colored_line(self, parts, top):
        """[(text, color)] rendered as one centered line in small_font (color None = spacing only)."""
        text = "".join(t for t, _ in parts)
        x0, _, x1, _ = ink_bounds(self.small.render(text))
        pen = (SIZE - (x1 - x0 + 1)) // 2 - x0
        pixels = []
        for t, color in parts:
            width = sum(self.small.glyph(ord(ch))[0] for ch in t)
            if color:
                pixels += [(x + pen, y + top - self.line_top, color) for x, y in self.small.render(t)]
            pen += width
        return pixels

    def layout_forecast(self, data):
        o = self.opts
        size = o["forecast_icon_size"]
        days = data["days"][1:1 + o["days"]]
        if not days:
            return []
        gap, low_gap = 3, 2
        col_h = self.fc_h + gap + size + gap + self.fc_h + low_gap + self.fc_h
        top = (SIZE - col_h) // 2
        col_w = SIZE // len(days)
        # mx-auto: center the group of icon boxes so the left and right margins match
        # (the icons are the widest items; text is centered on each icon).
        left0 = (SIZE - ((len(days) - 1) * col_w + size)) // 2
        text = lambda t, cx, y, color: self.text(self.fc_font, t, cx, y, color, self.fc_top)
        # Temperatures like "100°" or "-15°" overflow a 21px column in 5x7: if any does, draw
        # all of this screen's temperatures in the narrower fallback font, so they stay uniform.
        temps = [f"{t}°" for _, _, hi, lo in days for t in (hi, lo)]
        widest = max(ink_bounds(self.fc_font.render(t))[2] - ink_bounds(self.fc_font.render(t))[0] + 1
                     for t in temps)
        temp_text = text
        if widest > col_w - 2:
            temp_text = lambda t, cx, y, color: self.text(self.fc_fallback, t, cx, y + self.fc_h - self.fb_h,
                                                          color, self.fb_top)
        pixels, words = [], []   # icons, and text (kept apart to measure the true extents)
        for k, (label, cond, high, low) in enumerate(days):
            cx = left0 + k * col_w + size // 2
            words += text(label, cx, top, self.label_color)
            iy = top + self.fc_h + gap
            pixels += self.icon_at(o["forecast_icon_set"], cond, False, size, cx, iy)
            hy = iy + size + gap
            words += temp_text(f"{high}°", cx, hy, self.color)
            words += temp_text(f"{low}°", cx, hy + self.fc_h + low_gap, self.low_color)
        # Text wider than its icon (e.g. "-15°") can stick out past the icon boxes: re-center
        # on the icon boxes plus the text ink. Icon boxes, not icon ink, so animated icons
        # don't make the row jitter.
        xs = [x for x, _, _ in words] + [left0, left0 + (len(days) - 1) * col_w + size - 1]
        shift = ((SIZE - 1 - max(xs)) - min(xs)) // 2
        return [(x + shift, y, c) for x, y, c in pixels + words]
