"""Tetris rules: rotation states, collision, placements, line clears, the 7-bag.

    .venv/bin/python -m unittest discover tests
"""
import random
import unittest

from pixelgrid.tetris.game import PIECES, Bag, Game, Move, Well, rotations


def board_from(well, picture):
    """Rows drawn as strings ('#' filled), bottom-aligned; missing rows on top are empty."""
    rows = [sum(1 << x for x, ch in enumerate(line) if ch == "#") for line in picture]
    return (0,) * (well.height - len(rows)) + tuple(rows)


class RotationTest(unittest.TestCase):
    def test_t_states_follow_srs(self):
        up, right, down, left = rotations("T")
        self.assertEqual(set(up), {(1, 0), (0, 1), (1, 1), (2, 1)})
        self.assertEqual(set(right), {(1, 0), (1, 1), (1, 2), (2, 1)})
        self.assertEqual(set(down), {(0, 1), (1, 1), (2, 1), (1, 2)})
        self.assertEqual(set(left), {(1, 0), (0, 1), (1, 1), (1, 2)})

    def test_i_vertical_is_third_column(self):
        self.assertEqual(set(rotations("I")[1]), {(2, 0), (2, 1), (2, 2), (2, 3)})

    def test_four_turns_come_back(self):
        for p in PIECES:
            states = rotations(p)
            self.assertEqual(len(states), 4)
            self.assertTrue(all(len(s) == 4 for s in states))

    def test_o_never_changes(self):
        self.assertEqual(len(set(rotations("O"))), 1)


class CollisionTest(unittest.TestCase):
    def setUp(self):
        self.well = Well(10, 8)

    def test_walls_and_floor(self):
        b = self.well.empty()
        self.assertTrue(self.well.fits(b, "I", 0, 0, 0))
        self.assertFalse(self.well.fits(b, "I", 0, -1, 0))
        self.assertTrue(self.well.fits(b, "I", 0, 6, 0))
        self.assertFalse(self.well.fits(b, "I", 0, 7, 0))
        self.assertTrue(self.well.fits(b, "I", 1, -2, 0))   # vertical I sits in box column 2
        self.assertFalse(self.well.fits(b, "O", 0, 0, 7))   # bottom row would be below the floor

    def test_blocks(self):
        b = board_from(self.well, ["#........."])
        self.assertFalse(self.well.fits(b, "O", 0, 0, 6))
        self.assertTrue(self.well.fits(b, "O", 0, 1, 6))

    def test_cells_above_top_fit(self):
        self.assertTrue(self.well.fits(self.well.empty(), "I", 1, 0, -2))

    def test_drop_lands_on_stack(self):
        b = board_from(self.well, ["##........", "##........"])
        self.assertEqual(self.well.drop(b, "O", 0, 0, 0), 4)   # rests on rows 6-7
        self.assertEqual(self.well.drop(b, "O", 0, 2, 0), 6)


class PlacementTest(unittest.TestCase):
    def test_counts_on_empty_board(self):
        well = Well(10, 20)
        b = well.empty()
        # Distinct landings per rotation state: a piece n cells wide fits in 10 - n + 1 columns.
        self.assertEqual(len(well.legal_moves(b, "O")), 9)
        self.assertEqual(len(well.legal_moves(b, "I")), 7 + 10)
        self.assertEqual(len(well.legal_moves(b, "S")), 8 + 9)
        self.assertEqual(len(well.legal_moves(b, "T")), 8 + 9 + 8 + 9)

    def test_blocked_spawn_means_no_moves(self):
        well = Well(10, 4)
        b = (0b0000111000,) + (0,) * 3
        self.assertEqual(well.legal_moves(b, "T"), [])

    def test_shift_stops_at_a_tall_column(self):
        well = Well(10, 4)
        # A wall at column 2 reaching the spawn row: nothing can get to its left.
        b = tuple(0b100 for _ in range(4))
        moves = well.legal_moves(b, "O")
        self.assertTrue(moves)
        self.assertTrue(all(m.x > 2 for m in moves))


class SimulateTest(unittest.TestCase):
    def setUp(self):
        self.well = Well(4, 4)

    def test_line_clear_collapses(self):
        b = board_from(self.well, ["#...", "###."])
        x = 3 - 2   # vertical I in box column 2 -> column 3
        y = self.well.drop(b, "I", 1, x, -2)
        move = Move(1, x, y)
        new, full, lock = self.well.simulate(b, "I", move)
        self.assertEqual(full, [3])
        self.assertFalse(lock)
        self.assertEqual(new, board_from(self.well, ["...#", "...#", "#..#"]))
        self.assertEqual(b, board_from(self.well, ["#...", "###."]))   # input untouched

    def test_keep_rows(self):
        b = board_from(self.well, ["###."])
        y = self.well.drop(b, "I", 1, 1, -2)
        new, full, _ = self.well.simulate(b, "I", Move(1, 1, y), clear=False)
        self.assertEqual(full, [3])
        self.assertEqual(new[3], 0b1111)

    def test_lock_out(self):
        b = board_from(self.well, ["#...", "#...", "#...", "#..."])
        _, _, lock = self.well.simulate(b, "I", Move(1, -2, -1))
        self.assertTrue(lock)


class GameTest(unittest.TestCase):
    def test_bag_has_every_piece_per_seven(self):
        bag = Bag(random.Random(3))
        for _ in range(5):
            self.assertEqual(sorted(next(bag) for _ in range(7)), sorted(PIECES))

    def test_seeded_sequence_repeats(self):
        well = Well()
        a, b = Game(well, seed=7), Game(well, seed=7)
        self.assertEqual([a.piece(i) for i in range(30)], [b.piece(i) for i in range(30)])

    def test_place_tracks_colors_and_clears(self):
        well = Well(4, 4)
        g = Game(well, clear_lines=True)
        g.place("I", Move(0, 0, 2))   # flat I in box row 1 -> board row 3: a full row
        self.assertEqual(g.lines, 1)
        self.assertEqual(g.board, (0, 0, 0, 0))
        self.assertTrue(all(c is None for row in g.colors for c in row))
        g2 = Game(well, clear_lines=False)
        g2.place("I", Move(0, 0, 2))
        self.assertEqual(g2.colors[3], ["I"] * 4)
        self.assertEqual(g2.filled(), 4)


if __name__ == "__main__":
    unittest.main()
