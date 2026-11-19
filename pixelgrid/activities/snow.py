"""Snow activity: falling flakes that drift, land, and level out into a pile.

Flakes fall from the top at slightly different speeds and drift between
adjacent columns. A flake that lands next to a lower column slides off into
it and keeps falling, like sand, so the pile levels out instead of building
pillars. The ground starts with a low mound spanning the full width, and the air starts
full of flakes at random heights, as if it had been snowing a while. The top
`top_margin` rows stay dark (the panel's frame shades them at some angles, so
white shows blue there): flakes appear below them and the pile never reaches them.

The pile's size is tracked. When it covers shift_at of the panel, the whole
pile slowly sinks: one row at a time, shift_rows times, shift_interval
seconds apart, dropping the bottom row (64 pixels) each time. With
shift_at 0, the pile instead grows to max_pile rows, then melts back to the
starting mound.
"""
import math
import random

from pixelgrid.matrix import SIZE
from pixelgrid.activities.base import Activity
from pixelgrid.component import optional

AREA = SIZE * SIZE
FLAKE_COLOR = (255, 255, 255)


def snow_shade():
    """Settled snow: slightly varied bluish white so the pile has some texture."""
    v = random.randint(150, 215)
    return (v, v, min(255, v + 30))


def mound_heights(peak):
    """Low hill across the full width: `peak` tall in the middle, about half that at the edges."""
    heights = []
    for x in range(SIZE):
        t = (x - (SIZE - 1) / 2) / ((SIZE - 1) / 2)       # -1 .. 1
        h = peak * (0.5 + 0.5 * math.cos(t * math.pi / 2))  # peak at center, peak/2 at edges
        heights.append(max(1, min(peak, round(h + random.uniform(-0.4, 0.4)))))
    return heights


class SnowActivity(Activity):
    name = "snow"
    OPTIONS = {
        "rate": (float, "new flakes per second"),
        "speed": (float, "average fall speed in rows per second"),
        "drift": (float, "chance per row that a flake drifts sideways, 0-1"),
        "max_step": (int, "steepest allowed step between neighboring columns; 1 = smoothest"),
        "mound": (int, "starting mound height at its peak"),
        "shift_at": (float, "share of the panel the pile may cover before it sinks; 0 = melt mode"),
        "shift_rows": (int, "rows to sink once shift_at is reached"),
        "shift_interval": (float, "seconds between each row of sinking"),
        "max_pile": (int, "melt mode only: rows from the bottom the pile's highest point may reach before "
                          "it melts back down (to the mound, on top of any floor)"),
        "melt_interval": (float, "melt mode: seconds between melting steps; each sinks the whole surface a "
                                 "row, keeping its shape (snow landing on it meanwhile melts too)"),
        "floor": (int, "rows from the bottom the snow's surface never sinks below; the mound starts on top "
                       "of it and melts settle back to that; 0 = none"),
        "top_margin": (int, "rows at the top kept dark: flakes appear below them and the pile never "
                            "grows into them (the frame shades the top row at some angles); 0 = use them"),
        "floor_above_widget": (optional(int), "keep the snow's surface at least this many rows above the top "
                                              "of the widgets drawn over it (negative = below), so e.g. a "
                                              "corner clock sits in a snowbank; the mound starts on top of "
                                              "it and melts settle back to that; null = off"),
    }

    def validate(self):
        o = self.opts
        if not 1 <= o["mound"] < o["max_pile"] <= SIZE:
            raise ValueError(f"snow: need 1 <= mound < max_pile <= {SIZE}")
        if not 0 <= o["floor"] or o["floor"] + o["mound"] >= o["max_pile"]:
            raise ValueError("snow: floor must be 0 or more, and floor + mound below max_pile")
        if not 0 <= o["top_margin"] < SIZE // 2 or o["max_pile"] > SIZE - o["top_margin"]:
            raise ValueError(f"snow: top_margin must be 0-{SIZE // 2 - 1}, and max_pile at most {SIZE} - top_margin")
        if o["max_step"] < 1:
            raise ValueError("snow: max_step must be 1 or more")
        if o["shift_rows"] < 1:
            raise ValueError("snow: shift_rows must be 1 or more")
        if o["shift_interval"] < 0:
            raise ValueError("snow: shift_interval must be 0 or more")
        if not 0 <= o["shift_at"] <= 0.9:
            raise ValueError("snow: shift_at must be between 0 and 0.9")
        if o["melt_interval"] <= 0:
            raise ValueError("snow: melt_interval must be > 0")
        if o["shift_at"] and o["shift_at"] * AREA <= SIZE * (o["mound"] + 1):
            raise ValueError("snow: shift_at is too small for the starting mound; raise it or lower mound")

    def enter(self):
        # Settled snow is always a solid stack from the bottom of each column, so the
        # column heights describe the pile; colors[y][x] just stores each cell's shade.
        self.colors = [[None] * SIZE for _ in range(SIZE)]
        self.heights = [0] * SIZE
        self.flakes = []          # each: [x, y_float, speed]
        self.melting = False
        self.melt_timer = 0.0
        self.shifts_left = 0      # shifts remaining in the current sinking sequence
        self.shift_timer = 0.0    # seconds until the next shift in the sequence
        self.base = mound_heights(self.opts["mound"])
        self.floor = None         # set on the first update, once the widgets know where they are
        for x, h in enumerate(self.base):
            for _ in range(h):
                self.add_cell(x)
        print(f"Snow: pile starts at {self.total} px ({100 * self.total / AREA:.1f}%).", flush=True)

    def exit(self):
        print(f"Snow: pile ended at {self.total} px ({100 * self.total / AREA:.1f}%).", flush=True)

    # ---- pile helpers ----

    @property
    def total(self):
        return sum(self.heights)

    def surface(self, x):
        """Row index of the top settled cell in column x (SIZE if the column is empty)."""
        return SIZE - self.heights[x]

    def free(self, x, y):
        return 0 <= x < SIZE and y < self.surface(x)

    def add_cell(self, x):
        y = self.surface(x) - 1
        if y >= self.opts["top_margin"]:
            self.colors[y][x] = snow_shade()
            self.heights[x] += 1

    def downhill(self, x):
        """A neighbor column the flake should slide into, or None if x is stable here.

        Landing on column x would make it one taller; if that leaves a step steeper
        than max_step down to a neighbor, the flake rolls into that neighbor instead.
        """
        h = self.heights[x] + 1
        options = [nx for nx in (x - 1, x + 1)
                   if 0 <= nx < SIZE and h - self.heights[nx] > self.opts["max_step"]]
        if not options:
            return None
        lowest = min(self.heights[nx] for nx in options)
        return random.choice([nx for nx in options if self.heights[nx] == lowest])

    def settle(self, x):
        """Add a flake to column x, first rolling it downhill until it is stable."""
        while (nx := self.downhill(x)) is not None:
            x = nx
        if self.melting and self.heights[x] >= self.melt_caps[x]:
            return   # landed on a column already at its melt cap: it melts on contact
        self.add_cell(x)

    def shift_down(self):
        """Drop the whole pile one row, removing the bottom row."""
        removed = sum(1 for h in self.heights if h > 0)
        self.colors = [[None] * SIZE] + self.colors[:-1]
        self.heights = [max(0, h - 1) for h in self.heights]
        return removed

    def apply_floor(self):
        """Raise the pile's lowest allowed level to `floor` rows, or to floor_above_widget rows
        above the top of the widgets' ink if that's higher, across the whole width, and fill
        the pile up to it now."""
        o = self.opts
        self.floor = o["floor"]
        box = self.widget_bounds() if o["floor_above_widget"] is not None else None
        if box is not None:
            surface = max(0, min(SIZE - 1, box[1] - o["floor_above_widget"]))   # lowest row the surface may sink to
            self.floor = max(self.floor, SIZE - surface)
        if not self.floor:
            return
        # The starting mound sits on top of the floor (not inside it, where a floor taller than
        # the mound would leave a flat sheet), and melts settle back to that same hill.
        self.base = [self.floor + h for h in self.base]
        for x in range(SIZE):
            while self.heights[x] < self.base[x]:
                self.add_cell(x)
        if o["shift_at"] == 0 and max(self.base) >= o["max_pile"]:
            print(f"Snow: floor + mound already reach max_pile ({o['max_pile']} rows); it will keep melting; "
                  "lower floor or mound", flush=True)
        print(f"Snow: floor at {self.floor} rows (surface stays at or above row {SIZE - self.floor}); "
              f"pile now {self.total} px ({100 * self.total / AREA:.1f}%).", flush=True)

    def melt_step(self):
        """Sink the whole surface a row: every column's cap drops one (never below its base,
        the mound on top of any floor) and anything above it melts. Each column has its own cap,
        starting from its height when the melt began, so the surface keeps its bumps as it
        sinks (one level line would shave it into a flat plateau). Returns True once the pile
        is back down to its base."""
        self.melt_caps = [max(b, c - 1) for b, c in zip(self.base, self.melt_caps)]
        for x in range(SIZE):
            while self.heights[x] > self.melt_caps[x]:
                self.colors[self.surface(x)][x] = None
                self.heights[x] -= 1
        return self.melt_caps == self.base

    # ---- per-frame ----

    def fill_air(self):
        """Flakes already on their way down when the play starts: every flake that would have
        spawned over the time the slowest one takes to fall, moved as far as it would have got
        by now (drift aside), so the first frame looks like snow that's been falling a while."""
        o = self.opts
        slowest = o["speed"] * 0.6
        window = SIZE / slowest
        for _ in range(round(o["rate"] * window)):
            x = random.randrange(SIZE)
            v = random.uniform(o["speed"] * 0.6, o["speed"] * 1.4)
            y = -1.0 + v * random.uniform(0, window)
            if math.floor(y) < self.surface(x) and y >= o["top_margin"]:
                self.flakes.append([x, y, v])

    def spawn(self, dt):
        expected = self.opts["rate"] * dt
        count = int(expected) + (1 if random.random() < expected % 1 else 0)
        speed = self.opts["speed"]
        for _ in range(count):
            self.flakes.append([random.randrange(SIZE), -1.0, random.uniform(speed * 0.6, speed * 1.4)])

    def step_flakes(self, dt):
        still_falling = []
        for flake in self.flakes:
            x, y, speed = flake
            cy = math.floor(y)
            new_y = y + speed * dt
            landed = False
            # Advance one row at a time so a fast flake can't skip over the pile.
            while math.floor(new_y) > cy:
                # Drift: occasionally slide to an adjacent column if there is room.
                if random.random() < self.opts["drift"]:
                    dx = random.choice((-1, 1))
                    if self.free(x + dx, cy) and self.free(x + dx, cy + 1):
                        x += dx
                if not self.free(x, cy + 1):
                    nx = self.downhill(x)
                    if nx is None:
                        self.settle(x)
                        landed = True
                        break
                    # Too steep here: tumble into the lower neighbor column and keep falling.
                    x = nx
                cy += 1
            if not landed:
                flake[0], flake[1] = x, new_y
                still_falling.append(flake)
        # A flake can end up inside the pile when another one lands or rolls into its cell.
        # Settle those; settling can bury another flake, so repeat until none are left.
        self.flakes = still_falling
        while True:
            buried = [f for f in self.flakes if math.floor(f[1]) >= self.surface(f[0])]
            if not buried:
                break
            self.flakes = [f for f in self.flakes if math.floor(f[1]) < self.surface(f[0])]
            for f in buried:
                self.settle(f[0])

    def update_shifting(self, dt):
        """Start a slow sinking sequence at the threshold, then shift one row per interval."""
        o = self.opts
        if self.shifts_left == 0:
            total = self.total
            if total < o["shift_at"] * AREA:
                return
            self.shifts_left = o["shift_rows"]
            self.shift_timer = 0.0  # first shift happens right away
            print(f"Snow: pile reached {total} px ({100 * total / AREA:.1f}% of the panel); "
                  f"sinking {o['shift_rows']} rows, one every {o['shift_interval']:g}s.", flush=True)
        self.shift_timer -= dt
        if self.shift_timer > 0:
            return
        removed = self.shift_down()
        self.shifts_left -= 1
        self.shift_timer = o["shift_interval"]
        n = o["shift_rows"] - self.shifts_left
        print(f"  shift {n}/{o['shift_rows']}: removed {removed} px -> {self.total} px "
              f"({100 * self.total / AREA:.1f}%)", flush=True)

    def update(self, dt):
        o = self.opts
        if self.floor is None:
            self.apply_floor()
            self.fill_air()
        if self.melting:
            # It keeps snowing while the pile melts down a row every melt_interval; the melt
            # ends once the pile is back down to its base.
            self.spawn(dt)
            self.step_flakes(dt)
            self.melt_timer -= dt
            if self.melt_timer <= 0:
                self.melt_timer = o["melt_interval"]
                if self.melt_step():
                    self.melting = False
                    print(f"Snow: melted back to {self.total} px ({100 * self.total / AREA:.1f}%).", flush=True)
            return
        self.spawn(dt)
        self.step_flakes(dt)
        if self.opts["shift_at"] > 0:
            self.update_shifting(dt)
        elif max(self.heights) >= self.opts["max_pile"]:
            print(f"Snow: pile reached {max(self.heights)} rows (max_pile); melting a row every "
                  f"{o['melt_interval']:g}s.", flush=True)
            self.melting = True
            self.melt_caps = list(self.heights)    # no column grows past these; they drop a row each step
            self.melt_timer = o["melt_interval"]

    def draw(self, canvas):
        # While melting, the snow that goes at the next step (each column's cells above its next
        # cap, normally just its top pixel) fades from full brightness to black over the
        # melt_interval before it, so the surface melts away smoothly instead of in jumps.
        fade = None
        if self.melting and self.opts["melt_interval"] > 0:
            fade = max(0.0, min(1.0, self.melt_timer / self.opts["melt_interval"]))
        for x in range(SIZE):
            keep = max(self.base[x], self.melt_caps[x] - 1) if fade is not None else SIZE
            for y in range(self.surface(x), SIZE):
                r, g, b = self.colors[y][x]
                if SIZE - y > keep:   # this cell melts at the next step
                    r, g, b = round(r * fade), round(g * fade), round(b * fade)
                canvas.SetPixel(x, y, r, g, b)
        for x, y, _ in self.flakes:
            iy = math.floor(y)
            if iy >= self.opts["top_margin"]:
                canvas.SetPixel(x, iy, *FLAKE_COLOR)
