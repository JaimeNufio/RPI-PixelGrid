#!/usr/bin/env python3
"""Rainbow diagonal test for a 64x64 RGB LED matrix on an Adafruit RGB Matrix HAT/Bonnet.

The rainbow runs from the top-left corner to the bottom-right corner and
scrolls continuously along that diagonal.

    .venv/bin/python -m tools.rainbow_test
    .venv/bin/python -m tools.rainbow_test --brightness 50 --speed 2 --duration 20
"""
import argparse
import colorsys
import time

from pixelgrid.matrix import SIZE, add_matrix_args, build_matrix


def parse_args():
    p = argparse.ArgumentParser(description="Diagonal rainbow test for a 64x64 matrix")
    add_matrix_args(p)
    p.add_argument("--speed", type=float, default=1.0, help="hue steps per frame (default 1.0)")
    p.add_argument("--fps", type=float, default=60.0, help="target frame rate (default 60)")
    p.add_argument("--duration", type=float, default=0,
                   help="seconds to run before exiting; 0 = until Ctrl+C (default 0)")
    return p.parse_args()


def build_palette(steps):
    """One full hue cycle, precomputed so the frame loop stays cheap."""
    palette = []
    for i in range(steps):
        r, g, b = colorsys.hsv_to_rgb(i / steps, 1.0, 1.0)
        palette.append((int(r * 255), int(g * 255), int(b * 255)))
    return palette


def main():
    args = parse_args()
    matrix = build_matrix(args)
    canvas = matrix.CreateFrameCanvas()

    # x + y ranges 0..126 across the diagonal; map that span onto one full hue cycle.
    diag_span = 2 * (SIZE - 1)
    steps = 256
    palette = build_palette(steps)
    # Precompute each pixel's base palette index from its diagonal position.
    base = [[(x + y) * steps // (diag_span + 1) for x in range(SIZE)] for y in range(SIZE)]

    frame_time = 1.0 / args.fps
    offset = 0.0
    print("Running rainbow test. Ctrl+C to stop.")
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    frames = 0
    t0 = time.monotonic()
    try:
        while deadline is None or time.monotonic() < deadline:
            start = time.monotonic()
            shift = int(offset)
            for y in range(SIZE):
                row = base[y]
                for x in range(SIZE):
                    # Subtract the shift so colors flow from top-left toward bottom-right.
                    r, g, b = palette[(row[x] - shift) % steps]
                    canvas.SetPixel(x, y, r, g, b)
            canvas = matrix.SwapOnVSync(canvas)
            offset = (offset + args.speed) % steps
            frames += 1

            elapsed = time.monotonic() - start
            if elapsed < frame_time:
                time.sleep(frame_time - elapsed)
    except KeyboardInterrupt:
        pass
    finally:
        matrix.Clear()
        elapsed = time.monotonic() - t0
        if elapsed > 0:
            print(f"Rendered {frames} frames in {elapsed:.1f}s ({frames / elapsed:.1f} fps)")


if __name__ == "__main__":
    main()
