"""Self-test activity: a short panel check, run at service startup before anything else.

Phases: solid red, green, blue, white (color_seconds each), a coordinate grid
(grid_seconds), then the diagonal rainbow (rainbow_seconds). A phase with 0
seconds is skipped. Bad pixels are NOT masked here, since showing them is the point.
"""
import colorsys

from pixelgrid.matrix import SIZE
from pixelgrid.activities.base import Activity

COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]
PALETTE_STEPS = 256


def build_palette():
    out = []
    for i in range(PALETTE_STEPS):
        r, g, b = colorsys.hsv_to_rgb(i / PALETTE_STEPS, 1.0, 1.0)
        out.append((int(r * 255), int(g * 255), int(b * 255)))
    return out


class SelfTestActivity(Activity):
    name = "selftest"
    MASK_BAD_PIXELS = False
    OPTIONS = {
        "color_seconds": (float, "seconds for each solid color (red, green, blue, white)"),
        "grid_seconds": (float, "seconds for the coordinate grid (lines every 8 px, red top-left corner)"),
        "rainbow_seconds": (float, "seconds for the scrolling diagonal rainbow"),
    }

    def validate(self):
        if any(v < 0 for v in self.opts.values()):
            raise ValueError("selftest: phase lengths must be 0 or more")

    @classmethod
    def total_seconds(cls, opts):
        return 4 * opts["color_seconds"] + opts["grid_seconds"] + opts["rainbow_seconds"]

    def enter(self):
        o = self.opts
        self.phases = [("color", c, o["color_seconds"]) for c in COLORS]
        self.phases += [("grid", None, o["grid_seconds"]), ("rainbow", None, o["rainbow_seconds"])]
        self.phases = [p for p in self.phases if p[2] > 0]
        self.t = 0.0
        self.palette = build_palette()
        span = 2 * (SIZE - 1) + 1
        self.base = [[(x + y) * PALETTE_STEPS // span for x in range(SIZE)] for y in range(SIZE)]
        self.shift = 0.0
        print(f"Selftest: {len(self.phases)} phases, {self.total_seconds(o):g}s", flush=True)

    def update(self, dt):
        self.t += dt
        self.shift = (self.shift + 60 * dt) % PALETTE_STEPS  # ~60 hue steps per second

    def current_phase(self):
        t = self.t
        for kind, arg, secs in self.phases:
            if t < secs:
                return kind, arg
            t -= secs
        return self.phases[-1][:2] if self.phases else (None, None)  # hold the last phase until replaced

    def draw(self, canvas):
        kind, arg = self.current_phase()
        if kind == "color":
            canvas.Fill(*arg)
        elif kind == "grid":
            for i in range(SIZE):
                for j in range(0, SIZE, 8):
                    level = 255 if j % 16 == 0 else 60
                    canvas.SetPixel(j, i, level, level, level)
                    canvas.SetPixel(i, j, level, level, level)
            for x, y in ((0, 0), (1, 0), (0, 1)):
                canvas.SetPixel(x, y, 255, 0, 0)
        elif kind == "rainbow":
            shift = int(self.shift)
            pal = self.palette
            for y in range(SIZE):
                row = self.base[y]
                for x in range(SIZE):
                    canvas.SetPixel(x, y, *pal[(row[x] - shift) % PALETTE_STEPS])
