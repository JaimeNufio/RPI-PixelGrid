"""Tetris AI: try every placement, score the board it leaves, pick one.

The score is a weighted sum of board features (El-Tetris / Dellacherie style):

    landing_height   height of the piece's center where it lands
    holes            empty cells with a filled cell somewhere above
    row_transitions  filled<->empty changes along each row (walls count as filled)
    col_transitions  filled<->empty changes down each column (the floor counts as filled)
    wells            depth-weighted well cells: open cells with both sides filled (1+2+..+depth)
    bumpiness        sum of height differences between neighboring columns
    max_height       tallest column
    lines            rows completed by this piece (cleared or, when rows are kept, left full)

A personality is a dict of weights. With lookahead, the best `lookahead` placements are
rechecked against every placement of the next piece and ranked by the best pair.
search() is a generator that yields between chunks of work, so the frame loop can spread
one decision over several frames; choose() runs it to the end.
"""
import math
import random
from collections import namedtuple

from pixelgrid.tetris.game import popcount

PERSONALITIES = {
    # Packs the board as densely as possible (for rules where full rows stay).
    "packer": {"landing_height": -4.5, "holes": -7.9, "row_transitions": -3.2,
               "col_transitions": -9.3, "wells": -3.4, "lines": 3.4},
}

LOCK_OUT = -1e9   # score of a placement that sticks out over the top

Choice = namedtuple("Choice", "move board full score")


def features(well, board):
    """Board features of a post-placement board (everything except landing_height and lines)."""
    w, h, full = well.width, well.height, well.full
    walls = 1 | (1 << (w + 1))
    pairs = (1 << (w + 1)) - 1   # the w + 1 neighbor pairs from wall to wall
    edge_right = 1 << (w - 1)
    seen = 0            # columns with a filled cell at or above this row
    holes = row_tr = col_tr = wells = 0
    heights = [0] * w
    run = [0] * w       # current well depth per column
    prev_wells = 0
    prev = 0            # row above (the open space over the board counts as empty)
    for y, r in enumerate(board):
        holes += popcount(seen & ~r)
        new = r & ~seen
        while new:
            b = new & -new
            heights[b.bit_length() - 1] = h - y
            new ^= b
        seen |= r
        padded = (r << 1) | walls
        row_tr += popcount((padded ^ (padded >> 1)) & pairs)
        if y:
            col_tr += popcount(prev ^ r)
        prev = r
        # Open cells (nothing above) whose left and right neighbors are filled or a wall.
        wm = ~r & ((r << 1) | 1) & ((r >> 1) | edge_right) & full & ~seen
        changed = wm | prev_wells
        while changed:
            b = changed & -changed
            x = b.bit_length() - 1
            if wm & b:
                run[x] += 1
                wells += run[x]
            else:
                run[x] = 0
            changed ^= b
        prev_wells = wm
    col_tr += popcount(full & ~board[-1])
    bump = sum(abs(heights[i] - heights[i + 1]) for i in range(w - 1))
    return {"holes": holes, "row_transitions": row_tr, "col_transitions": col_tr, "wells": wells,
            "bumpiness": bump, "max_height": max(heights), "aggregate_height": sum(heights)}


class Agent:
    def __init__(self, well, weights, lookahead=8, temperature=0.0, misdrop_rate=0.0,
                 clear_lines=True, rng=None):
        self.well = well
        self.weights = weights
        self.lookahead = lookahead
        self.temperature = temperature
        self.misdrop_rate = misdrop_rate
        self.clear_lines = clear_lines
        self.rng = rng or random.Random()

    def evaluate(self, board, piece, move):
        """(score, new board, full rows) for one placement."""
        new, full, locked_out = self.well.simulate(board, piece, move, self.clear_lines)
        if locked_out:
            return LOCK_OUT, new, full
        f = features(self.well, new)
        f["landing_height"] = self.well.height - (move.y + self.well.shapes[piece][move.rot].center_y)
        f["lines"] = len(full)
        return sum(wt * f[k] for k, wt in self.weights.items()), new, full

    def search(self, board, piece, next_piece=None):
        """Generator: yields while working, returns a Choice (None if the piece can't spawn)."""
        moves = self.well.legal_moves(board, piece)
        if not moves:
            return None
        ranked = []
        for i, m in enumerate(moves):
            score, new, full = self.evaluate(board, piece, m)
            ranked.append(Choice(m, new, full, score))
            if i % 8 == 7:
                yield
        ranked.sort(key=lambda c: c.score, reverse=True)
        if self.lookahead and next_piece:
            rescored = []
            for c in ranked[:self.lookahead]:
                yield
                nexts = self.well.legal_moves(c.board, next_piece) if c.score > LOCK_OUT else []
                best = LOCK_OUT
                for i, m in enumerate(nexts):
                    best = max(best, self.evaluate(c.board, next_piece, m)[0])
                    if i % 8 == 7:
                        yield
                rescored.append(c._replace(score=c.score + best))
            ranked = sorted(rescored, key=lambda c: c.score, reverse=True)
        choice = self.pick(ranked)
        return self.misdrop(board, piece, moves, choice)

    def pick(self, ranked):
        """The best choice, or with temperature > 0 a softmax draw over the ranked scores
        (normalized to 0..1 between the worst and best, so temperature means the same on any
        board). Lock-outs are only picked when nothing else is left."""
        alive = [c for c in ranked if c.score > LOCK_OUT] or ranked
        if self.temperature <= 0 or len(alive) == 1:
            return alive[0]
        hi, lo = alive[0].score, alive[-1].score
        span = (hi - lo) or 1.0
        weights = [math.exp((c.score - hi) / span / self.temperature) for c in alive]
        return self.rng.choices(alive, weights)[0]

    def misdrop(self, board, piece, moves, choice):
        """With probability misdrop_rate, land one column off (same rotation), if possible."""
        if self.misdrop_rate <= 0 or self.rng.random() >= self.misdrop_rate:
            return choice
        m = choice.move
        nearby = [n for n in moves if n.rot == m.rot and abs(n.x - m.x) == 1]
        if not nearby:
            return choice
        n = self.rng.choice(nearby)
        score, new, full = self.evaluate(board, piece, n)
        return Choice(n, new, full, score)

    def choose(self, board, piece, next_piece=None):
        gen = self.search(board, piece, next_piece)
        while True:
            try:
                next(gen)
            except StopIteration as done:
                return done.value
