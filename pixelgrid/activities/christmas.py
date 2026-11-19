r"""Christmas activity: holiday screens: "snowflakes", then "christmas-lights".

snowflakes: large pseudorandom snowflakes falling from the top to the bottom.

    +----------------------------------+
    |    *          *          *       |   <- a row of 3 (min_per_row..max_per_row, random),
    |  *      *          *        *    |      evenly spread and mirrored around the middle;
    |    *          *          *       |      each flake nudged up to `jitter` px
    +----------------------------------+

Each flake is a `size` x `size` pattern with 8-fold symmetry (mirrored across both
axes and both diagonals), so every random pattern still reads as a snowflake. It's
built in one octant from a long main arm (plain, forked or capped tip) with fern
branches or crossbars, a shorter plain diagonal arm, and a hub (dot, ring, solid or
gap), then mirrored. Candidates that come out too bare, clumped (a solid 2x2 block or
a crowded 3x3 area), or not star-shaped (filled between the arms near the rim, which
reads as a square or circle) are thrown away and regenerated.

christmas-lights: `light_rows` rows of bulbs hanging from a green wire.

    +----------------------------------+
    |  \_o_/\_o_/\_o_/\_o_/\_o_/        |   <- each row hangs in a long curve (row_sag) and
    |                                  |      droops again between bulbs (sag), each droop a
    |  \_o_/\_o_/\_o_/\_o_/\_o_/        |      random depth; bulbs are 5 x 8, the wire 3 thick
    +----------------------------------+

Rows are evenly spaced and vertically centered; each row has min_lights..max_lights
bulbs (random per row), spread evenly and mirrored around the middle. Each bulb changes color on its own random timer
(about every `change_every` seconds), with a quick fade, never matching its neighbors.

More screens (ornaments, a tree, ...) go in SCREENS; they share the play time
evenly unless "<screen>_seconds" is set (see activities/base.py).
"""
import math
import random

from pixelgrid.activities.base import Activity
from pixelgrid.activities.clock import parse_color
from pixelgrid.component import optional
from pixelgrid.matrix import SIZE


MAX_FILL = 0.38   # reject flakes covering more of their square than this
MIN_FILL = 0.18   # ... or less than this (a bare star isn't interesting)
BRANCH_SLOPE = 0.45   # branches stay within ~24 degrees of their spoke (y/x <= this)
WEDGE = (0.42, 0.78)  # y/x range between the spokes that stays empty in the outer part
WEDGE_REACH = 0.55    # ... beyond this share of the radius


def is_open(pixels):
    """True if the flake has open space between its features: no solid 2x2 block and no
    3x3 area with 6+ pixels lit, outside the hub. Snowflakes read by their negative space;
    solid or checkerboard clumps are what make a pattern look like a blob."""
    on = set(pixels)
    for x, y in on:
        if max(abs(x), abs(y)) <= 1:
            continue  # the hub may be solid
        if (x + 1, y) in on and (x, y + 1) in on and (x + 1, y + 1) in on:
            return False
        if sum((x + dx, y + dy) in on for dx in (-1, 0, 1) for dy in (-1, 0, 1)) >= 6:
            return False
    return True


def is_star(pixels, r):
    """True if the outline is a star, not a square or a circle: the wedges between spokes
    stay empty in the outer half, so the spoke tips stick out on their own. (Rings and
    squares come from decoration spanning those wedges at an even distance.)"""
    return not any(0 < y <= x and WEDGE[0] < y / x < WEDGE[1] and math.hypot(x, y) > r * WEDGE_REACH
                   for x, y in pixels)


def make_flake(rng, size):
    """Pixel offsets (dx, dy) from the center of a random 8-fold symmetric snowflake.
    size: odd width in pixels (9-21). Retries until the flake is open, star-shaped and
    neither a blob nor bare."""
    r = size // 2
    for _ in range(200):
        pixels = _flake(rng, r)
        if (MIN_FILL * size * size <= len(pixels) <= MAX_FILL * size * size
                and is_open(pixels) and is_star(pixels, r)):
            return pixels
    return pixels


def _flake(rng, r):
    """One candidate: built in the octant 0 <= y <= x <= r, then mirrored 8 ways."""
    cells = set()
    # Hub: dot, open ring, solid 3x3 center, or a lone dot with the spokes starting a pixel out.
    hub = rng.choice(("dot", "ring", "solid", "gap"))
    # Main spoke (becomes the + arms), reaching the edge (or nearly) so its tip sticks out.
    arm = r if rng.random() < 0.7 else r - 1
    cells |= {(x, 0) for x in range(arm + 1)}
    # Spoke tip: plain, a V (fork) or, rarely, a T (cap; caps line up into squares).
    tip = rng.choices(("plain", "fork", "cap"), weights=(4, 4, 1))[0]
    if tip == "fork":
        cells.add((arm - 1, 1))
    elif tip == "cap":
        cells.add((arm, 1))
    # Diagonal spoke (becomes the x arms): plain and shorter, 45-80% of the main spoke's
    # reach, so the flake is a star, not a square: 4 long decorated spokes alternating with
    # 4 short plain ones. (Decoration near the diagonal either lands between the spokes or
    # clumps into solid blocks with its mirror image, so the diagonal only varies in length
    # and sometimes ends in a separate dot.)
    dmin = max(2, math.ceil(0.45 * r / math.sqrt(2)))
    diag = rng.randint(dmin, max(dmin, int(0.8 * r / math.sqrt(2))))
    cells |= {(d, d) for d in range(diag + 1)}
    if diag >= 3 and rng.random() < 0.35:
        cells.discard((diag - 1, diag - 1))
    # Branches off the main spoke: angled outward (fern) or straight across (bar), kept
    # close to the spoke and short of its tip, with gaps between them.
    # Each branch starts 2+ pixels past where the previous one ended (a fern ends further
    # out than it starts), and not beside a solid hub, so branches never clump together.
    x0 = rng.randint(3, 4) if hub in ("solid", "ring") else rng.randint(2, 3)
    while x0 <= arm - 2:
        kind = rng.choices(("fern", "bar", None), weights=(3, 2, 2))[0]
        end = x0
        for k in range(1, rng.randint(1, 3) + 1):  # 1-3 pixels long
            cell = (x0 + k, k) if kind == "fern" else (x0, k) if kind == "bar" else None
            if cell and cell[1] <= BRANCH_SLOPE * cell[0] and math.hypot(*cell) <= arm - 1.5:
                cells.add(cell)
                end = max(end, cell[0])
        x0 = end + rng.randint(2, 3)
    if hub == "ring":
        cells.discard((0, 0))
        cells.add((1, 1))
    elif hub == "solid":
        cells |= {(1, 0), (1, 1)}
    elif hub == "gap":   # a lone center dot, the spokes starting a pixel out
        cells -= {(1, 0), (1, 1)}
    out = set()
    for x, y in cells:
        for a, b in ((x, y), (y, x)):
            out |= {(a, b), (-a, b), (a, -b), (-a, -b)}
    return sorted(out)


STAGGER = 2   # rows each flake in a crowded row moves up or down (alternating)


def row_centers(n, min_step=0):
    """x centers for n flakes spread evenly across the panel, mirrored around its middle
    (mx-auto): the left half is placed and the right half is its mirror image. min_step
    spreads them at least that far apart, letting the outer ones hang off the edges."""
    lane_w = max(SIZE / n, min_step)
    mid = (SIZE - 1) / 2
    left = [int(mid + (i - (n - 1) / 2) * lane_w) for i in range(n // 2)]
    return left + ([int(mid)] if n % 2 else []) + [SIZE - 1 - x for x in reversed(left)]


WIRE_W = 3           # wire thickness in pixels (drawn downward from its top edge)
# A hanging bulb, relative to where it hangs (the top of the wire): a 3-wide socket just
# under the wire, then a 5 x 8 glass bulb (3-wide neck, 5 x 5 body, 3-wide taper, 1-pixel
# tip) with a three-pixel highlight streak and a dim halo around the glass.
SOCKET = [(dx, WIRE_W) for dx in (-1, 0, 1)]
BULB = ([(dx, WIRE_W + 1) for dx in (-1, 0, 1)]
        + [(dx, WIRE_W + dy) for dy in range(2, 7) for dx in (-2, -1, 0, 1, 2)]
        + [(dx, WIRE_W + 7) for dx in (-1, 0, 1)] + [(0, WIRE_W + 8)])
BULB_SHINE = [(-1, WIRE_W + 2), (-1, WIRE_W + 3), (-1, WIRE_W + 4)]
BULB_DROP = WIRE_W + 8   # rows from the hang point to the bottom of the bulb
# Halo: pixels directly beside the glass (not diagonal, so it stays round instead of a box),
# never on the socket or the wire above it.
BULB_GLOW = sorted({(x + dx, y + dy) for x, y in BULB for dx, dy in ((-1, 0), (1, 0), (0, 1))}
                   - set(BULB) - {(dx, dy) for dx in (-2, -1, 0, 1, 2) for dy in range(WIRE_W + 1)})
NUDGE_CELL = 6       # width in pixels of each cell of the shared up/down nudge pattern
WIDGET_GAP = 3       # rows between a widget's text and the light rows framing it (outline + 1 blank)
MIN_ROW_SPACING = BULB_DROP + 4   # hang point to the next row's wire: glow, 1 blank row, +-1 nudges
FADE = 0.25          # seconds a bulb takes to fade to its new color


def row_centers_step(n, step):
    """x centers for n items `step` apart, mirrored around the panel's middle (mx-auto)."""
    mid = (SIZE - 1) / 2
    left = [int(mid + (i - (n - 1) / 2) * step) for i in range(n // 2)]
    return left + ([int(mid)] if n % 2 else []) + [SIZE - 1 - x for x in reversed(left)]


# ---- christmas-tree geometry (the tree is mirrored around the panel's middle, x = 31.5) ----
CENTER = (SIZE - 1) / 2
# Tiers as (top row, bottom row, half-width at the top, half-width at the bottom).
TIERS = [(9, 23, 1.5, 11.0), (17, 36, 4.5, 17.5), (28, 50, 7.5, 24.5)]
TIER_SPANS = [(t, b) for t, b, _, _ in TIERS]
TREE_GROUND = 59          # top row of the snow
TREE_TOP_MARGIN = 3       # blank rows always kept above the star
STAR_ROWS = [             # a 10-wide star, symmetric, its top at row 0
    "....##....",
    "....##....",
    "...####...",
    "##########",
    ".########.",
    "..######..",
    "..######..",
    ".###..###.",
    ".##....##.",
]
STAR_TOP = 1
STAR, STAR_GLINT = (255, 200, 40), (255, 250, 210)
STAR_SHINE = (31, STAR_TOP + 3)
NEEDLES = [(10, 80, 25), (20, 115, 38), (40, 150, 55)]   # dark, mid, light
NEEDLE_SHADOW = (6, 50, 16)
TRUNK, TRUNK_DARK = (110, 62, 28), (75, 40, 18)
ORNAMENT = [(0, -1), (-1, 0), (0, 0), (1, 0), (0, 1)]          # a 3x3 ball: plus shape ...
ORNAMENT_EDGE = [(1, -1), (-1, 1), (1, 1)]                     # ... with dim corners to round it
ORNAMENT_CAP = (190, 190, 200)
TREE_LIGHT_GLOW = [(-1, 0), (1, 0), (0, -1), (0, 1)]
TREE_LIGHT_FLARE = [(-1, -1), (1, -1), (-1, 1), (1, 1)]   # lit only at a sparkle's peak
SPARKLE_SECONDS = 0.4     # how long a sparkle takes to flash and settle


def tree_half_width(y):
    """Half-width of the tree's outline at row y (the widest tier covering it)."""
    best = 0.0
    for top, base, w0, w1 in TIERS:
        if top <= y <= base + 2:
            best = max(best, w0 + (w1 - w0) * min(1.0, (y - top) / (base - top)))
    return best


def tree_mask():
    """Pixels of the tree, built on the left half and mirrored (so it's exactly centered).
    tiers: [{(x, y): rows from the next tier up's bottom edge, or None}], bottom tier last;
    body: every needle pixel; trunk; star."""
    tiers = []
    for top, base, w0, w1 in TIERS:
        tier = {}
        for y in range(top, base + 3):
            t = min(1.0, (y - top) / (base - top))
            half = w0 + (w1 - w0) * t + (1 if (y - top) % 4 == 3 else 0)   # branch tips poke out
            for x in range(SIZE // 2):
                d = CENTER - x
                if d > half:
                    continue
                # Scalloped bottom edge: branch tips droop up to 2 rows below the base.
                bottom = base + round(1 + math.cos(2 * math.pi * d / 5.0))
                if y > bottom:
                    continue
                tier[(x, y)] = None
        tiers.append(tier)
    # Shadow: rows just below the tier above's bottom edge (its overhang shades this tier).
    for upper, lower in zip(tiers, tiers[1:]):
        bottoms = {}
        for x, y in upper:
            bottoms[x] = max(bottoms.get(x, -1), y)
        for (x, y) in lower:
            if x in bottoms and y > bottoms[x]:
                lower[(x, y)] = y - bottoms[x] - 1
    mirror = lambda pts: pts | {(SIZE - 1 - x, y) for x, y in pts}
    tiers = [{**t, **{(SIZE - 1 - x, y): v for (x, y), v in t.items()}} for t in tiers]
    body = set().union(*[set(t) for t in tiers])
    trunk = mirror({(x, y) for x in range(SIZE // 2) if CENTER - x <= 3.5
                    for y in range(TIERS[-1][1] + 1, TREE_GROUND + 2)})   # into the snow, so a moved tree stays grounded
    star = set()
    for r, row in enumerate(STAR_ROWS):
        for c, ch in enumerate(row):
            if ch == "#":
                star.add((SIZE // 2 - len(row) // 2 + c, STAR_TOP + r))
    # Each tier's lowest row at the middle column: where the next tier down becomes visible.
    bottoms = [max(y for (x, y) in t if x == SIZE // 2) for t in tiers]
    return {"tiers": tiers, "body": sorted(body), "trunk": sorted(trunk), "star": sorted(star),
            "bottoms": bottoms}


class Flake:
    __slots__ = ("x", "y", "pixels", "color", "phase", "sway")

    def __init__(self, x, y, pixels, color, phase, sway):
        self.x, self.y, self.pixels, self.color, self.phase, self.sway = x, y, pixels, color, phase, sway


class ChristmasActivity(Activity):
    name = "christmas"
    SCREENS = ("snowflakes", "christmas-lights", "christmas-tree")
    POOL = 8   # ready-made flake patterns kept in stock (making one takes up to ~15ms on a Pi 4)
    OPTIONS = {
        "snowflakes_seconds": (optional(float), "seconds on the snowflakes screen each cycle; null = share "
                                                "the play time evenly with other unset screens; 0 = never"),
        "size": (int, "snowflake width in pixels (odd, 9-21)"),
        "min_per_row": (int, "fewest flakes in a row"),
        "max_per_row": (int, "most flakes in a row (each row picks at random); a row too wide for the "
                             "panel (4 x 17px) spreads out and its outer flakes are clipped by the edges"),
        "spacing": (int, "average rows from one row of flakes to the next"),
        "speed": (float, "fall speed in rows per second"),
        "jitter": (int, "max pixels each flake is nudged sideways from its even spot (as far as the row "
                        "has room) and the gap between rows varies by"),
        "y_jitter": (int, "max rows each flake is nudged up/down from its row, so rows don't line up; "
                          "a flake that would come too close to one below is moved up instead"),
        "sway": (float, "side-to-side drift in pixels while falling; 0 = straight down"),
        "colors": (str, "comma-separated #rrggbb colors picked at random per flake"),
        "christmas_lights_seconds": (optional(float), "seconds on the christmas-lights screen each cycle; "
                                                      "null = share the play time evenly with other unset "
                                                      "screens; 0 = never"),
        "light_rows": (int, "rows of lights, evenly spaced down the panel (1-4)"),
        "min_lights": (int, "fewest bulbs in a row (each row picks at random, spread evenly across)"),
        "max_lights": (int, "most bulbs in a row"),
        "sag": (float, "deepest the wire droops between two bulbs, in pixels (each droop is random up to this)"),
        "row_sag": (float, "how far the rows droop in the middle, hung from just past the panel edges "
                           "(75-100% of this, the same for every row so they stay parallel)"),
        "light_row_spacing": (optional(float), "pixels from one row of lights to the next; null = 85% of the "
                                               "spacing that would fill the panel"),
        "wire_color": (str, "wire color as #rrggbb"),
        "light_colors": (str, "comma-separated #rrggbb bulb colors"),
        "change_every": (float, "average seconds before a bulb changes color (each bulb on its own random timer)"),
        "sparkle_every": (float, "average seconds between sparkles per light: a quick flash toward white with a "
                                 "flared glow, each light on its own random timer (christmas-lights and "
                                 "christmas-tree); 0 = no sparkle"),
        "glow": (float, "brightness of the halo around each bulb, 0-1 (0 = none)"),
        "christmas_tree_seconds": (optional(float), "seconds on the christmas-tree screen each cycle; null = "
                                                    "share the play time evenly with other unset screens; "
                                                    "0 = never"),
        "ornaments_per_tier": (str, "ornament count range for each tier, top to bottom, e.g. \"3-4,5-6,6-8\" "
                                    "(each play picks within each range); one evenly spaced strand per tier"),
        "ornament_colors": (str, "comma-separated #rrggbb ornament colors"),
        "garlands": (int, "strands of lights wrapped around the tree (1-4); they use light_colors, "
                          "change_every and glow like the christmas-lights screen"),
        "tree_light_spacing": (int, "pixels between lights along a strand"),
    }

    def validate(self):
        o = self.opts
        self.validate_screens()
        if o["size"] % 2 == 0 or not 9 <= o["size"] <= 21:
            raise ValueError("christmas: size must be odd, 9-21")
        most = SIZE // o["size"] + 1
        if not 1 <= o["min_per_row"] <= o["max_per_row"] <= most:
            raise ValueError(f"christmas: need 1 <= min_per_row <= max_per_row <= {most} for "
                             f"{o['size']}px flakes (more would overlap)")
        if o["spacing"] < o["size"] + 1 + o["jitter"]:
            raise ValueError("christmas: spacing must be at least size + 1 + jitter")
        if o["speed"] <= 0 or o["jitter"] < 0 or o["y_jitter"] < 0 or o["sway"] < 0:
            raise ValueError("christmas: speed must be > 0; jitter, y_jitter and sway 0 or more")
        self.palette = [parse_color(c) for c in o["colors"].split(",") if c.strip()]
        if not self.palette:
            raise ValueError("christmas: colors needs at least one #rrggbb")
        if not 1 <= o["light_rows"] <= 4:
            raise ValueError("christmas: light_rows must be 1-4")
        if not 2 <= o["min_lights"] <= o["max_lights"] <= 8:
            raise ValueError("christmas: need 2 <= min_lights <= max_lights <= 8")
        if o["sparkle_every"] < 0:
            raise ValueError("christmas: sparkle_every must be 0 (off) or more")
        if not 0 <= o["sag"] <= BULB_DROP or o["change_every"] <= 0 or not 0 <= o["glow"] <= 1:
            raise ValueError(f"christmas: sag must be 0-{BULB_DROP} (deeper droops would hang below the "
                             "bulbs), change_every > 0, glow 0-1")
        if not 0 <= o["row_sag"] <= 12:
            raise ValueError("christmas: row_sag must be 0-12")
        if o["light_row_spacing"] is not None and o["light_row_spacing"] < MIN_ROW_SPACING:
            raise ValueError(f"christmas: light_row_spacing must be at least {MIN_ROW_SPACING} (closer, a "
                             "bulb's glow would reach the next row's wire)")
        self.wire_color = parse_color(o["wire_color"])
        self.light_palette = [parse_color(c) for c in o["light_colors"].split(",") if c.strip()]
        if len(self.light_palette) < 3:
            raise ValueError("christmas: light_colors needs at least 3 colors (neighbors never match)")
        self.ornament_palette = [parse_color(c) for c in o["ornament_colors"].split(",") if c.strip()]
        if not self.ornament_palette:
            raise ValueError("christmas: ornament_colors needs at least one #rrggbb")
        if not 1 <= o["garlands"] <= 4 or not 3 <= o["tree_light_spacing"] <= 12:
            raise ValueError("christmas: garlands must be 1-4, tree_light_spacing 3-12")
        try:
            self.ornament_ranges = [tuple(sorted(int(v) for v in part.split("-"))) if "-" in part
                                    else (int(part), int(part)) for part in o["ornaments_per_tier"].split(",")]
        except ValueError:
            self.ornament_ranges = None
        if (not self.ornament_ranges or len(self.ornament_ranges) != len(TIERS)
                or any(lo < 0 or hi > 15 for lo, hi in self.ornament_ranges)):
            raise ValueError(f"christmas: ornaments_per_tier needs {len(TIERS)} ranges like \"3-4,5-6,6-8\" "
                             "(top tier first, each 0-15)")

    def enter(self):
        o = self.opts
        self.rng = random.Random()
        self.t = 0.0
        self.pool = []
        self.flakes = []
        # Fill the panel as if the snow had been falling a while: rows from the bottom up.
        self.row_y = SIZE + o["size"] / 2 - self.rng.uniform(0, o["spacing"])   # newest row's base y
        self.spawn_row(self.row_y)
        while self.row_y - o["spacing"] > -o["size"]:
            self.row_y -= self.gap()
            self.spawn_row(self.row_y)
        self.next_gap = self.gap()
        self.rows = None   # laid out on the first update, once the widgets know where they are
        self.build_tree()

    def gap(self):
        return self.opts["spacing"] + self.rng.randint(-self.opts["jitter"], self.opts["jitter"])

    def spawn_row(self, y):
        """A row of min_per_row..max_per_row flakes, evenly spread, each nudged sideways by up
        to `jitter` and up/down by up to `y_jitter`. A crowded row (wider than the panel, e.g.
        4 x 17px) spreads size + 2 apart with the outer flakes clipped by the edges, isn't
        nudged sideways or swayed (that could close the gap), and zigzags up/down by STAGGER.
        Then each flake is moved up if needed to keep a blank row above any flake below it
        that it could touch, so flakes never touch however far they're nudged."""
        o, j, jy = self.opts, self.opts["jitter"], self.opts["y_jitter"]
        n = self.rng.randint(o["min_per_row"], o["max_per_row"])
        crowded = n * o["size"] > SIZE
        centers = row_centers(n, o["size"] + 2 if crowded else 0)
        # Sideways nudge, limited so neighbors (each nudged and swaying toward the other)
        # still keep a blank column between their spoke tips.
        step = centers[1] - centers[0] if n > 1 else SIZE
        jx = max(0, min(j, (step - o["size"] - 2 - 2 * math.ceil(o["sway"])) // 2))
        flip = self.rng.choice((-1, 1))
        for i, cx in enumerate(centers):
            if crowded:
                x, fy = cx, y + flip * (STAGGER if i % 2 else -STAGGER) + self.rng.randint(-jy, jy)
            else:
                x, fy = cx + self.rng.randint(-jx, jx), y + self.rng.randint(-jy, jy)
            fy = self.clear_of_below(x, fy, 0 if crowded else o["sway"])
            pixels = self.pool.pop() if self.pool else make_flake(self.rng, o["size"])
            self.flakes.append(Flake(x, fy, pixels, self.rng.choice(self.palette),
                                     self.rng.uniform(0, 2 * math.pi), 0 if crowded else o["sway"]))

    def clear_of_below(self, x, y, sway):
        """y, moved up as needed so a new flake at x keeps a blank row above every existing
        flake it could touch (one whose column range, sway included, reaches it)."""
        o = self.opts
        for f in self.flakes:
            # Closer than this horizontally (both flakes' sway included), the two could touch.
            if abs(f.x - x) < o["size"] + 1 + math.ceil(f.sway) + math.ceil(sway):
                y = min(y, f.y - o["size"] - 1)
        return y

    def update(self, dt):
        if self.rows is None:
            self.build_lights()
        self.t += dt
        screen = self.screen_at(self.t)
        if screen == "snowflakes":
            self.update_snowflakes(dt)
        elif screen == "christmas-lights":
            self.change_colors(self.rows)
        elif screen == "christmas-tree":
            self.change_colors(self.tree_strands)

    def update_snowflakes(self, dt):
        o = self.opts
        half = o["size"] // 2
        if len(self.pool) < self.POOL:   # one new pattern per frame, so spawning a row never stalls
            self.pool.append(make_flake(self.rng, o["size"]))
        for f in self.flakes:
            f.y += o["speed"] * dt
        self.row_y += o["speed"] * dt
        self.flakes = [f for f in self.flakes if f.y - half - o["sway"] < SIZE]
        # The next row starts just above the panel once the newest row has fallen a gap's worth.
        if self.row_y - self.next_gap >= -half - o["y_jitter"] - STAGGER - 1:
            self.row_y -= self.next_gap
            self.spawn_row(self.row_y)
            self.next_gap = self.gap()

    def draw(self, canvas):
        screen = self.screen_at(self.t)
        if screen == "snowflakes":
            self.draw_snowflakes(canvas)
        elif screen == "christmas-lights":
            self.draw_lights(canvas)
        elif screen == "christmas-tree":
            self.draw_tree(canvas)

    def draw_snowflakes(self, canvas):
        for f in self.flakes:
            cx = f.x + round(f.sway * math.sin(self.t * 0.8 + f.phase))
            cy = math.floor(f.y)   # not int(): it rounds toward zero, off by one above the top edge
            r, g, b = f.color
            for dx, dy in f.pixels:
                x, y = cx + dx, cy + dy
                if 0 <= x < SIZE and 0 <= y < SIZE:
                    canvas.SetPixel(x, y, r, g, b)

    # ---- christmas-lights: rows of bulbs on a drooping wire ----

    def build_lights(self):
        """Lay out the rows once per play: bulb positions, the wire's shape, starting colors.
        Only the colors change afterwards.

        The rows hang in the same long curve (row_sag) from points just past the panel edges,
        so they stay parallel and evenly spaced all the way across. Each row gets a random
        number of bulbs (min_lights..max_lights) spread evenly across; bulbs are nudged up/down
        a pixel by a random pattern shared by every row (so the spacing stays even), and the
        wire droops a random depth between each pair of bulbs (sag), so no two rows look alike. Rows are light_row_spacing apart (by default 85% of
        what would fill the panel), and the block is centered on its bulbs, the bright part
        the eye sees, rather than on the dim wire (mx-auto, vertically). With two rows and a
        widget drawn over the screen (a centered clock), the rows frame it instead: one above,
        one below (frame_widget)."""
        o, rng = self.opts, self.rng
        n = o["light_rows"]
        ends = (-6, SIZE + 5)   # where the rows are "hung", just off the panel
        droop = rng.uniform(0.75, 1.0) * o["row_sag"]
        tilt = rng.choice((-1, 0, 0, 1))

        def curve(x):
            t = (x - ends[0]) / (ends[1] - ends[0])
            return tilt * t + 4 * droop * t * (1 - t)

        # Small up/down nudges for a hand-hung look, as a random pattern across the panel's
        # width shared by every row: a bulb at the same x gets the same nudge in any row, so
        # the rows stay evenly spaced even though their bulbs don't line up.
        cells = {c: rng.choice((-1, 0, 0, 1)) for c in range(-4, SIZE // NUDGE_CELL + 5)}

        def nudge(x):
            return cells[x // NUDGE_CELL]

        glass = BULB + (BULB_GLOW if o["glow"] > 0 else [])
        rows = []
        for _ in range(n):
            # This row's bulbs: min_lights..max_lights spread evenly across the panel and
            # mirrored around the middle (mx-auto), plus one beyond each edge so the wire runs
            # off the panel instead of ending at a bulb.
            count = rng.randint(o["min_lights"], o["max_lights"])
            step = SIZE / count
            xs = row_centers_step(count, step)
            xs = [round(xs[0] - step)] + xs + [round(xs[-1] + step)]
            points = [(x, round(curve(x)) + nudge(x)) for x in xs]   # hang points
            sag = o["sag"] * min(1.0, step / 13)                    # closer bulbs, shallower swags
            sags = [rng.uniform(0.6, 1.0) * sag for _ in points[1:]]  # one droop per gap
            wire = self.wire_pixels(points, sags)
            bulbs = [{"x": x, "y": y, "color": None, "prev": None, "since": -99.0,
                      "next": self.t + rng.uniform(0, 2 * o["change_every"])} for x, y in points[1:-1]]
            for i, b in enumerate(bulbs):   # starting colors: never the same as the left neighbor
                left = bulbs[i - 1]["color"] if i else None
                b["color"] = rng.choice([c for c in self.light_palette if c != left])
            ink = [y for x, y in wire if 0 <= x < SIZE] + [b["y"] + dy for b in bulbs for _, dy in glass]
            rows.append({"wire": wire, "bulbs": bulbs, "top": min(ink), "bottom": max(ink),
                         "glass_top": min(b["y"] + dy for b in bulbs for _, dy in glass),
                         "glass_bottom": max(b["y"] + dy for b in bulbs for _, dy in glass)})
        # Rows sit at multiples of `band` on the shared curve (not by their random extremes,
        # which would add a pixel of unevenness).
        height = max(row["bottom"] - min(0, row["top"]) for row in rows)
        fill = (SIZE - 1 - height) / (n - 1) if n > 1 else 0
        band = o["light_row_spacing"] if o["light_row_spacing"] is not None else max(MIN_ROW_SPACING, 0.85 * fill)
        for i, row in enumerate(rows):
            self.shift_row(row, round(i * band))
        # Center on the bulbs; if that would push the wire off the panel, settle for the
        # nearest position that keeps everything on it.
        top, bottom = rows[0]["glass_top"], rows[-1]["glass_bottom"]
        shift = ((SIZE - 1 - bottom) - top) // 2
        ink_top = min(row["top"] for row in rows)
        ink_bottom = max(row["bottom"] for row in rows)
        shift = max(-ink_top, min(SIZE - 1 - ink_bottom, shift))
        for row in rows:
            self.shift_row(row, shift)
        box = self.widget_bounds()
        if box is not None and n == 2:
            self.frame_widget(rows, box, glass)
        for row in rows:
            row["wire"] = [(x, y) for x, y in row["wire"] if 0 <= x < SIZE and 0 <= y < SIZE]
        self.rows = rows

    def frame_widget(self, rows, box, glass):
        """Two rows around a widget (e.g. a centered clock): the first centered in the space
        above its box, the second in the space below, each kept WIDGET_GAP rows clear of the
        box (its text; the gap covers the outline plus a blank row). If a row doesn't fit its
        space, it stays clear of the widget and runs off the panel's outer edge instead."""
        spaces = ((0, box[1] - WIDGET_GAP), (box[3] + WIDGET_GAP, SIZE - 1))
        for row, (lo, hi), upper in zip(rows, spaces, (True, False)):
            ys = [y for _, y in row["wire"]] + [b["y"] + dy for b in row["bulbs"] for _, dy in glass]
            top, bottom = min(ys), max(ys)
            shift = (lo + hi) // 2 - (top + bottom) // 2
            if upper:
                shift = min(shift, hi - bottom)    # never into the widget
            else:
                shift = max(shift, lo - top)
            self.shift_row(row, shift)

    @staticmethod
    def shift_row(row, dy):
        row["wire"] = [(x, y + dy) for x, y in row["wire"]]
        for b in row["bulbs"]:
            b["y"] += dy
        for key in ("top", "bottom", "glass_top", "glass_bottom"):
            row[key] += dy

    @staticmethod
    def wire_pixels(points, sags):
        """Pixels of a WIRE_W-thick wire through `points` (its top edge) that droops between
        each pair (a parabola `sag` deep), with vertical steps filled in so it has no gaps."""
        pixels = set()
        for (x0, y0), (x1, y1), sag in zip(points, points[1:], sags):
            prev = None
            for x in range(x0, x1 + 1):
                t = (x - x0) / (x1 - x0)
                y = round(y0 + (y1 - y0) * t + 4 * sag * t * (1 - t))
                if prev is not None:
                    for yy in range(min(prev, y), max(prev, y) + 1):   # fill steep steps
                        pixels.add((x if abs(yy - y) < abs(yy - prev) else x - 1, yy))
                pixels.add((x, y))
                prev = y
        return sorted({(x, y + k) for x, y in pixels for k in range(WIRE_W)})   # WIRE_W thick

    def new_bulb(self, x, y, left, palette=None):
        """A bulb (also used for the tree's lights) with a random starting color that differs
        from its left neighbor's, and a random time for its first change."""
        palette = palette or self.light_palette
        return {"x": x, "y": y, "color": self.rng.choice([c for c in palette if c != left]), "palette": palette,
                "prev": None, "since": -99.0, "next": self.t + self.rng.uniform(0, 2 * self.opts["change_every"])}

    def change_colors(self, rows):
        """Each bulb changes color on its own random timer, to one its neighbors don't have.
        rows: [{"bulbs": [...]}] (christmas-lights rows, or the tree's strands)."""
        o, rng = self.opts, self.rng
        for row in rows:
            bulbs = row["bulbs"]
            for i, b in enumerate(bulbs):
                self.schedule_sparkle(b)
                if self.t < b["next"]:
                    continue
                taken = {b["color"]} | {bulbs[k]["color"] for k in (i - 1, i + 1) if 0 <= k < len(bulbs)}
                b["prev"], b["color"], b["since"] = b["color"], rng.choice(
                    [c for c in b.get("palette", self.light_palette) if c not in taken]), self.t
                b["next"] = self.t + rng.uniform(0.4, 1.6) * o["change_every"]

    def draw_lights(self, canvas):
        o = self.opts
        wr, wg, wb = self.wire_color
        socket = tuple(min(255, c + 40) for c in self.wire_color)
        for row in self.rows:
            colors = [self.bulb_color(b) for b in row["bulbs"]]
            sparks = [self.sparkle(b) for b in row["bulbs"]]
            # Halo first, so the wire and the bulbs draw over it (never the other way round).
            # A sparkle flares the halo (up to 3.5x) and washes the glass toward white.
            if o["glow"] > 0:
                for b, color, sp in zip(row["bulbs"], colors, sparks):
                    dim = tuple(min(255, round(c * o["glow"] * (1 + 2.5 * sp))) for c in color)
                    self.stamp(canvas, b, BULB_GLOW, dim)
            for x, y in row["wire"]:
                canvas.SetPixel(x, y, wr, wg, wb)
            for b, color, sp in zip(row["bulbs"], colors, sparks):
                self.stamp(canvas, b, SOCKET, socket)
                self.stamp(canvas, b, BULB, self.whiten(color, 0.6 * sp))
                self.stamp(canvas, b, BULB_SHINE, self.whiten(color, 0.45 + 0.55 * sp))

    def schedule_sparkle(self, b):
        """Start the bulb's next sparkle when its random timer comes up."""
        every = self.opts["sparkle_every"]
        if every <= 0:
            return
        if "spark_next" not in b:
            b["spark_at"], b["spark_next"] = -99.0, self.t + self.rng.uniform(0, 2 * every)
        if self.t >= b["spark_next"]:
            b["spark_at"] = self.t
            b["spark_next"] = self.t + SPARKLE_SECONDS + self.rng.uniform(0.4, 1.6) * every

    def sparkle(self, b):
        """0..1: how far into a sparkle the bulb is (rises and settles over SPARKLE_SECONDS)."""
        dt = self.t - b.get("spark_at", -99.0)
        return math.sin(math.pi * dt / SPARKLE_SECONDS) if 0 <= dt < SPARKLE_SECONDS else 0.0

    @staticmethod
    def whiten(color, k):
        return tuple(round(c + (255 - c) * k) for c in color)

    def bulb_color(self, b):
        """The bulb's color now, mid-fade if it just changed."""
        k = min(1.0, (self.t - b["since"]) / FADE)
        if k >= 1 or b["prev"] is None:
            return b["color"]
        return tuple(round(p + (c - p) * k) for p, c in zip(b["prev"], b["color"]))

    @staticmethod
    def stamp(canvas, b, offsets, color):
        for dx, dy in offsets:
            x, y = b["x"] + dx, b["y"] + dy
            if 0 <= x < SIZE and 0 <= y < SIZE:
                canvas.SetPixel(x, y, *color)

    # ---- christmas-tree: a decorated tree with ornaments and color-changing lights ----

    def build_tree(self):
        """Lay out the tree once per play: needles (random speckle), ornaments and light strands
        (random places), all as fixed pixels except the lights' colors. The tree is mirrored
        around the panel's middle (mx-auto); the decorations are placed freely."""
        o, rng = self.opts, self.rng
        mask = tree_mask()
        # Snow on the ground (kept separate: it stays put when the tree is moved below).
        ground = {}
        for x in range(SIZE):
            top = TREE_GROUND + round(0.8 * math.sin(x / 5.0 + rng.uniform(0, 0.4)))
            for y in range(top, SIZE):
                v = rng.randint(185, 225)
                ground[(x, y)] = (v, v, min(255, v + 25))
        # The trunk, then the tiers bottom-up (each overlapping the one below), so the shadow
        # under each tier's overhang lands on the tier beneath it.
        static = {}
        for (x, y) in mask["trunk"]:
            static[(x, y)] = TRUNK_DARK if (x + y) % 4 == 0 or abs(x - CENTER) > 2.5 else TRUNK
        for tier in reversed(mask["tiers"]):
            for (x, y), edge_gap in tier.items():
                shade = rng.choices(NEEDLES, weights=(2, 5, 2))[0]
                static[(x, y)] = NEEDLE_SHADOW if edge_gap is not None and edge_gap <= 1 else shade
        for (x, y) in mask["star"]:
            static[(x, y)] = STAR
        static[STAR_SHINE] = STAR_GLINT
        inside = set(mask["body"])
        # Strands of lights and of ornaments wrap around the tree, curving lower in the middle
        # (the front of the tree): in each tier, its light strand(s) above (the bottom tier gets
        # two when garlands is 4), then its ornaments lowest, where the tier is widest. In each tier the
        # strands are evenly spaced down the part you can see (below the tier above). All strands
        # share one droop, so they're parallel.
        droop = rng.uniform(2.5, 3.5)
        light_tiers = [0, 1, 2, 2][:o["garlands"]]
        plans = []   # (tier, kind, middle row)
        for k, (top, base) in enumerate(TIER_SPANS):
            visible_top = top + 3 if k == 0 else mask["bottoms"][k - 1] + 1
            kinds = ["lights"] * light_tiers.count(k) + ["ornaments"]   # ornaments lowest, where it's widest
            band = (base - visible_top) / len(kinds)
            plans += [(k, kind, visible_top + (i + 0.5) * band) for i, kind in enumerate(kinds)]

        def curve_y(x, mid):
            """Row of a strand at column x whose middle (front) is at row `mid`."""
            half = tree_half_width(mid - droop)
            d = (x - CENTER) / half if half else 0
            return round(mid - droop * d * d)

        # Ornaments: shared out between the tiers by how wide each strand is, then evenly
        # spaced along it and mirrored around the middle (mx-auto).
        strands = [(k, mid) for k, kind, mid in plans if kind == "ornaments"]
        fits = lambda x, y: all((x + dx, y + dy) in inside for dx, dy in ORNAMENT + ORNAMENT_EDGE + [(0, -2)])
        def strand_ends(mid):
            """(left x, span): the outermost mirrored pair of spots where a whole ornament fits
            on the strand's curve (the tree's edge is jagged)."""
            xl = 0
            while xl < CENTER and not (fits(xl, curve_y(xl, mid)) and fits(SIZE - 1 - xl, curve_y(SIZE - 1 - xl, mid))):
                xl += 1
            return xl, SIZE - 1 - 2 * xl

        # Each tier gets a count from its range in ornaments_per_tier. Its strand starts at its
        # evenly spaced row and moves down (where the tier is wider) until that many fit at
        # least 4px apart (3px balls with a gap), never below the tier's bottom. The ornaments
        # are then spread evenly between the strand's ends and mirrored around the middle, so
        # none has to be pushed in on its own (which would bunch them up).
        self.ornaments = []
        for (k, mid), (lo, hi) in zip(strands, self.ornament_ranges):
            n = rng.randint(lo, hi)
            if n == 0:
                continue
            xl, span = strand_ends(mid)
            while span // 4 + 1 < n and mid + 0.5 <= TIERS[k][1]:
                mid += 0.5
                xl, span = strand_ends(mid)
            n = min(n, span // 4 + 1)
            xs = row_centers_step(n, span / (n - 1)) if n > 1 else [int(CENTER)]
            left = None
            for x in xs:
                y = curve_y(x, mid)
                if not fits(x, y):
                    continue
                color = rng.choice([c for c in self.ornament_palette if c != left] or self.ornament_palette)
                self.ornaments.append((x, y, color))
                left = color
        blocked = {(x + dx, y + dy) for x, y, _ in self.ornaments
                   for dx in (-2, -1, 0, 1, 2) for dy in (-3, -2, -1, 0, 1, 2)}
        # Lights: tree_light_spacing apart along each light strand, mirrored around the middle,
        # skipping any spot an ornament already covers. Green lights vanish against the
        # needles, so the tree skips them (if enough colors remain for neighbors to differ).
        palette = [c for c in self.light_palette if not (c[1] > 1.3 * max(c[0], c[2]))]
        palette = palette if len(palette) >= 3 else self.light_palette
        self.tree_strands = []
        for k, kind, mid in plans:
            if kind != "lights":
                continue
            half = tree_half_width(mid - droop)
            count = max(1, int((2 * half - 2) // o["tree_light_spacing"]) + 1)
            bulbs = []
            for x in row_centers_step(count, o["tree_light_spacing"]):
                y = curve_y(x, mid)
                if (x, y) in inside and (x, y) not in blocked:
                    bulbs.append(self.new_bulb(x, y, bulbs[-1]["color"] if bulbs else None, palette))
            self.tree_strands.append({"bulbs": bulbs})
        for x, y, color in self.ornaments:
            static[(x, y - 2)] = ORNAMENT_CAP
            for dx, dy in ORNAMENT:
                static[(x + dx, y + dy)] = color
            for dx, dy in ORNAMENT_EDGE:
                static[(x + dx, y + dy)] = tuple(round(c * 0.45) for c in color)
            static[(x - 1, y - 1)] = tuple(round(c + (255 - c) * 0.6) for c in color)   # highlight
        # Exactly TREE_TOP_MARGIN blank rows above the tree's highest pixel (the star's tip),
        # whatever the geometry: move the tree, its lights and ornaments; the trunk just
        # stands a little deeper in the snow (it reaches below the ground line).
        shift = TREE_TOP_MARGIN - min(y for _, y in static)
        static = {(x, y + shift): c for (x, y), c in static.items()}
        for strand in self.tree_strands:
            for b in strand["bulbs"]:
                b["y"] += shift
        self.ornaments = [(x, y + shift, c) for x, y, c in self.ornaments]
        merged = {**ground, **static}   # the tree (trunk) over the snow
        self.tree_static = [(x, y, c) for (x, y), c in merged.items() if 0 <= x < SIZE and 0 <= y < SIZE]

    def draw_tree(self, canvas):
        o = self.opts
        for x, y, (r, g, b) in self.tree_static:
            canvas.SetPixel(x, y, r, g, b)
        for strand in self.tree_strands:
            for b in strand["bulbs"]:
                color = self.bulb_color(b)
                sp = self.sparkle(b)
                if o["glow"] > 0:
                    dim = tuple(round(c * min(1.0, o["glow"] * 3.5 * (1 + 1.2 * sp))) for c in color)
                    self.stamp(canvas, b, TREE_LIGHT_GLOW, self.whiten(dim, 0.4 * sp))
                if sp > 0.35:   # at its peak a sparkle also flashes the diagonals: a tiny star
                    self.stamp(canvas, b, TREE_LIGHT_FLARE, tuple(round(c * 0.6 * sp) for c in self.whiten(color, 0.5)))
                self.stamp(canvas, b, [(0, 0)], self.whiten(color, 0.7 * sp))
