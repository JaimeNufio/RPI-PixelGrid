#!/usr/bin/env python3
"""Display service: the entry point systemd runs at boot.

Plays the queue (or a random mode when it's empty), serves the HTTP API
(see api.py), and records every play in SQLite (config "manager" -> "db_path").

    sudo .venv/bin/python -m pixelgrid.manager      (from the repository root)
"""
import argparse
import sys

# Exit code meaning "please restart me". Any non-zero exit makes systemd
# (Restart=on-failure in deploy/pixelgrid.service) start a fresh process.
RESTART_EXIT_CODE = 75

from pixelgrid.config import CONFIG_PATH, load_config, resolve


def main():
    p = argparse.ArgumentParser(description="Run the display service (queue, random modes, HTTP API).")
    p.add_argument("--config", default=str(CONFIG_PATH))
    args = p.parse_args()
    config = load_config(args.config)
    mcfg = config.get("manager", {})

    from pixelgrid.api import start_api
    from pixelgrid.display_manager import DisplayManager
    from pixelgrid.store import Store

    store = Store(resolve(mcfg.get("db_path", "data/pixelgrid.db")))
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
    if manager.restart_requested:
        print(f"Manager: restart requested; exiting with code {RESTART_EXIT_CODE} so systemd restarts us.",
              flush=True)
        sys.exit(RESTART_EXIT_CODE)


if __name__ == "__main__":
    main()
