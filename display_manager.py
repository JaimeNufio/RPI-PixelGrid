"""DisplayManager: owns the matrix, runs one mode at a time, and decides what plays next.

Scheduling (service mode):
  - Each item plays for its duration, or indefinitely if it has none.
  - An indefinite item gives way as soon as something is waiting in the queue.
  - When an item ends, the next queue item plays; if the queue is empty, a
    random mode from config "manager" -> "random_modes" plays.
  - interject() (HTTP PUT /state) takes over immediately; when it ends, the
    queue resumes.

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

from matrix_setup import build_matrix
from states import STATES


class DisplayManager:
    def __init__(self, config, store=None, registry=STATES):
        self.config = config
        self.store = store
        self.registry = registry
        display = config["display"]
        self.default_fps = float(display["fps"])
        self.bad_pixels = ([tuple(p) for p in display.get("bad_pixels", [])]
                           if display.get("mask_bad_pixels", True) else [])
        self.matrix = build_matrix(SimpleNamespace(brightness=display["brightness"],
                                                   mapping=display["mapping"],
                                                   slowdown=display["slowdown"]))
        self.canvas = self.matrix.CreateFrameCanvas()
        self.state = None
        self.current = None              # what's playing, for snapshot(); guarded by _lock
        self._lock = threading.Lock()
        self._commands = queue.Queue()   # from API threads to the frame loop
        self.queue_waiting = threading.Event()
        self._stop = False
        self._last_random = None

    # ---- requests (validated anywhere, executed on the frame loop) ----

    def make_entry(self, name, options=None, duration=None):
        """Validate a request to play a mode. Returns {"state", "options", "duration"}.
        options holds only overrides; config defaults are merged in at play time."""
        if not name:
            raise ValueError("'state' is required")
        if name not in self.registry:
            raise ValueError(f"unknown state {name!r}; available: {', '.join(sorted(self.registry))}")
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
        self.registry[name](self._merged(name, options))  # raises ValueError if invalid
        return {"state": name, "options": options, "duration": duration}

    def _merged(self, name, overrides):
        return {**self.config["states"].get(name, {}), **overrides}

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

    # ---- switching (frame-loop thread only) ----

    def _switch(self, entry, source, reason):
        name = entry["state"]
        try:
            new = self.registry[name](self._merged(name, entry["options"]))
        except (KeyError, ValueError) as e:
            print(f"Manager: can't play {name!r}: {e}", flush=True)
            return False
        self._end_current(reason)
        try:
            new.enter()
        except Exception:
            print(f"Manager: {name} failed to start:", flush=True)
            traceback.print_exc()
            new.stop_workers()
            return False
        self.state = new
        duration = entry["duration"]
        history_id = self.store.history_start(name, entry["options"], duration, source) if self.store else None
        t0 = time.monotonic()
        with self._lock:
            self.current = {
                "state": name, "options": entry["options"], "duration": duration, "source": source,
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "ends_at": (datetime.now() + timedelta(seconds=duration)).isoformat(timespec="seconds")
                           if duration is not None else None,
                "_t0": t0, "_history": history_id,
            }
        print(f"Manager: now playing {name} ({source}, "
              + ("until replaced" if duration is None else f"{duration:g}s") + ")", flush=True)
        return True

    def _end_current(self, reason):
        if self.state is None:
            return
        try:
            self.state.exit()
        except Exception:
            traceback.print_exc()
        self.state.stop_workers()
        if self.store and self.current and self.current["_history"] is not None:
            self.store.history_end(self.current["_history"], reason)
        self.state = None
        with self._lock:
            self.current = None

    def _next(self, reason):
        """Play the next queue item, or a random mode if the queue is empty."""
        while self.store and (item := self.store.queue_pop()) is not None:
            if self._switch(item, "queue", reason):
                return
        self._play_random(reason)

    def _play_random(self, reason):
        mcfg = self.config.get("manager", {})
        choices = [m for m in mcfg.get("random_modes", sorted(self.registry)) if m in self.registry]
        choices = choices or sorted(self.registry)
        if len(choices) > 1 and self._last_random in choices:
            choices.remove(self._last_random)  # avoid repeating the same mode back to back
        name = random.choice(choices)
        self._last_random = name
        entry = {"state": name, "options": {}, "duration": mcfg.get("random_duration")}
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
        """Run forever: queue first, else a random mode; obey interjections and skips."""
        self._next("startup")
        self._loop(service=True)

    def run_once(self, entry, duration=None):
        """Play one entry for `duration` seconds (None = until Ctrl+C / SIGTERM)."""
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
                    self.canvas.Clear()
                    self.state.draw(self.canvas)
                except Exception:
                    if not service:
                        raise
                    print(f"Manager: {self.current and self.current['state']} crashed; moving on:", flush=True)
                    traceback.print_exc()
                    self.canvas.Clear()
                    self._end_current("error")
                for x, y in self.bad_pixels:
                    self.canvas.SetPixel(x, y, 0, 0, 0)
                self.canvas = self.matrix.SwapOnVSync(self.canvas)
                elapsed = time.monotonic() - start
                if elapsed < frame_time:
                    time.sleep(frame_time - elapsed)
        except KeyboardInterrupt:
            pass
        finally:
            self._end_current("shutdown")
            self.matrix.Clear()
            print("Display: stopped.", flush=True)
