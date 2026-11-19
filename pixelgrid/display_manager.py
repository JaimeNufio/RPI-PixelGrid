"""DisplayManager: owns the matrix, runs one activity at a time, and decides what plays next.

Scheduling (service):
  - Each item plays for its duration, or indefinitely if it has none.
  - An indefinite item gives way as soon as something is waiting in the queue.
  - When an item ends, the next queue item plays; if the queue is empty, the
    next item of config "manager" -> "rotation" plays. Its order comes from the items'
    tags (pixelgrid/scheduler.py): "active" items each play once per round, with one
    "clock" item between them; a "group" plays back to back. "shuffle": true shuffles
    each round, false keeps config order.
  - Debug mode (debug_mode(): config "manager" -> "debug" for now, a hardware switch later)
    plays every rotation item for a tenth of its duration (DEBUG_SCALE), same order, and
    keeps the top-right LED bright blue (DEBUG_LED) as the indicator. It never turns on
    an activity's fake-data demo (e.g. weather "demo").
  - interject() (HTTP PUT /activity) takes over immediately; when it ends, the
    queue resumes.

An entry is an activity plus optional widgets drawn on top of it:
    {"activity": "snow", "options": {...}, "duration": 60,
     "widgets": [{"name": "clock", "options": {"top": 4}}], "preset": None, "screen": None}
"screen" plays just that one of the activity's SCREENS (the others' "<screen>_seconds"
are set to 0 in options).
A preset (config "presets") is a named activity + widgets combination, usable
anywhere an activity name is (API, queue, rotation, run.py).

All matrix and activity work happens on the frame-loop thread. Other threads
(the HTTP API) only call interject(), skip(), notify_queue() and snapshot().
"""
import queue
import signal
import threading
import time
import traceback
from datetime import datetime, timedelta
from types import SimpleNamespace

from pixelgrid.matrix import build_matrix
from pixelgrid.scheduler import Rotation
from pixelgrid.activities import ACTIVITIES
from pixelgrid.widgets import WIDGETS

DEBUG_SCALE = 0.1     # debug mode: rotation items play for this share of their duration
DEBUG_LED = (63, 0, (0, 0, 255))  # ... and this pixel (top-right) stays bright blue, on top of everything
PREFETCH_LEAD = 60.0  # seconds before a timed item ends to warm the next item's data
READY_WAIT = 20.0     # longest the current item is held while the next one has no data yet


class DisplayManager:
    def __init__(self, config, store=None, registry=ACTIVITIES, widget_registry=WIDGETS):
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
        self.activity = None
        self.widgets = []
        self.current = None              # what's playing, for snapshot(); guarded by _lock
        self._lock = threading.Lock()
        self._commands = queue.Queue()   # from API threads to the frame loop
        self.queue_waiting = threading.Event()
        self._stop = False
        self._order = Rotation(self.rotation(), bool(config.get("manager", {}).get("shuffle")))
        self._prefetched_for = None      # _t0 of the item whose successor was already prefetched
        self._waiting_since = None       # when we started holding the current item for the next one's data
        self.restart_requested = False
        self._pending_resume = None  # item to resume after the startup selftest
        self.started_at = datetime.now().isoformat(timespec="seconds")

    # ---- requests (validated anywhere, executed on the frame loop) ----

    def available(self):
        return sorted(set(self.registry) | set(self.presets))

    def make_entry(self, name, options=None, duration=None, widgets=None, screen=None):
        """Validate a request to play an activity or preset. Returns a normalized entry:
        {"activity", "preset", "options", "duration", "widgets": [{"name", "options"}], "screen"}.
        options hold only overrides; config defaults are merged in at play time.
        widgets=None means the preset's widgets (or none); [] means no widgets.
        screen = play only that screen (the others are set to 0 seconds in options)."""
        if not name:
            raise ValueError("'activity' is required")
        preset = None
        if name in self.presets:
            preset, p = name, self.presets[name]
            name = p.get("activity")
            if name not in self.registry:
                raise ValueError(f"preset {preset!r} uses unknown activity {name!r}")
            options = {**p.get("options", {}), **(options or {})}
            if widgets is None:
                widgets = p.get("widgets", [])
        elif name not in self.registry:
            raise ValueError(f"unknown activity {name!r}; available: {', '.join(self.available())}")
        if options is None:
            options = {}
        if not isinstance(options, dict):
            raise ValueError("'options' must be an object")
        if screen is not None:
            cls = self.registry[name]
            if screen not in cls.SCREENS:
                raise ValueError(f"{name} has no screen {screen!r}"
                                 + (f"; screens: {', '.join(cls.SCREENS)}" if cls.SCREENS else " (it has only one)"))
            options = {**options, **{cls.screen_option(s): (None if s == screen else 0) for s in cls.SCREENS}}
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
        return {"activity": name, "preset": preset, "options": options, "duration": duration,
                "widgets": widget_list, "screen": screen}

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
                return {"activity": None}
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
        name = entry["activity"]
        label = (entry.get("preset") or name) + (f" ({entry['screen']})" if entry.get("screen") else "")
        widget_list = entry.get("widgets") or []
        try:
            new = self.registry[name](self._merged(self.registry[name], entry["options"]))
            new.duration = entry["duration"]  # lets activities with screens split the time
            new_widgets = [self._build_widget(w) for w in widget_list]
            new.widgets = new_widgets  # lets an activity work around what's drawn over it
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
        self.activity = new
        self.widgets = new_widgets
        self._waiting_since = None
        duration = entry["duration"]
        history_id = (self.store.history_start(name, entry["options"], duration, source,
                                               widgets=widget_list, preset=entry.get("preset"))
                      if self.store else None)
        t0 = time.monotonic()
        with self._lock:
            self.current = {
                "activity": name, "preset": entry.get("preset"), "screen": entry.get("screen"),
                "tags": entry.get("tags", []), "widgets": widget_list,
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
        if self.activity is None:
            return
        for part in [self.activity, *self.widgets]:
            try:
                part.exit()
            except Exception:
                traceback.print_exc()
            part.stop_workers()
        self.widgets = []
        if self.store and self.current and self.current["_history"] is not None:
            self.store.history_end(self.current["_history"], reason)
        self.activity = None
        with self._lock:
            self.current = None

    def _next(self, reason):
        """Play the item saved by a requested restart, else the next queue item,
        else the next rotation item."""
        if self._resume(reason):
            return
        while self.store and (item := self.store.queue_pop()) is not None:
            if self._switch(item, "queue", reason):
                return
        self._play_rotation(reason)

    def rotation(self):
        """Config manager.rotation as [{"activity", "duration"?, "options"?, "widgets"?, "screen"?,
        "tags"?, "group"?}]. A bare name is shorthand for {"activity": name} (plays until replaced)."""
        items = self.config.get("manager", {}).get("rotation") or ["snow-clock" if "snow-clock" in self.presets
                                                                    else sorted(self.registry)[0]]
        return [{"activity": i} if isinstance(i, str) else i for i in items]

    def debug_mode(self):
        """True while debug mode is on: config manager.debug for now (read live, so a future
        hardware switch only has to replace this)."""
        return bool(self.config.get("manager", {}).get("debug"))

    def rotation_entry(self, item):
        tags = item.get("tags") or []
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError(f"{item.get('activity')}: 'tags' must be a list of names")
        if item.get("group") is not None and not isinstance(item["group"], str):
            raise ValueError(f"{item.get('activity')}: 'group' must be a name")
        entry = self.make_entry(item.get("activity"), item.get("options"), item.get("duration"),
                                item.get("widgets"), item.get("screen"))
        entry["tags"] = tags
        if self.debug_mode() and entry["duration"] is not None:
            entry["duration"] = round(entry["duration"] * DEBUG_SCALE, 3)
        return entry

    def _screens(self, name, screen):
        """{(activity, screen)} an activity or preset shows: just `screen` if given, else all
        of the activity's screens ((activity, None) for one without SCREENS)."""
        activity = self.presets[name].get("activity") if name in self.presets else name
        cls = self.registry.get(activity)
        shown = (screen,) if screen else (cls.SCREENS if cls and cls.SCREENS else (None,))
        return {(activity, s) for s in shown}

    def _avoid(self):
        """Rotation indices that would show the same screen as what's playing now, so the
        rotation never puts the same screen up twice in a row."""
        cur = self.current and self.current.get("_entry")
        if not cur:
            return frozenset()
        now = self._screens(cur.get("preset") or cur["activity"], cur.get("screen"))
        return frozenset(i for i, item in enumerate(self.rotation())
                         if self._screens(item.get("activity"), item.get("screen")) & now)

    def _play_rotation(self, reason):
        items = self.rotation()
        index = self._order.next(self._avoid())
        item = items[index]
        try:
            entry = self.rotation_entry(item)
        except ValueError as e:
            raise RuntimeError(f"rotation item {item!r} is invalid: {e}") from None
        if not self._switch(entry, "rotation", reason):
            raise RuntimeError(f"rotation item {item!r} can't start; check config.json")

    def _schedule(self):
        while True:
            try:
                cmd, arg = self._commands.get_nowait()
            except queue.Empty:
                break
            if cmd == "play":
                # A newer deliberate choice: drop any item still waiting to resume after a
                # restart (e.g. one whose selftest this play interrupted), or it would cut in
                # ahead of the queue when this play ends.
                self._pending_resume = None
                self._switch(arg, "api", "interrupted")
            elif cmd == "skip":
                self._next("skipped")
        if self.activity is None:
            self._next("error")
            return
        cur = self.current
        if cur["duration"] is not None:
            elapsed = time.monotonic() - cur["_t0"]
            if cur["duration"] - elapsed <= PREFETCH_LEAD and self._prefetched_for != cur["_t0"]:
                self._prefetched_for = cur["_t0"]
                upcoming = self._peek_next()
                if upcoming:
                    self._prefetch_async([upcoming])
            if elapsed >= cur["duration"] and not self._hold_for_next():
                self._next("finished")
        elif self.queue_waiting.is_set():
            self.queue_waiting.clear()
            if self.store and self.store.queue_peek() is not None:
                self._next("replaced by queue")

    # ---- data warm-up (so an activity never opens on a blank "loading" frame) ----

    def _peek_next(self):
        """The entry that plays next if the current one ends now, without consuming it."""
        if self.store and (item := self.store.queue_peek()) is not None:
            return item
        try:
            return self.rotation_entry(self.rotation()[self._order.peek(self._avoid())])
        except (ValueError, AttributeError, IndexError):
            return None

    def _prefetch_async(self, entries):
        """Run each entry's Activity.prefetch() in a background thread."""
        def run():
            for e in entries:
                cls = self.registry.get(e.get("activity"))
                if cls is None:
                    continue
                try:
                    cls.prefetch(self._merged(cls, e.get("options") or {}))
                except Exception as ex:  # network down, etc.: the activity retries when it plays
                    print(f"Manager: prefetch for {e.get('preset') or e['activity']} failed: {ex}", flush=True)
        threading.Thread(target=run, name="prefetch", daemon=True).start()

    def _ready(self, entry):
        cls = self.registry.get(entry.get("activity"))
        try:
            return cls is None or cls.ready(self._merged(cls, entry.get("options") or {}))
        except Exception:
            return True

    def _hold_for_next(self):
        """True to keep the current item up a little longer because the next one has no data
        yet (at most READY_WAIT seconds, then it switches anyway)."""
        upcoming = self._peek_next()
        if upcoming is None or self._ready(upcoming):
            self._waiting_since = None
            return False
        label = upcoming.get("preset") or upcoming["activity"]
        if self._waiting_since is None:
            self._waiting_since = time.monotonic()
            print(f"Manager: {label} has no data yet; holding the current item up to {READY_WAIT:g}s", flush=True)
            self._prefetch_async([upcoming])
        if time.monotonic() - self._waiting_since < READY_WAIT:
            return True
        print(f"Manager: {label} still has no data after {READY_WAIT:g}s; switching anyway", flush=True)
        self._waiting_since = None
        return False

    # ---- run loops ----

    def run_service(self):
        """Run forever: queue first, else the rotation; obey interjections and skips.
        Starts with the selftest (config manager.startup_selftest); after a requested
        restart, whatever was playing resumes next."""
        self._pending_resume = self.store.meta_pop("resume") if self.store else None
        # Warm every rotation item's data while the selftest plays, whatever comes first.
        warm = [self._pending_resume] if self._pending_resume else []
        for item in self.rotation():
            try:
                warm.append(self.rotation_entry(item))
            except (ValueError, AttributeError):
                pass
        self._prefetch_async([e for e in warm if e.get("activity")])
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
        if origin in ("rotation", "random", "selftest"):
            return  # not a deliberate choice: start the (possibly updated) rotation fresh
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
            name = entry.get("preset") or entry.get("activity") or entry["state"]  # "state": saved before the rename
            entry = self.make_entry(name, entry.get("options"), entry.get("duration"), entry.get("widgets"))
            entry["origin"] = origin
        except (KeyError, ValueError) as e:
            print(f"Manager: can't resume after restart ({e}); starting fresh", flush=True)
            return False
        return self._switch(entry, "resume", reason)

    def run_once(self, entry, duration=None):
        """Play one entry for `duration` seconds (None = until Ctrl+C / SIGTERM)."""
        entry = {**entry, "duration": duration}  # so logs and snapshot() show the real run length
        cls = self.registry.get(entry["activity"])
        if cls:
            try:
                cls.prefetch(self._merged(cls, entry["options"]))  # first frame shows real data
            except Exception as e:
                print(f"prefetch failed ({e}); the activity will retry", flush=True)
        if not self._switch(entry, "cli", "start"):
            raise ValueError(f"can't play {entry['activity']!r}")
        self._loop(service=False, deadline=None if duration is None else time.monotonic() + duration)

    def _loop(self, service, deadline=None):
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.stop)  # systemd stop -> clean shutdown
        try:
            while not self._stop and (deadline is None or time.monotonic() < deadline):
                start = time.monotonic()
                if service:
                    self._schedule()
                fps = (self.activity.FPS if self.activity and self.activity.FPS else None) or self.default_fps
                frame_time = 1.0 / fps
                try:
                    self.activity.update(frame_time)
                    for w in self.widgets:
                        w.update(frame_time)
                    self.canvas.Clear()
                    self.activity.draw(self.canvas)
                    for w in self.widgets:
                        w.draw(self.canvas)
                except Exception:
                    if not service:
                        raise
                    print(f"Manager: {self.current and self.current['activity']} crashed; moving on:", flush=True)
                    traceback.print_exc()
                    self.canvas.Clear()
                    self._end_current("error")
                if not self.activity or self.activity.MASK_BAD_PIXELS:
                    for x, y in self.bad_pixels:
                        self.canvas.SetPixel(x, y, 0, 0, 0)
                if self.debug_mode():
                    x, y, color = DEBUG_LED
                    self.canvas.SetPixel(x, y, *color)
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
