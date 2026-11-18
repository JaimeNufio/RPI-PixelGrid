#!/usr/bin/env python3
"""Run one mode directly, for testing. Defaults come from config.json; flags override them for this run.

For the always-on service with the queue and HTTP API, use pixelgrid.manager (see deploy/pixelgrid.service).
Run from the repository root:

    sudo .venv/bin/python -m pixelgrid.run                      # config defaults
    sudo .venv/bin/python -m pixelgrid.run --state clock --indefinite
    sudo .venv/bin/python -m pixelgrid.run --rate 3 --duration 600
    .venv/bin/python -m pixelgrid.run --help                    # every flag, with its config default
"""
import argparse
import socket
import sys

from pixelgrid.config import CONFIG_PATH, load_config
from pixelgrid.states import STATES


def flag(name):
    return "--" + name.replace("_", "-")


def build_parser(config, state_name):
    disp = config["display"]
    state_cfg = config["states"].get(state_name, {})
    run_cfg = config["run"]
    p = argparse.ArgumentParser(description="Run the LED display. Flags override config.json for this run.")
    p.add_argument("--config", default=str(CONFIG_PATH), help="config file (default: config.json in the repo root)")
    p.add_argument("--state", choices=sorted(STATES), help=f"state to show (config: {run_cfg['state']})")

    r = p.add_argument_group("run")
    r.add_argument("--duration", type=float,
                   help=f"seconds to run; 0 = indefinite (config: {run_cfg['duration']})")
    r.add_argument("--indefinite", action="store_true", help="run until Ctrl+C or SIGTERM")

    d = p.add_argument_group("display")
    d.add_argument("--brightness", type=int, help=f"0-100 (config: {disp['brightness']})")
    d.add_argument("--mapping", help=f"adafruit-hat-pwm, adafruit-hat, regular (config: {disp['mapping']})")
    d.add_argument("--slowdown", type=int, help=f"GPIO slowdown, Pi 4 usually 3-5 (config: {disp['slowdown']})")
    d.add_argument("--fps", type=float, help=f"frames per second (config: {disp['fps']})")
    d.add_argument("--show-bad-pixels", action="store_true",
                   help=f"don't black out bad pixels {disp.get('bad_pixels', [])}")

    s = p.add_argument_group(f"{state_name} options")
    for name, (typ, help_text) in STATES[state_name].OPTIONS.items():
        s.add_argument(flag(name), dest=name, type=typ,
                       help=f"{help_text} (config: {state_cfg.get(name, 'unset')})")
    return p


def resolve_duration(args, run_cfg):
    if args.indefinite:
        return None
    value = args.duration if args.duration is not None else run_cfg.get("duration", "indefinite")
    if value in ("indefinite", None, 0, 0.0):
        return None
    return float(value)


def service_running(config):
    """True if the display service's API is answering, meaning it owns the panel right now."""
    port = int(config.get("manager", {}).get("http_port", 8080))
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
        return True
    except OSError:
        return False


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # First pass: find the config file and state, since the state decides which flags exist.
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default=str(CONFIG_PATH))
    pre.add_argument("--state")
    known, _ = pre.parse_known_args(argv)
    config = load_config(known.config)
    state_name = known.state or config["run"]["state"]
    if state_name not in STATES:
        sys.exit(f"unknown state {state_name!r}; available: {', '.join(sorted(STATES))}")

    args = build_parser(config, state_name).parse_args(argv)

    if service_running(config):
        sys.exit("The display service is running and owns the panel. Stop it first:\n"
                 "  sudo systemctl stop pixelgrid\n"
                 "or send it this mode over the API instead (PUT /state).")

    for key in ("brightness", "mapping", "slowdown", "fps"):
        if getattr(args, key) is not None:
            config["display"][key] = getattr(args, key)
    if args.show_bad_pixels:
        config["display"]["mask_bad_pixels"] = False

    overrides = {name: getattr(args, name) for name in STATES[state_name].OPTIONS
                 if getattr(args, name) is not None}
    duration = resolve_duration(args, config["run"])

    # Imported here so --help works without touching the hardware library.
    from pixelgrid.display_manager import DisplayManager
    manager = DisplayManager(config)
    try:
        entry = manager.make_entry(state_name, overrides)
    except ValueError as e:
        manager.matrix.Clear()
        sys.exit(f"error: {e}")
    manager.run_once(entry, duration)


if __name__ == "__main__":
    main()
