"""HTTP API for the display manager. Standard library only; runs in background threads.

  GET    /activities      available activities, their options and config defaults
  GET    /activity        what's playing now
  GET    /widgets         available widgets, their options and config defaults
  PUT    /activity        play something right now:
                          {"activity": "snow", "options": {...}, "duration": 60, "widgets": ["clock"],
                           "screen": null}
  POST   /activity/skip   end the current item and move on
  GET    /queue           queued items, in play order
  POST   /queue           add to the end of the queue (same body as PUT /activity)
  DELETE /queue           clear the queue
  DELETE /queue/<id>      remove one queued item
  GET    /history?limit=N recent plays, newest first (default 50, max 500)
  GET    /health          process id, start time and loaded code version
  POST   /admin/restart   restart the service to load new code/config (systemd restarts it)

"activity" may be an activity or a preset (config "presets"). "options" holds only
overrides; anything left out uses config.json. "widgets" is a list of names or
{"name", "options"} objects; leaving it out uses the preset's widgets (or
none). "screen" plays only that one of the activity's screens (e.g. "forecast").
A "duration" of null (or leaving it out) means play until replaced.
If config "manager" -> "api_token" is set, send "Authorization: Bearer <token>".
"""
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_BODY = 64 * 1024


def code_version():
    """Short git commit of the loaded code, plus '+dirty' if there are uncommitted changes."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # The service runs as root but the repo belongs to the user; without safe.directory,
    # git refuses to read it ("dubious ownership"). Scoped to this one repo and command.
    git = ["git", "-c", f"safe.directory={root}", "-C", root]
    try:
        rev = subprocess.run(git + ["rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(git + ["status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return (rev + ("+dirty" if dirty else "")) or None
    except (OSError, subprocess.SubprocessError):
        return None


VERSION = code_version()  # captured at startup: the code this process actually loaded


def options_info(manager, cls):
    defaults = cls.defaults(manager.config)
    return {opt: {"type": typ.__name__, "help": help_text, "default": defaults.get(opt)}
            for opt, (typ, help_text) in cls.OPTIONS.items()}


def activities_info(manager):
    info = {name: {"fps": cls.FPS or manager.default_fps, "options": options_info(manager, cls)}
            for name, cls in sorted(manager.registry.items())}
    for name, preset in sorted(manager.presets.items()):
        info[name] = {"preset": preset}
    return info


def widgets_info(manager):
    return {name: {"options": options_info(manager, cls)} for name, cls in sorted(manager.widget_registry.items())}


def make_handler(manager, store, token):
    class Handler(BaseHTTPRequestHandler):
        server_version = "pixelgrid"

        def log_message(self, fmt, *args):
            print(f"API: {self.client_address[0]} " + fmt % args, flush=True)

        def send(self, code, body=None):
            data = (json.dumps(body, indent=2) + "\n").encode() if body is not None else b""
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("request body too large")
            raw = self.rfile.read(length) if length else b""
            data = json.loads(raw) if raw.strip() else {}
            if not isinstance(data, dict):
                raise ValueError("request body must be a JSON object")
            return data

        def entry_from_body(self):
            b = self.body()
            return manager.make_entry(b.get("activity"), b.get("options"), b.get("duration"), b.get("widgets"),
                                      b.get("screen"))

        def route(self, method):
            if token and self.headers.get("Authorization") != f"Bearer {token}":
                return self.send(401, {"error": "unauthorized"})
            url = urlparse(self.path)
            parts = [p for p in url.path.split("/") if p]
            try:
                return self.dispatch(method, parts, parse_qs(url.query))
            except ValueError as e:  # includes bad JSON
                return self.send(400, {"error": str(e)})

        def dispatch(self, method, parts, query):
            if parts in ([], ["activities"]) and method == "GET":
                return self.send(200, activities_info(manager))
            if parts == ["widgets"] and method == "GET":
                return self.send(200, widgets_info(manager))
            if parts == ["activity"]:
                if method == "GET":
                    return self.send(200, manager.snapshot())
                if method == "PUT":
                    entry = self.entry_from_body()
                    manager.interject(entry)
                    return self.send(202, {"playing": entry})
            if parts == ["activity", "skip"] and method == "POST":
                manager.skip()
                return self.send(202, {"skipped": manager.snapshot().get("activity")})
            if parts == ["queue"]:
                if method == "GET":
                    return self.send(200, store.queue_list())
                if method == "POST":
                    entry = self.entry_from_body()
                    item_id = store.queue_add(entry)
                    manager.notify_queue()
                    return self.send(201, {"id": item_id, **entry})
                if method == "DELETE":
                    return self.send(200, {"removed": store.queue_clear()})
            if len(parts) == 2 and parts[0] == "queue" and method == "DELETE":
                if not parts[1].isdigit():
                    raise ValueError("queue id must be a number")
                if store.queue_remove(int(parts[1])):
                    return self.send(200, {"removed": int(parts[1])})
                return self.send(404, {"error": f"no queue item {parts[1]}"})
            if parts == ["health"] and method == "GET":
                return self.send(200, {"pid": os.getpid(), "started_at": manager.started_at,
                                       "version": VERSION, "activity": manager.snapshot().get("activity")})
            if parts == ["admin", "restart"] and method == "POST":
                manager.request_restart()
                return self.send(202, {"restarting": True, "pid": os.getpid()})
            if parts == ["history"] and method == "GET":
                try:
                    limit = int(query.get("limit", ["50"])[0])
                except ValueError:
                    raise ValueError("limit must be a number") from None
                return self.send(200, store.history_list(max(1, min(500, limit))))
            return self.send(404, {"error": f"no route for {method} /{'/'.join(parts)}"})

        def do_GET(self):
            self.route("GET")

        def do_PUT(self):
            self.route("PUT")

        def do_POST(self):
            self.route("POST")

        def do_DELETE(self):
            self.route("DELETE")

    return Handler


def start_api(manager, store, host, port, token=None):
    server = ThreadingHTTPServer((host, port), make_handler(manager, store, token))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="api", daemon=True).start()
    print(f"API: listening on http://{host}:{port}" + (" (token required)" if token else ""), flush=True)
    return server
