"""Headless tetris games for tuning the AI weights (no panel needed).

    .venv/bin/python -m tools.tetris_sim --games 50                       # play-keep (packer)
    .venv/bin/python -m tools.tetris_sim --lookahead 0 --games 200        # 1-ply only
    .venv/bin/python -m tools.tetris_sim --weights holes=-12,wells=-2     # try other weights

Reports pieces per game, how full the board was at top-out, holes left, lines, the
tetris rate (clearing rules) and the time per decision.
"""
import argparse
import random
import statistics
import time

from pixelgrid.activities.tetris import SCREEN_RULES
from pixelgrid.tetris.agent import PERSONALITIES, Agent, features
from pixelgrid.tetris.game import Game, Well


def play(well, agent, seed, clear, max_pieces):
    game = Game(well, seed=seed, clear_lines=clear)
    times = []
    while not game.over and game.placed < max_pieces:
        n = game.placed
        t = time.perf_counter()
        choice = agent.choose(game.board, game.piece(n), game.piece(n + 1))
        times.append(time.perf_counter() - t)
        if choice is None:
            break
        game.place(game.piece(n), choice.move)
    return game, times


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--screen", default="play-keep", choices=sorted(SCREEN_RULES))
    p.add_argument("--personality", help="override the screen's personality")
    p.add_argument("--weights", default="", help="weight overrides, e.g. holes=-12,wells=-2")
    p.add_argument("--games", type=int, default=20)
    p.add_argument("--seed", type=int, default=1, help="first game's seed (games use seed, seed+1, ...)")
    p.add_argument("--lookahead", type=int, default=8)
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--misdrop-rate", type=float, default=0.0)
    p.add_argument("--width", type=int, default=16)
    p.add_argument("--height", type=int, default=16)
    p.add_argument("--max-pieces", type=int, default=2000, help="stop a game that's still going after this many")
    a = p.parse_args()

    personality, clear = SCREEN_RULES[a.screen]
    weights = dict(PERSONALITIES[a.personality or personality])
    for kv in filter(None, a.weights.split(",")):
        k, v = kv.split("=")
        weights[k.strip()] = float(v)
    well = Well(a.width, a.height)
    agent = Agent(well, weights, a.lookahead, a.temperature, a.misdrop_rate, clear, random.Random(a.seed))
    cells = a.width * a.height

    pieces, fill, holes, lines, tetrises, times = [], [], [], [], [], []
    for g in range(a.games):
        game, t = play(well, agent, a.seed + g, clear, a.max_pieces)
        pieces.append(game.placed)
        fill.append(game.filled() / cells)
        holes.append(features(well, game.board)["holes"])
        lines.append(game.lines)
        tetrises.append(game.clears[4])
        times += t

    def stat(xs, fmt="{:.1f}"):
        return f"{fmt.format(statistics.mean(xs))} (min {fmt.format(min(xs))}, max {fmt.format(max(xs))})"

    print(f"{a.games} games, {a.screen} ({'clearing' if clear else 'rows kept'}), {a.width}x{a.height}, "
          f"lookahead {a.lookahead}")
    print(f"weights: {weights}")
    print(f"pieces:         {stat(pieces)}")
    print(f"fill at end:    {stat([f * 100 for f in fill], '{:.1f}%')}")
    print(f"holes at end:   {stat(holes)}")
    print(f"lines:          {stat(lines)}")
    if clear:
        total = sum(lines) or 1
        print(f"tetris rate:    {sum(tetrises) * 4 / total:.0%} of lines")
    times.sort()
    print(f"decision time:  mean {statistics.mean(times) * 1000:.1f} ms, "
          f"p95 {times[int(len(times) * 0.95)] * 1000:.1f} ms, max {times[-1] * 1000:.1f} ms")


if __name__ == "__main__":
    main()
