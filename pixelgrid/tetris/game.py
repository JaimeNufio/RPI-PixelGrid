"""Tetris rules on a bit-packed board.

A board is a tuple of `height` ints, one per row, top row first; bit x of a row is
column x (0 = left). Boards are never changed in place: simulate() returns a new one,
so the AI can try placements freely.

Pieces spawn centered at the top in their SRS spawn state. A move is (rot, x, y): the
rotation state (0-3, clockwise from spawn) and where the piece's bounding box lands.
Placements are what a player could reach by rotating and shifting in the spawn row,
then hard-dropping (no kicks, slides or spins).
"""
import random
from collections import namedtuple

PIECES = "IJLOSTZ"

# SRS spawn states: (box size, cells as (x, y) in the box, y down).
SPAWN = {
    "I": (4, ((0, 1), (1, 1), (2, 1), (3, 1))),
    "J": (3, ((0, 0), (0, 1), (1, 1), (2, 1))),
    "L": (3, ((2, 0), (0, 1), (1, 1), (2, 1))),
    "O": (2, ((0, 0), (1, 0), (0, 1), (1, 1))),
    "S": (3, ((1, 0), (2, 0), (0, 1), (1, 1))),
    "T": (3, ((1, 0), (0, 1), (1, 1), (2, 1))),
    "Z": (3, ((0, 0), (1, 0), (1, 1), (2, 1))),
}

# Rotation steps from the spawn state to each state: 1 = clockwise, -1 = counterclockwise.
ROTATE_STEPS = {0: (), 1: (1,), 2: (1, 1), 3: (-1,)}

Move = namedtuple("Move", "rot x y")


def rotations(piece):
    """The 4 rotation states of a piece, each a sorted tuple of (x, y) box cells."""
    n, cells = SPAWN[piece]
    states = [tuple(sorted(cells))]
    for _ in range(3):
        cells = tuple(sorted((n - 1 - y, x) for x, y in cells))   # clockwise in the n x n box
        states.append(cells)
    return states


def popcount(v):
    return v.bit_count()


class Shape:
    """One rotation state: its cells and per-row bit masks (at x = 0)."""

    def __init__(self, cells):
        self.cells = cells
        self.minx = min(x for x, _ in cells)
        self.maxx = max(x for x, _ in cells)
        self.top = min(y for _, y in cells)
        self.bottom = max(y for _, y in cells)
        self.rows = tuple((dy, sum(1 << x for x, y in cells if y == dy))
                          for dy in range(self.top, self.bottom + 1))
        self.center_y = sum(y for _, y in cells) / len(cells)


def shift(mask, x):
    return mask << x if x >= 0 else mask >> -x


class Well:
    """Board geometry and rules for a width x height well."""

    def __init__(self, width=16, height=16):
        self.width, self.height = width, height
        self.full = (1 << width) - 1
        self.shapes = {p: [Shape(c) for c in rotations(p)] for p in PIECES}
        self.spawn = {p: ((width - SPAWN[p][0]) // 2, -self.shapes[p][0].top) for p in PIECES}

    def empty(self):
        return (0,) * self.height

    def fits(self, board, piece, rot, x, y):
        s = self.shapes[piece][rot]
        if x + s.minx < 0 or x + s.maxx >= self.width:
            return False
        for dy, m in s.rows:
            yy = y + dy
            if yy >= self.height or (yy >= 0 and board[yy] & shift(m, x)):
                return False
        return True

    def drop(self, board, piece, rot, x, y):
        """The y where a piece at (rot, x, y) comes to rest."""
        while self.fits(board, piece, rot, x, y + 1):
            y += 1
        return y

    def legal_moves(self, board, piece):
        """Every distinct landing reachable from the spawn position (rotate in place, shift
        along the spawn row, hard drop). [] if the piece can't even spawn (topped out)."""
        sx, sy = self.spawn[piece]
        if not self.fits(board, piece, 0, sx, sy):
            return []
        moves, seen = [], set()
        for rot in range(4):
            r, ok = 0, True
            for step in ROTATE_STEPS[rot]:
                r = (r + step) % 4
                ok = ok and self.fits(board, piece, r, sx, sy)
            if not ok:
                continue
            rows = self.shapes[piece][rot].rows
            for direction in (-1, 1):
                x = sx if direction < 0 else sx + 1
                while self.fits(board, piece, rot, x, sy):
                    y = self.drop(board, piece, rot, x, sy)
                    key = tuple((y + dy, shift(m, x)) for dy, m in rows)   # same cells = same move
                    if key not in seen:
                        seen.add(key)
                        moves.append(Move(rot, x, y))
                    x += direction
        return moves

    def cells(self, piece, move):
        """Absolute (x, y) cells of a piece placed at move (y may be negative: above the top)."""
        return [(move.x + cx, move.y + cy) for cx, cy in self.shapes[piece][move.rot].cells]

    def simulate(self, board, piece, move, clear=True):
        """Place a piece. Returns (new board, full rows, locked_out): `full` lists the rows this
        piece completed (indices before any collapse); with clear=True they're removed and
        everything above drops. locked_out = part of the piece is above the top row."""
        s = self.shapes[piece][move.rot]
        rows = list(board)
        locked_out = False
        for dy, m in s.rows:
            yy = move.y + dy
            if yy < 0:
                locked_out = True
            else:
                rows[yy] |= shift(m, move.x)
        full = [y for y in range(max(0, move.y + s.top), min(self.height, move.y + s.bottom + 1))
                if rows[y] == self.full]
        if clear and full:
            rows = [0] * len(full) + [r for i, r in enumerate(rows) if i not in full]
        return tuple(rows), full, locked_out


class Bag:
    """7-bag randomizer: each run of 7 pieces holds every piece once, shuffled."""

    def __init__(self, rng):
        self.rng = rng
        self.pending = []

    def __next__(self):
        if not self.pending:
            self.pending = list(PIECES)
            self.rng.shuffle(self.pending)
        return self.pending.pop()


class Game:
    """One game: the board, its colors and the piece sequence. Pieces are numbered from 0;
    piece(n) is known ahead of time, so the AI can look at upcoming pieces."""

    def __init__(self, well, seed=None, clear_lines=True):
        self.well = well
        self.clear_lines = clear_lines
        self.bag = Bag(random.Random(seed))
        self.sequence = []
        self.board = well.empty()
        self.colors = [[None] * well.width for _ in range(well.height)]   # piece letter per cell
        self.placed = 0         # pieces locked so far
        self.lines = 0          # rows cleared (or completed, when rows are kept)
        self.clears = [0] * 5   # clears by size, clears[4] = tetrises
        self.cleared = 0        # kept rows removed later by clear_row() (play-keep's flush)
        self.over = False

    def piece(self, n):
        while len(self.sequence) <= n:
            self.sequence.append(next(self.bag))
        return self.sequence[n]

    def place(self, piece, move):
        """Lock a piece at move. Returns the rows it completed; sets `over` on a lock out."""
        self.board, full, locked_out = self.well.simulate(self.board, piece, move, self.clear_lines)
        for x, y in self.well.cells(piece, move):
            if y >= 0:
                self.colors[y][x] = piece
        if full and self.clear_lines:
            kept = [row for y, row in enumerate(self.colors) if y not in full]
            self.colors = [[None] * self.well.width for _ in full] + kept
        self.placed += 1
        self.lines += len(full)
        self.clears[len(full)] += 1
        self.over = locked_out
        return full

    def full_rows(self):
        """Rows that are completely filled (they stay when rows are kept), top to bottom."""
        return [y for y, r in enumerate(self.board) if r == self.well.full]

    def clear_row(self, y):
        """Remove row y; everything above it drops one row and an empty row appears on top."""
        self.board = (0,) + self.board[:y] + self.board[y + 1:]
        self.colors = [[None] * self.well.width] + self.colors[:y] + self.colors[y + 1:]
        self.cleared += 1

    def filled(self):
        return sum(popcount(r) for r in self.board)
