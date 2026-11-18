"""HTTP API for the display manager. Standard library only; runs in background threads.

  GET    /modes           available modes, their options and config defaults
  GET    /state           what's playing now
  PUT    /state           play something right now: {"state": "snow", "options": {...}, "duration": 60}
  POST   /state/skip      end the current item and move on
  GET    /queue           queued items, in play order
  POST   /queue           add to the end of the queue (same body as PUT /state)
  DELETE /queue           clear the queue
  DELETE /queue/<id>      remove one queued item
  GET    /history?limit=N recent plays, newest first (default 50, max 500)

"options" holds only overrides; anything left out uses config.json. A
"duration" of null (or leaving it out) means play until something replaces it.
If config "manager" -> "api_token" is set, send "Authorization: Bearer <token>".
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

MAX_BODY = 64 * 1024


def modes_info(manager):
    info = {}
    for name, cls in sorted(manager.registry.items()):
        defaults = manager.config["states"].get(name, {})
        info[name] = {
            "fps": cls.FPS or manager.default_fps,
            "options": {opt: {"type": typ.__name__, "help": help_text, "default": defaults.get(opt)}
                        for opt, (typ, help_text) in cls.OPTIONS.items()},
        }
    return info


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
            return manager.make_entry(b.get("state"), b.get("options"), b.get("duration"))

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
            if parts in ([], ["modes"]) and method == "GET":
                return self.send(200, modes_info(manager))
            if parts == ["state"]:
                if method == "GET":
                    return self.send(200, manager.snapshot())
                if method == "PUT":
                    entry = self.entry_from_body()
                    manager.interject(entry)
                    return self.send(202, {"playing": entry})
            if parts == ["state", "skip"] and method == "POST":
                manager.skip()
                return self.send(202, {"skipped": manager.snapshot().get("state")})
            if parts == ["queue"]:
                if method == "GET":
                    return self.send(200, store.queue_list())
                if method == "POST":
                    entry = self.entry_from_body()
                    item_id = store.queue_add(entry["state"], entry["options"], entry["duration"])
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
