#!/usr/bin/env python3
"""Diagnostics for finding a bad pixel on the 64x64 panel. No sudo needed.

Modes:
  solid  Fill the panel red, green, blue, then white. A weak LED shows up
         dim or off-color in one of these.
  grid   Draw a coordinate grid (line every 8 px; brighter every 16 px; the
         top-left corner is marked) so you can read off the bad pixel's x,y.
  walk   Light one white pixel at a time, row by row, printing its x,y.
         Use --rows to limit it to the rows around the bad pixel.
  pixel  Flash a single pixel at --x --y through red/green/blue/white,
         next to a neighbor for comparison.
  circle Fill a disc of --radius around --x --y and cycle it through
         red/green/blue/white so the center can be compared with its neighbors.

Examples:
  .venv/bin/python -m tools.pixel_check solid
  .venv/bin/python -m tools.pixel_check grid
  .venv/bin/python -m tools.pixel_check walk --rows 20-24 --delay 0.05
  .venv/bin/python -m tools.pixel_check pixel --x 37 --y 22
  .venv/bin/python -m tools.pixel_check circle --x 32 --y 5 --radius 5 --hold 2
"""
import argparse
import time

from pixelgrid.matrix import SIZE, add_matrix_args, build_matrix

COLORS = [("red", (255, 0, 0)), ("green", (0, 255, 0)), ("blue", (0, 0, 255)),
          ("white", (255, 255, 255))]


def parse_rows(spec):
    lo, _, hi = spec.partition("-")
    lo = int(lo)
    hi = int(hi) if hi else lo
    if not (0 <= lo <= hi < SIZE):
        raise argparse.ArgumentTypeError(f"rows must be within 0-{SIZE - 1}")
    return lo, hi


def parse_args():
    p = argparse.ArgumentParser(description="Bad-pixel diagnostics for a 64x64 matrix",
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    p.add_argument("mode", choices=["solid", "grid", "walk", "pixel", "circle"])
    add_matrix_args(p)
    p.add_argument("--hold", type=float, default=5.0,
                   help="seconds per color in solid/pixel mode, or total for grid (default 5)")
    p.add_argument("--delay", type=float, default=0.02, help="seconds per step in walk mode")
    p.add_argument("--rows", type=parse_rows, default=(0, SIZE - 1),
                   help="row range for walk mode, e.g. 20-24 (default all)")
    p.add_argument("--x", type=int, help="pixel x (0-63) for pixel mode")
    p.add_argument("--y", type=int, help="pixel y (0-63) for pixel mode")
    p.add_argument("--radius", type=int, default=5, help="disc radius for circle mode (default 5)")
    p.add_argument("--cycles", type=int, default=0,
                   help="color cycles in circle mode; 0 = until Ctrl+C (default 0)")
    args = p.parse_args()
    if args.mode in ("pixel", "circle"):
        if args.x is None or args.y is None:
            p.error(f"{args.mode} mode needs --x and --y")
        if not (0 <= args.x < SIZE and 0 <= args.y < SIZE):
            p.error(f"--x and --y must be within 0-{SIZE - 1}")
    return args


def show(matrix, canvas):
    return matrix.SwapOnVSync(canvas)


def solid(matrix, canvas, args):
    for name, (r, g, b) in COLORS:
        print(f"Solid {name} for {args.hold:g}s")
        canvas.Fill(r, g, b)
        canvas = show(matrix, canvas)
        time.sleep(args.hold)
    return canvas


def grid(matrix, canvas, args):
    canvas.Clear()
    for i in range(SIZE):
        for j in range(0, SIZE, 8):
            level = 255 if j % 16 == 0 else 60
            canvas.SetPixel(j, i, level, level, level)  # vertical lines
            canvas.SetPixel(i, j, level, level, level)  # horizontal lines
    canvas.SetPixel(0, 0, 255, 0, 0)  # red marks x=0, y=0 (top-left)
    canvas.SetPixel(1, 0, 255, 0, 0)
    canvas.SetPixel(0, 1, 255, 0, 0)
    print("Grid: lines every 8 px (bright at 0, 16, 32, 48). Red corner = (0,0).")
    show(matrix, canvas)
    time.sleep(args.hold)
    return canvas


def walk(matrix, canvas, args):
    lo, hi = args.rows
    print(f"Walking rows {lo}-{hi}. Watch for a pixel that is dim, off-color, or missing.")
    for y in range(lo, hi + 1):
        print(f"row {y}")
        for x in range(SIZE):
            canvas.Clear()
            canvas.SetPixel(x, y, 255, 255, 255)
            canvas = show(matrix, canvas)
            time.sleep(args.delay)
    return canvas


def pixel(matrix, canvas, args):
    # Compare against a neighbor in the same row so differences are easy to see.
    nx = args.x + 2 if args.x + 2 < SIZE else args.x - 2
    print(f"Pixel ({args.x},{args.y}) vs neighbor ({nx},{args.y})")
    for name, (r, g, b) in COLORS:
        print(f"  {name} for {args.hold:g}s")
        canvas.Clear()
        canvas.SetPixel(args.x, args.y, r, g, b)
        canvas.SetPixel(nx, args.y, r, g, b)
        canvas = show(matrix, canvas)
        time.sleep(args.hold)
    return canvas


def circle(matrix, canvas, args):
    r2 = args.radius * args.radius
    # Pixels whose centers fall inside the radius; clipped at the panel edges.
    disc = [(x, y)
            for y in range(max(0, args.y - args.radius), min(SIZE, args.y + args.radius + 1))
            for x in range(max(0, args.x - args.radius), min(SIZE, args.x + args.radius + 1))
            if (x - args.x) ** 2 + (y - args.y) ** 2 <= r2]
    print(f"Circle r={args.radius} around ({args.x},{args.y}): {len(disc)} pixels. Ctrl+C to stop.")
    n = 0
    while args.cycles == 0 or n < args.cycles:
        for name, (r, g, b) in COLORS:
            print(f"  {name}")
            canvas.Clear()
            for x, y in disc:
                canvas.SetPixel(x, y, r, g, b)
            canvas = show(matrix, canvas)
            time.sleep(args.hold)
        n += 1
    return canvas


def main():
    args = parse_args()
    matrix = build_matrix(args)
    canvas = matrix.CreateFrameCanvas()
    try:
        {"solid": solid, "grid": grid, "walk": walk, "pixel": pixel,
         "circle": circle}[args.mode](matrix, canvas, args)
    except KeyboardInterrupt:
        pass
    finally:
        matrix.Clear()


if __name__ == "__main__":
    main()
