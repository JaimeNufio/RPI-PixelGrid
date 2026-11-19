#!/usr/bin/env python3
"""Control the running display service over its HTTP API. No sudo needed.

Reads the port and api_token from config.json, so you never type the token.

    .venv/bin/python -m pixelgrid.ctl status
    .venv/bin/python -m pixelgrid.ctl play snow-clock
    .venv/bin/python -m pixelgrid.ctl play clock --duration 300
    .venv/bin/python -m pixelgrid.ctl play snow --widget clock --opt rate=10
    .venv/bin/python -m pixelgrid.ctl skip
    .venv/bin/python -m pixelgrid.ctl restart     # reload code + config; waits for the new process
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from pixelgrid.config import CONFIG_PATH, load_config


class Client:
    def __init__(self, config):
        m = config.get("manager", {})
        self.base = f"http://127.0.0.1:{int(m.get('http_port', 8080))}"
        self.token = m.get("api_token")

    def call(self, method, path, body=None, timeout=5):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, method=method, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("error", "")
            except ValueError:
                msg = ""
            sys.exit(f"error: HTTP {e.code} {msg}".rstrip())
        except OSError as e:
            raise ConnectionError(f"service not reachable at {self.base} ({e})") from None


def parse_opt(text):
    """key=value -> (key, value); values are parsed as JSON when possible (numbers, null, ...)."""
    key, sep, value = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected key=value, got {text!r}")
    try:
        return key, json.loads(value)
    except ValueError:
        return key, value


def show(obj):
    print(json.dumps(obj, indent=2))


def cmd_status(c, args):
    show({"health": c.call("GET", "/health"), "activity": c.call("GET", "/activity")})


def cmd_play(c, args):
    body = {"activity": args.activity, "options": dict(args.opt or [])}
    if args.duration is not None:
        body["duration"] = args.duration
    if args.screen:
        body["screen"] = args.screen
    if args.no_widgets:
        body["widgets"] = []
    elif args.widget:
        body["widgets"] = args.widget
    show(c.call("PUT", "/activity", body))


def cmd_skip(c, args):
    show(c.call("POST", "/activity/skip"))


def cmd_restart(c, args):
    old = c.call("GET", "/health")
    c.call("POST", "/admin/restart")
    print(f"Restarting (pid {old['pid']}, code {old.get('version')}) ...", flush=True)
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        time.sleep(0.5)
        try:
            new = c.call("GET", "/health", timeout=2)
        except ConnectionError:
            continue
        if new["pid"] != old["pid"] and new.get("activity"):  # new process, and an activity is on screen
            st = c.call("GET", "/activity")
            print(f"Back up: pid {new['pid']}, code {new.get('version')}, "
                  f"playing {st.get('preset') or st.get('activity')} ({st.get('source')})")
            return
    sys.exit(f"error: service didn't come back within {args.timeout:g}s; "
             "check: systemctl status pixelgrid / journalctl -u pixelgrid -n 50")


def main(argv=None):
    p = argparse.ArgumentParser(description="Control the running display service (no sudo needed).")
    p.add_argument("--config", default=str(CONFIG_PATH))
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="process info and what's playing").set_defaults(fn=cmd_status)
    pl = sub.add_parser("play", help="play an activity or preset right now")
    pl.add_argument("activity")
    pl.add_argument("--duration", type=float, help="seconds; omit to play until replaced")
    pl.add_argument("--screen", help="play only this screen of the activity (e.g. forecast)")
    pl.add_argument("--widget", action="append", help="widget to draw on top (repeatable)")
    pl.add_argument("--no-widgets", action="store_true", help="drop a preset's widgets")
    pl.add_argument("--opt", action="append", type=parse_opt, metavar="KEY=VALUE", help="activity option override")
    pl.set_defaults(fn=cmd_play)
    sub.add_parser("skip", help="move on to the next item").set_defaults(fn=cmd_skip)
    rs = sub.add_parser("restart", help="restart the service to load new code/config")
    rs.add_argument("--timeout", type=float, default=30)
    rs.set_defaults(fn=cmd_restart)
    args = p.parse_args(argv)
    try:
        args.fn(Client(load_config(args.config)), args)
    except ConnectionError as e:
        sys.exit(f"error: {e}. Is it running? systemctl status pixelgrid")


if __name__ == "__main__":
    main()
