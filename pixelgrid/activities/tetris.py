r"""Tetris activity: a self-playing game on a 16 x 16 well of 4 x 4 px cells.

play-keep: completed rows aren't cleared as they fill. The AI ("packer" in
pixelgrid/tetris/agent.py) packs the board as tightly as it can; a row that fills up gets a
white glint sweeping across it and stays. When the next piece can't fit (it can't spawn, or
every placement would stick out over the top), the board flushes: the full rows go one at a
time from the bottom up (each flashes white, then everything above it slides down a row), and
the same piece tries again on what's left, so the game keeps going. Only when there's no full
row to clear does the board hold for `end_pause` seconds, wipe from the top down, and a new
game start.

    +----------------+
    |      []        |  <- the piece rotates and shifts in the spawn row (move_interval
    |      [][]      |     per step), then drops a row every drop_interval
    |      []        |
    |                |
    |   ..           |  <- ghost: where it will land (dim)
    | [][]..  [][][] |
    |[][][][][][][][]|  <- full row: glint, then kept
    +----------------+

Each cell is a 3 x 3 fill with a darker right/bottom edge (`edge`). The AI decides a piece
while the one before it is still falling, a few milliseconds per frame (THINK_BUDGET), so
a decision never stalls the frame loop. Game rules and AI live in pixelgrid/tetris/;
tools/tetris_sim.py plays headless games to tune them.
"""
import random
import time

from pixelgrid.activities.base import Activity
from pixelgrid.activities.clock import parse_color
from pixelgrid.component import optional
from pixelgrid.matrix import SIZE
from pixelgrid.tetris.agent import PERSONALITIES, Agent
from pixelgrid.tetris.game import PIECES, ROTATE_STEPS, Game, Move, Well

CELL = 4                        # pixels per cell
CELLS = SIZE // CELL            # 16 x 16 well
GLINT = 0.6                     # seconds for a completed row's glint to sweep across
WIPE_ROW = 0.05                 # seconds per row of the game-over wipe
FLUSH_FLASH = 0.3               # seconds a full row flashes white before it's removed (flush)
FLUSH_DROP = 0.2                # seconds the rows above take to slide down into its place
THINK_BUDGET = 0.008            # seconds of AI work per frame

# screen -> (AI personality, clear full rows?)
SCREEN_RULES = {
    "play-keep": ("packer", False),
}


def scale(color, k):
    return tuple(int(c * k) for c in color)


def toward_white(color, k):
    return tuple(int(c + (255 - c) * k) for c in color)


class TetrisActivity(Activity):
    name = "tetris"
    SCREENS = ("play-keep",)
    FPS = 30
    OPTIONS = {
        "play_keep_seconds": (optional(float), "seconds on the play-keep screen (full rows stay, the AI packs "
                                               "the board until it tops out) each cycle; null = share the play "
                                               "time evenly with other unset screens; 0 = never"),
        "move_interval": (float, "seconds per rotate or shift step in the spawn row"),
        "drop_interval": (float, "seconds per row while a piece falls"),
        "lock_delay": (float, "pause in seconds after a piece lands, before the next one appears"),
        "lookahead": (int, "how many of the best placements the AI rechecks against the next piece "
                           "(0 = only look at the current piece)"),
        "temperature": (float, "randomness in the AI's choice: 0 = always the best placement; around 0.1-0.5 "
                               "it sometimes takes a worse one"),
        "misdrop_rate": (float, "chance (0-1) that a piece lands one column off from the AI's choice"),
        "ghost": (float, "brightness of the landing preview while a piece moves, 0-1 (0 = none)"),
        "piece_colors": (str, "comma-separated #rrggbb colors for the I, J, L, O, S, T, Z pieces"),
        "edge": (float, "brightness of each cell's right/bottom edge relative to its fill, 0-1"),
        "end_pause": (float, "seconds the final board stays up before it wipes and a new game starts"),
        "seed": (optional(int), "random seed for repeatable games; null = different every play"),
    }

    def validate(self):
        o = self.opts
        self.validate_screens()
        if o["move_interval"] <= 0 or o["drop_interval"] <= 0:
            raise ValueError("tetris: move_interval and drop_interval must be > 0")
        if o["lock_delay"] < 0 or o["end_pause"] < 0 or o["lookahead"] < 0 or o["temperature"] < 0:
            raise ValueError("tetris: lock_delay, end_pause, lookahead and temperature must be 0 or more")
        for k in ("misdrop_rate", "ghost", "edge"):
            if not 0 <= o[k] <= 1:
                raise ValueError(f"tetris: {k} must be 0-1")
        colors = [parse_color(c) for c in o["piece_colors"].split(",") if c.strip()]
        if len(colors) != len(PIECES):
            raise ValueError(f"tetris: piece_colors needs {len(PIECES)} colors (I, J, L, O, S, T, Z)")
        self.palette = {p: (c, scale(c, o["edge"])) for p, c in zip(PIECES, colors)}

    def enter(self):
        self.well = Well(CELLS, CELLS)
        self.rng = random.Random(self.opts["seed"])
        self.t = 0.0
        self.screen = None

    # Game flow: wait (at spawn, until the AI has decided) -> move -> fall -> lock -> next
    # piece ... until a piece can't spawn or would lock out -> flush (clear full rows, bottom
    # up) -> the same piece again; with no full rows to clear: over -> wipe -> new game.

    def new_game(self, screen):
        o = self.opts
        personality, clear = SCREEN_RULES[screen]
        self.screen = screen
        self.game = Game(self.well, seed=self.rng.random(), clear_lines=clear)
        self.agent = Agent(self.well, PERSONALITIES[personality], o["lookahead"], o["temperature"],
                           o["misdrop_rate"], clear, random.Random(self.rng.random()))
        self.decisions = {}        # piece number -> Choice (None = can't be placed)
        self.thinking = None       # (piece number, search generator)
        self.pending = (0, self.game.board)   # next piece to think about, and the board it lands on
        self.glints = {}           # row -> time its glint started
        self.spawn(0)

    def spawn(self, n):
        self.n = n
        self.piece = self.game.piece(n)
        sx, sy = self.well.spawn[self.piece]
        self.pos = Move(0, sx, sy)
        self.target = None
        if self.well.fits(self.game.board, self.piece, 0, sx, sy):
            self.phase, self.timer = "wait", self.opts["move_interval"]   # a beat in the spawn spot
        else:
            self.topped_out()

    def topped_out(self):
        """The current piece has nowhere to go: flush the full rows, or end the game if none."""
        full = self.game.full_rows()
        if full:
            self.glints = {}
            self.flush_next(full)
        else:
            self.game_over()

    def flush_next(self, full):
        """Start removing the lowest of the full rows: flash it, then slide the rows above down."""
        self.phase, self.flush_row, self.flush_stage = "flush", max(full), "flash"
        self.flush_start = self.t
        self.timer = max(self.timer, 0) + FLUSH_FLASH

    def resume_after_flush(self):
        """Back to the piece that didn't fit, rethought on the cleared board."""
        self.decisions, self.thinking = {}, None
        self.pending = (self.n, self.game.board)
        self.spawn(self.n)

    def game_over(self):
        self.phase, self.timer = "over", self.opts["end_pause"]

    def think(self):
        """Advance the AI for up to THINK_BUDGET: the active piece, then the one after it."""
        deadline = time.perf_counter() + THINK_BUDGET
        while time.perf_counter() < deadline:
            if self.thinking is None:
                if self.pending is None or self.pending[0] > self.n + 1:
                    return
                n, board = self.pending
                nxt = self.game.piece(n + 1) if self.opts["lookahead"] else None
                self.thinking = (n, self.agent.search(board, self.game.piece(n), nxt))
                self.pending = None
            n, gen = self.thinking
            try:
                next(gen)
            except StopIteration as done:
                self.decisions[n] = done.value
                self.thinking = None
                if done.value is not None:
                    self.pending = (n + 1, done.value.board)

    def update(self, dt):
        self.t += dt
        screen = self.screen_at(self.t)
        if screen != self.screen:
            self.new_game(screen)
        self.think()
        self.timer -= dt
        while self.timer <= 0:
            if not self.step():
                break

    def step(self):
        """One timed step of the game flow. False = waiting on something else (the AI)."""
        o = self.opts
        if self.phase == "wait":
            if self.n not in self.decisions:
                return False
            choice = self.decisions.pop(self.n)
            if choice is None or self.well.simulate(self.game.board, self.piece, choice.move)[2]:
                self.topped_out()   # no placement, or only ones sticking out over the top
                return True
            self.target = choice.move
            # Rotation steps, then shifts one column at a time.
            r = 0
            self.steps = []
            for s in ROTATE_STEPS[self.target.rot]:
                r = (r + s) % 4
                self.steps.append(("rot", r))
            dx = 1 if self.target.x > self.pos.x else -1
            self.steps += [("x", x) for x in range(self.pos.x + dx, self.target.x + dx, dx)]
            self.phase = "move"
            self.timer += o["move_interval"] if self.steps else 0
            return True
        if self.phase == "move":
            if self.steps:
                kind, v = self.steps.pop(0)
                self.pos = self.pos._replace(rot=v) if kind == "rot" else self.pos._replace(x=v)
            if not self.steps:
                self.phase = "fall"
            self.timer += o["move_interval"] if self.steps else o["drop_interval"]
            return True
        if self.phase == "fall":
            if self.pos.y < self.target.y:
                self.pos = self.pos._replace(y=self.pos.y + 1)
                self.timer += o["drop_interval"]
                return True
            full = self.game.place(self.piece, self.target)
            for y in full:
                self.glints[y] = self.t
            if self.game.over:
                self.game_over()
            else:
                self.phase, self.timer = "lock", self.timer + o["lock_delay"]
            return True
        if self.phase == "lock":
            self.spawn(self.n + 1)
            return True
        if self.phase == "flush":
            if self.flush_stage == "flash":
                self.flush_stage, self.flush_start = "drop", self.t
                self.timer += FLUSH_DROP
                return True
            self.game.clear_row(self.flush_row)
            full = self.game.full_rows()
            if full:
                self.flush_next(full)
            else:
                self.resume_after_flush()
            return True
        if self.phase == "over":
            self.phase, self.timer, self.wipe_start = "wipe", CELLS * WIPE_ROW, self.t
            return True
        if self.phase == "wipe":
            self.new_game(self.screen)
            return False
        return False

    # Drawing

    def draw(self, canvas):
        wipe = (self.t - self.wipe_start) / WIPE_ROW if self.phase == "wipe" else -1
        flash = drop = 0.0   # flush: the row being removed flashes white, then the rows above slide down
        if self.phase == "flush":
            k = min(1.0, (self.t - self.flush_start) / (FLUSH_FLASH if self.flush_stage == "flash" else FLUSH_DROP))
            if self.flush_stage == "flash":
                flash = k
            else:
                drop = k
        for y, row in enumerate(self.game.colors):
            if y < int(wipe):
                continue   # already wiped
            dy = 0
            if self.phase == "flush":
                if y == self.flush_row and self.flush_stage == "drop":
                    continue   # removed; the rows above are sliding into its place
                if y < self.flush_row:
                    dy = round(drop * CELL)
            glint = self.glints.get(y)
            sweep = None
            if glint is not None:
                age = self.t - glint
                if age > GLINT:
                    del self.glints[y]
                else:
                    sweep = age / GLINT * (CELLS + 4) - 2
            for x, p in enumerate(row):
                if p is None:
                    continue
                fill, edge = self.palette[p]
                k = 0.0
                if sweep is not None:
                    k = max(0.0, 1 - abs(x - sweep) / 2.5) * 0.85
                if y == int(wipe):
                    k = max(k, wipe - int(wipe))
                if self.phase == "flush" and y == self.flush_row:
                    k = max(k, flash)
                if k:
                    fill, edge = toward_white(fill, k), toward_white(edge, k)
                self.draw_cell(canvas, x, y, fill, edge, dy)
        if self.phase not in ("wait", "move", "fall"):
            return
        fill, edge = self.palette[self.piece]
        cells = self.well.cells(self.piece, self.pos)
        if self.target and self.phase == "move" and self.opts["ghost"] > 0:
            g = self.opts["ghost"]
            for x, y in self.well.cells(self.piece, self.target):
                if (x, y) not in cells:
                    self.draw_cell(canvas, x, y, scale(fill, g), scale(edge, g))
        for x, y in cells:
            self.draw_cell(canvas, x, y, fill, edge)

    @staticmethod
    def draw_cell(canvas, x, y, fill, edge, dy=0):
        """A cell at (x, y), drawn dy pixels lower (a row sliding down during a flush)."""
        if y < 0:
            return
        px, py = x * CELL, y * CELL + dy
        r, g, b = fill
        for dy in range(CELL - 1):
            for dx in range(CELL - 1):
                canvas.SetPixel(px + dx, py + dy, r, g, b)
        r, g, b = edge
        for i in range(CELL):
            canvas.SetPixel(px + CELL - 1, py + i, r, g, b)
            if i < CELL - 1:
                canvas.SetPixel(px + i, py + CELL - 1, r, g, b)
