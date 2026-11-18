"""Shared matrix setup for the 64x64 panel on the Adafruit RGB Matrix HAT.

Works with or without sudo:
- As root: full performance (hardware PWM timing via /dev/mem).
- As a normal user in the 'gpio' group: drives the panel through /dev/gpiomem
  with software timing. Slightly more flicker, but no sudo needed.
"""
import os

from rgbmatrix import RGBMatrix, RGBMatrixOptions

SIZE = 64

# Library timing settings that config.json may set under display.matrix_options
# (names as in rgbmatrix.RGBMatrixOptions; see rpi-rgb-led-matrix/include/led-matrix.h).
TUNABLE_OPTIONS = {
    "limit_refresh_rate_hz": int,   # cap the refresh rate so every frame gets equal time (0 = no cap)
    "pwm_bits": int,                # color depth per channel, 1-11 (lower = faster refresh)
    "pwm_lsb_nanoseconds": int,     # base PWM time slice (higher = steadier, less ghosting, slower)
    "pwm_dither_bits": int,         # time-dither low bits for a higher refresh rate
    "show_refresh_rate": bool,      # print the live refresh rate to stdout (debugging)
}


def add_matrix_args(parser):
    parser.add_argument("--brightness", type=int, default=60, help="0-100 (default 60)")
    parser.add_argument("--mapping", default="adafruit-hat-pwm",
                        help="adafruit-hat-pwm (GPIO4-GPIO18 jumper), adafruit-hat, regular "
                             "(default adafruit-hat-pwm)")
    parser.add_argument("--slowdown", type=int, default=4,
                        help="GPIO slowdown; Pi 4 usually needs 3-5 (default 4)")


def check_tunables(extra):
    """Validate display.matrix_options; returns them converted to the right types."""
    unknown = sorted(set(extra) - set(TUNABLE_OPTIONS))
    if unknown:
        raise ValueError(f"display.matrix_options: unknown option(s) {', '.join(unknown)}; "
                         f"supported: {', '.join(sorted(TUNABLE_OPTIONS))}")
    return {k: TUNABLE_OPTIONS[k](v) for k, v in extra.items()}


def build_matrix(args, extra=None):
    """args: brightness, mapping, slowdown. extra: display.matrix_options from config.json."""
    is_root = os.geteuid() == 0
    opts = RGBMatrixOptions()
    opts.rows = SIZE
    opts.cols = SIZE
    opts.chain_length = 1
    opts.parallel = 1
    opts.hardware_mapping = args.mapping
    opts.gpio_slowdown = args.slowdown
    opts.brightness = max(0, min(100, args.brightness))
    opts.drop_privileges = False
    # The hardware pulse timer needs /dev/mem (root). Without it, fall back to software timing.
    opts.disable_hardware_pulsing = not is_root
    for key, value in check_tunables(extra or {}).items():
        setattr(opts, key, value)
    if not is_root:
        print("Running without root: using /dev/gpiomem and software timing (a bit more flicker).")
    return RGBMatrix(options=opts)
