"""Tetris AI: board features and placement choices.

    .venv/bin/python -m unittest discover tests
"""
import random
import unittest

from pixelgrid.tetris.agent import PERSONALITIES, Agent, features
from pixelgrid.tetris.game import Game, Well
from tests.test_tetris_game import board_from


class FeatureTest(unittest.TestCase):
    def setUp(self):
        self.well = Well(4, 4)

    def test_empty_board(self):
        f = features(self.well, self.well.empty())
        self.assertEqual(f["holes"], 0)
        self.assertEqual(f["max_height"], 0)
        self.assertEqual(f["bumpiness"], 0)
        self.assertEqual(f["row_transitions"], 4 * 2)   # each empty row: wall->empty, empty->wall
        self.assertEqual(f["col_transitions"], 4)       # each empty column meets the floor

    def test_holes_and_heights(self):
        b = board_from(self.well, ["##..",
                                   ".#..",
                                   "#..."])
        f = features(self.well, b)
        self.assertEqual(f["holes"], 2)   # under the top of column 0 and of column 1
        self.assertEqual(f["max_height"], 3)
        self.assertEqual(f["aggregate_height"], 6)
        self.assertEqual(f["bumpiness"], 0 + 3 + 0)

    def test_well_depth(self):
        b = board_from(self.well, ["#.##",
                                   "#.##"])
        self.assertEqual(features(self.well, b)["wells"], 1 + 2)

    def test_edge_well_uses_the_wall(self):
        b = board_from(self.well, [".###"])
        self.assertEqual(features(self.well, b)["wells"], 1)


class AgentTest(unittest.TestCase):
    def test_fills_the_obvious_slot(self):
        well = Well(4, 8)
        b = board_from(well, ["###.", "###.", "###.", "###."])
        agent = Agent(well, PERSONALITIES["packer"], lookahead=0)
        choice = agent.choose(b, "I")
        self.assertEqual({x for x, _ in well.cells("I", choice.move)}, {3})

    def test_prefers_no_holes(self):
        well = Well(6, 6)
        b = board_from(well, ["#.####"])
        agent = Agent(well, PERSONALITIES["packer"], lookahead=0)
        choice = agent.choose(b, "O")
        self.assertEqual(features(well, choice.board)["holes"], 0)

    def test_packer_fills_most_of_the_board(self):
        well = Well(16, 16)
        agent = Agent(well, PERSONALITIES["packer"], lookahead=0, clear_lines=False)
        game = Game(well, seed=1, clear_lines=False)
        while not game.over:
            c = agent.choose(game.board, game.piece(game.placed), game.piece(game.placed + 1))
            if c is None:
                break
            game.place(game.piece(game.placed), c.move)
        self.assertGreater(game.filled() / 256, 0.75)

    def test_temperature_and_misdrop_stay_legal(self):
        well = Well(10, 12)
        agent = Agent(well, PERSONALITIES["packer"], lookahead=2, temperature=0.5, misdrop_rate=0.5,
                      rng=random.Random(4))
        game = Game(well, seed=4)
        for _ in range(40):
            if game.over:
                break
            piece = game.piece(game.placed)
            legal = well.legal_moves(game.board, piece)
            c = agent.choose(game.board, piece, game.piece(game.placed + 1))
            if c is None:
                break
            self.assertIn(c.move, legal)
            game.place(piece, c.move)

    def test_search_yields_and_matches_choose(self):
        well = Well()
        agent = Agent(well, PERSONALITIES["packer"], lookahead=4)
        b = well.empty()
        gen = agent.search(b, "T", "L")
        steps = 0
        try:
            while True:
                next(gen)
                steps += 1
        except StopIteration as done:
            result = done.value
        self.assertGreater(steps, 1)
        self.assertEqual(result.move, agent.choose(b, "T", "L").move)


if __name__ == "__main__":
    unittest.main()
