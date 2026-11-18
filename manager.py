#!/usr/bin/env python3
"""Display service: the entry point systemd runs at boot.

Plays the queue (or a random mode when it's empty), serves the HTTP API
(see api.py), and records every play in SQLite (config "manager" -> "db_path").

    sudo .venv/bin/python manager.py
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description="Run the display service (queue, random modes, HTTP API).")
    p.add_argument("--config", default=str(HERE / "config.json"))
    args = p.parse_args()
    if not Path(args.config).exists():
        sys.exit(f"{args.config} not found. Create it with: cp config.example.json config.json")
    with open(args.config) as f:
        config = json.load(f)
    mcfg = config.get("manager", {})

    from api import start_api
    from display_manager import DisplayManager
    from store import Store

    store = Store(HERE / mcfg.get("db_path", "data/pixelgrid.db"))
    manager = DisplayManager(config, store)
    try:
        for name in mcfg.get("random_modes", []):
            manager.make_entry(name)  # fail fast on a bad config instead of mid-rotation
    except ValueError as e:
        manager.matrix.Clear()
        sys.exit(f"config error in manager.random_modes: {e}")

    server = start_api(manager, store, mcfg.get("http_host", "0.0.0.0"),
                       int(mcfg.get("http_port", 8080)), mcfg.get("api_token"))
    try:
        manager.run_service()
    finally:
        server.shutdown()
        store.close()


if __name__ == "__main__":
    main()
