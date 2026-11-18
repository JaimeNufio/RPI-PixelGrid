"""DisplayManager: owns the matrix, runs one mode at a time, and decides what plays next.

Scheduling (service mode):
  - Each item plays for its duration, or indefinitely if it has none.
  - An indefinite item gives way as soon as something is waiting in the queue.
  - When an item ends, the next queue item plays; if the queue is empty, a
    random mode from config "manager" -> "random_modes" plays.
  - interject() (HTTP PUT /state) takes over immediately; when it ends, the
    queue resumes.

An entry is a mode plus optional widgets drawn on top of it:
    {"state": "snow", "options": {...}, "duration": 60,
     "widgets": [{"name": "clock", "options": {"top": 4}}], "preset": None}
A preset (config "presets") is a named mode + widgets combination, usable
anywhere a mode name is (API, queue, random_modes, run.py).

All matrix and state work happens on the frame-loop thread. Other threads
(the HTTP API) only call interject(), skip(), notify_queue() and snapshot().
"""
import queue
import random
import signal
import threading
import time
import traceback
from datetime import datetime, timedelta
from types import SimpleNamespace

from pixelgrid.matrix import build_matrix
from pixelgrid.states import STATES
from pixelgrid.widgets import WIDGETS


class DisplayManager:
    def __init__(self, config, store=None, registry=STATES, widget_registry=WIDGETS):
        self.config = config
        self.store = store
        self.registry = registry
        self.widget_registry = widget_registry
        self.presets = config.get("presets", {})
        display = config["display"]
        self.default_fps = float(display["fps"])
        self.bad_pixels = ([tuple(p) for p in display.get("bad_pixels", [])]
                           if display.get("mask_bad_pixels", True) else [])
        self.matrix = build_matrix(SimpleNamespace(brightness=display["brightness"],
                                                   mapping=display["mapping"],
                                                   slowdown=display["slowdown"]),
                                   display.get("matrix_options", {}))
        self.canvas = self.matrix.CreateFrameCanvas()
        self.state = None
        self.widgets = []
        self.current = None              # what's playing, for snapshot(); guarded by _lock
        self._lock = threading.Lock()
        self._commands = queue.Queue()   # from API threads to the frame loop
        self.queue_waiting = threading.Event()
        self._stop = False
        self._last_random = None
        self.restart_requested = False
        self._pending_resume = None  # item to resume after the startup selftest
        self.started_at = datetime.now().isoformat(timespec="seconds")

    # ---- requests (validated anywhere, executed on the frame loop) ----

    def available(self):
        return sorted(set(self.registry) | set(self.presets))

    def make_entry(self, name, options=None, duration=None, widgets=None):
        """Validate a request to play a mode or preset. Returns a normalized entry:
        {"state", "preset", "options", "duration", "widgets": [{"name", "options"}]}.
        options hold only overrides; config defaults are merged in at play time.
        widgets=None means the preset's widgets (or none); [] means no widgets."""
        if not name:
            raise ValueError("'state' is required")
        preset = None
        if name in self.presets:
            preset, p = name, self.presets[name]
            name = p.get("state")
            if name not in self.registry:
                raise ValueError(f"preset {preset!r} uses unknown state {name!r}")
            options = {**p.get("options", {}), **(options or {})}
            if widgets is None:
                widgets = p.get("widgets", [])
        elif name not in self.registry:
            raise ValueError(f"unknown state {name!r}; available: {', '.join(self.available())}")
        if options is None:
            options = {}
        if not isinstance(options, dict):
            raise ValueError("'options' must be an object")
        if duration is not None:
            try:
                duration = float(duration)
            except (TypeError, ValueError):
                raise ValueError("'duration' must be a number of seconds, or null") from None
            if duration <= 0:
                raise ValueError("'duration' must be > 0, or null to run until replaced")
        self.registry[name](self._merged(self.registry[name], options))  # raises ValueError if invalid
        widget_list = self._normalize_widgets(widgets or [])
        for w in widget_list:
            self._build_widget(w)  # raises ValueError if invalid
        return {"state": name, "preset": preset, "options": options, "duration": duration,
                "widgets": widget_list}

    def _normalize_widgets(self, widgets):
        if not isinstance(widgets, list):
            raise ValueError("'widgets' must be a list of names or {\"name\", \"options\"} objects")
        out = []
        for w in widgets:
            if isinstance(w, str):
                w = {"name": w}
            if not isinstance(w, dict) or not w.get("name"):
                raise ValueError("each widget must be a name or an object with a 'name'")
            if w["name"] not in self.widget_registry:
                raise ValueError(f"unknown widget {w['name']!r}; available: {', '.join(sorted(self.widget_registry))}")
            opts = w.get("options") or {}
            if not isinstance(opts, dict):
                raise ValueError(f"widget {w['name']!r}: 'options' must be an object")
            out.append({"name": w["name"], "options": opts})
        return out

    def _merged(self, cls, overrides):
        return {**cls.defaults(self.config), **overrides}

    def _build_widget(self, w):
        cls = self.widget_registry[w["name"]]
        return cls(self._merged(cls, w["options"]))

    def interject(self, entry):
        """Play entry right away, replacing whatever is on (thread-safe)."""
        self._commands.put(("play", entry))

    def skip(self):
        """End the current item and move on to the next (thread-safe)."""
        self._commands.put(("skip", None))

    def notify_queue(self):
        """Tell the frame loop the queue changed (thread-safe)."""
        self.queue_waiting.set()

    def snapshot(self):
        """What's playing right now (thread-safe)."""
        with self._lock:
            if self.current is None:
                return {"state": None}
            cur = {k: v for k, v in self.current.items() if not k.startswith("_")}
            if cur["duration"] is not None:
                cur["remaining"] = round(max(0.0, cur["duration"] - (time.monotonic() - self.current["_t0"])), 1)
            return cur

    def stop(self, *_):
        """Finish after the current frame (also the SIGTERM handler)."""
        self._stop = True

    def request_restart(self):
        """Stop cleanly and tell the entry point to exit with RESTART_EXIT_CODE, which
        systemd (Restart=on-failure) answers by starting a fresh process with the latest
        code and config (thread-safe)."""
        self.restart_requested = True
        self._stop = True

    # ---- switching (frame-loop thread only) ----

    def _switch(self, entry, source, reason):
        name = entry["state"]
        label = entry.get("preset") or name
        widget_list = entry.get("widgets") or []
        try:
            new = self.registry[name](self._merged(self.registry[name], entry["options"]))
            new_widgets = [self._build_widget(w) for w in widget_list]
        except (KeyError, ValueError) as e:
            print(f"Manager: can't play {label!r}: {e}", flush=True)
            return False
        self._end_current(reason)
        started = []
        try:
            for part in [new, *new_widgets]:
                part.enter()
                started.append(part)
        except Exception:
            print(f"Manager: {label} failed to start:", flush=True)
            traceback.print_exc()
            for part in started:
                part.stop_workers()
            new.stop_workers()
            return False
        self.state = new
        self.widgets = new_widgets
        duration = entry["duration"]
        history_id = (self.store.history_start(name, entry["options"], duration, source,
                                               widgets=widget_list, preset=entry.get("preset"))
                      if self.store else None)
        t0 = time.monotonic()
        with self._lock:
            self.current = {
                "state": name, "preset": entry.get("preset"), "widgets": widget_list,
                "options": entry["options"], "duration": duration, "source": source,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "ends_at": (datetime.now() + timedelta(seconds=duration)).isoformat(timespec="seconds")
                           if duration is not None else None,
                "_t0": t0, "_history": history_id, "_entry": entry,
                # where the item originally came from (survives being resumed after restarts)
                "_origin": entry.get("origin") or source,
            }
        shown = label + (f" + {', '.join(w['name'] for w in widget_list)}" if widget_list and not entry.get("preset") else "")
        print(f"Manager: now playing {shown} ({source}, "
              + ("until replaced" if duration is None else f"{duration:g}s") + ")", flush=True)
        return True

    def _end_current(self, reason):
        if self.state is None:
            return
        for part in [self.state, *self.widgets]:
            try:
                part.exit()
            except Exception:
                traceback.print_exc()
            part.stop_workers()
        self.widgets = []
        if self.store and self.current and self.current["_history"] is not None:
            self.store.history_end(self.current["_history"], reason)
        self.state = None
        with self._lock:
            self.current = None

    def _next(self, reason):
        """Play the item saved by a requested restart, else the next queue item,
        else a random mode."""
        if self._resume(reason):
            return
        while self.store and (item := self.store.queue_pop()) is not None:
            if self._switch(item, "queue", reason):
                return
        self._play_random(reason)

    def _play_random(self, reason):
        mcfg = self.config.get("manager", {})
        choices = [m for m in mcfg.get("random_modes", sorted(self.registry))
                   if m in self.registry or m in self.presets]
        choices = choices or sorted(self.registry)
        if len(choices) > 1 and self._last_random in choices:
            choices.remove(self._last_random)  # avoid repeating the same mode back to back
        name = random.choice(choices)
        self._last_random = name
        try:
            entry = self.make_entry(name, duration=mcfg.get("random_duration"))
        except ValueError as e:
            raise RuntimeError(f"random mode {name!r} is invalid: {e}") from None
        if not self._switch(entry, "random", reason):
            raise RuntimeError(f"random mode {name!r} can't start; check config.json")

    def _schedule(self):
        while True:
            try:
                cmd, arg = self._commands.get_nowait()
            except queue.Empty:
                break
            if cmd == "play":
                self._switch(arg, "api", "interrupted")
            elif cmd == "skip":
                self._next("skipped")
        if self.state is None:
            self._next("error")
            return
        cur = self.current
        if cur["duration"] is not None:
            if time.monotonic() - cur["_t0"] >= cur["duration"]:
                self._next("finished")
        elif self.queue_waiting.is_set():
            self.queue_waiting.clear()
            if self.store and self.store.queue_peek() is not None:
                self._next("replaced by queue")

    # ---- run loops ----

    def run_service(self):
        """Run forever: queue first, else a random mode; obey interjections and skips.
        Starts with the selftest (config manager.startup_selftest); after a requested
        restart, whatever was playing resumes next."""
        self._pending_resume = self.store.meta_pop("resume") if self.store else None
        if not (self.config.get("manager", {}).get("startup_selftest") and self._start_selftest()):
            self._next("startup")
        self._loop(service=True)

    def _start_selftest(self):
        cls = self.registry.get("selftest")
        if cls is None:
            return False
        try:
            entry = self.make_entry("selftest", duration=cls.total_seconds(self._merged(cls, {})))
        except (ValueError, KeyError) as e:
            print(f"Manager: skipping startup selftest ({e})", flush=True)
            return False
        return self._switch(entry, "selftest", "startup")

    def _save_resume(self):
        """Before a requested restart: remember the current item and its remaining time."""
        if not (self.store and self.current):
            return
        origin = self.current["_origin"]
        if origin in ("random", "selftest"):
            return  # not a deliberate choice: pick fresh from the (possibly updated) config
        entry = dict(self.current["_entry"])
        entry["origin"] = origin
        if entry["duration"] is not None:
            remaining = entry["duration"] - (time.monotonic() - self.current["_t0"])
            if remaining < 1:
                return  # about to end anyway; let the queue/rotation take over
            entry["duration"] = round(remaining, 1)
        self.store.meta_set("resume", entry)

    def _resume(self, reason="startup"):
        entry, self._pending_resume = self._pending_resume, None
        if not entry:
            return False
        origin = entry.get("origin")
        try:
            entry = self.make_entry(entry.get("preset") or entry["state"], entry.get("options"),
                                    entry.get("duration"), entry.get("widgets"))
            entry["origin"] = origin
        except (KeyError, ValueError) as e:
            print(f"Manager: can't resume after restart ({e}); starting fresh", flush=True)
            return False
        return self._switch(entry, "resume", reason)

    def run_once(self, entry, duration=None):
        """Play one entry for `duration` seconds (None = until Ctrl+C / SIGTERM)."""
        entry = {**entry, "duration": duration}  # so logs and snapshot() show the real run length
        if not self._switch(entry, "cli", "start"):
            raise ValueError(f"can't play {entry['state']!r}")
        self._loop(service=False, deadline=None if duration is None else time.monotonic() + duration)

    def _loop(self, service, deadline=None):
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.stop)  # systemd stop -> clean shutdown
        try:
            while not self._stop and (deadline is None or time.monotonic() < deadline):
                start = time.monotonic()
                if service:
                    self._schedule()
                fps = (self.state.FPS if self.state and self.state.FPS else None) or self.default_fps
                frame_time = 1.0 / fps
                try:
                    self.state.update(frame_time)
                    for w in self.widgets:
                        w.update(frame_time)
                    self.canvas.Clear()
                    self.state.draw(self.canvas)
                    for w in self.widgets:
                        w.draw(self.canvas)
                except Exception:
                    if not service:
                        raise
                    print(f"Manager: {self.current and self.current['state']} crashed; moving on:", flush=True)
                    traceback.print_exc()
                    self.canvas.Clear()
                    self._end_current("error")
                if not self.state or self.state.MASK_BAD_PIXELS:
                    for x, y in self.bad_pixels:
                        self.canvas.SetPixel(x, y, 0, 0, 0)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                elapsed = time.monotonic() - start
                if elapsed < frame_time:
                    time.sleep(frame_time - elapsed)
        except KeyboardInterrupt:
            pass
        finally:
            if self.restart_requested:
                self._save_resume()
            self._end_current("restart" if self.restart_requested else "shutdown")
            self.matrix.Clear()
            print("Display: stopped.", flush=True)
