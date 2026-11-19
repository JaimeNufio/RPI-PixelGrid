"""Tetris rules and AI, with no display code (unit-testable anywhere).

game.py   board, the 7 tetrominoes (SRS rotation states), 7-bag, placements, line clears
agent.py  board features, weighted placement search, personalities

The tetris activity (pixelgrid/activities/tetris.py) animates and draws a Game played by an
Agent; tools/tetris_sim.py plays headless games to tune the weights.
"""
