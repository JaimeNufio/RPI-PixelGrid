"""Base class for display states (modes): animations, clocks, weather, tickers, ..."""
import threading
import traceback


class State:
    """One display mode. The DisplayManager drives it:

        enter()          once, when the mode becomes active
        update(dt)       every frame: advance by dt seconds
        draw(canvas)     every frame: draw onto an already-cleared canvas
        exit()           once, when the mode is replaced or the display stops

    Class attributes:
        name     the mode's name, used in config.json, the CLI and the API
        OPTIONS  {option: (type, help)}; default values live in config.json
                 under "states" -> <name>, not in code
        FPS      frame rate this mode needs, or None for the display default.
                 A clock can use 2; an animation wants the default.

    Modes that need outside data (weather, stocks) should fetch it with
    self.every(seconds, fn) so slow network calls never stall the display.
    """

    name = ""
    OPTIONS = {}
    FPS = None

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
        """Call fn() now and then every `seconds` in a background thread, until this mode exits.
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
        raise NotImplementedError

    def draw(self, canvas):
        raise NotImplementedError

    def exit(self):
        pass
