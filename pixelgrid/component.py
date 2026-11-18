"""Component: the shared base for display modes (State) and overlays (Widget).

Lifecycle, driven by the DisplayManager on the frame-loop thread:

    enter()          once, when it becomes active
    update(dt)       every frame: advance by dt seconds
    draw(canvas)     every frame
    exit()           once, when it is replaced or the display stops

Class attributes:
    name      used in config.json, the CLI and the API
    SECTION   config section holding its defaults: "states" or "widgets"
    OPTIONS   {option: (type, help)}; default values live in config.json
    INHERITS  names of *modes* whose config defaults are reused, e.g. ("clock",).
              Matching options come from states.<parent> first, then this
              component's own section on top.
    FPS       frame rate a mode needs, or None for the display default

Outside data (weather, stocks) should be fetched with self.every(seconds, fn)
so slow network calls never stall the display.
"""
import threading
import traceback


class Component:
    name = ""
    SECTION = ""
    OPTIONS = {}
    INHERITS = ()
    FPS = None

    @classmethod
    def defaults(cls, config):
        """Config defaults for this component, from the full config dict."""
        merged = {}
        for parent in cls.INHERITS:
            merged.update({k: v for k, v in config.get("states", {}).get(parent, {}).items() if k in cls.OPTIONS})
        merged.update(config.get(cls.SECTION, {}).get(cls.name, {}))
        return merged

    def __init__(self, options):
        """Check and store options. Must stay cheap with no side effects: the manager
        also builds throwaway instances just to validate API requests."""
        missing = sorted(set(self.OPTIONS) - set(options))
        unknown = sorted(set(options) - set(self.OPTIONS))
        if missing:
            raise ValueError(f"{self.name}: missing option(s) {', '.join(missing)} (add them to config.json)")
        if unknown:
            raise ValueError(f"{self.name}: unknown option(s) {', '.join(unknown)}")
        try:
            self.opts = {k: self.OPTIONS[k][0](v) for k, v in options.items()}
        except (TypeError, ValueError) as e:
            raise ValueError(f"{self.name}: bad option value: {e}") from None
        self._halt = threading.Event()
        self.validate()

    def validate(self):
        """Raise ValueError for bad option combinations."""

    def every(self, seconds, fn):
        """Call fn() now and then every `seconds` in a background thread, until this exits.
        Errors are logged and retried on the next tick. Share results with the frame loop by
        assigning attributes (a single assignment is atomic in Python)."""
        def loop():
            while True:
                try:
                    fn()
                except Exception:
                    print(f"{self.name}: background task failed:", flush=True)
                    traceback.print_exc()
                if self._halt.wait(seconds):
                    return
        threading.Thread(target=loop, name=f"{self.name}-worker", daemon=True).start()

    def stop_workers(self):
        self._halt.set()

    def enter(self):
        pass

    def update(self, dt):
        pass

    def draw(self, canvas):
        raise NotImplementedError

    def exit(self):
        pass
