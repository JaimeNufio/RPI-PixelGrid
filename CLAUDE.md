# Pixelgrid

An always-on LED display: a Raspberry Pi 4 (8 GB, Debian 13 "trixie") drives an
Adafruit 64x64 RGB matrix through the Adafruit RGB Matrix HAT. A manager
service rotates through display modes (`snow`, `clock`) with optional overlay widgets
(`clock`) and named presets (`snow-clock` = snow + clock widget), a persistent queue,
on-demand interjections over HTTP, and a SQLite play history.

Planned modes: weather/temperature, stock ticker, Christmas/holiday animations.

## Hardware facts

- The GPIO4–GPIO18 jumper is soldered, so always use `mapping: adafruit-hat-pwm`.
- **Dead green LED at x=32, y=5** (0-indexed, top-left origin): white shows purple there.
  It's listed in `config.json` -> `display.bad_pixels`, and the manager draws it black in
  every mode. See `docs/PANEL_NOTES.md`.
- `gpio_slowdown` 4–5 works on this Pi 4.
- Onboard audio is disabled (`dtparam=audio=off`, and `snd_bcm2835` is blacklisted) because
  it conflicts with the matrix driver's PWM timer.

## Layout

Run everything from the repository root (`python -m ...`), so `pixelgrid` and `tools` import as packages.

| Path | Role |
|---|---|
| `pixelgrid/manager.py` | Service entry point (`python -m pixelgrid.manager`, run by systemd at boot): queue, random rotation, HTTP API, history |
| `pixelgrid/ctl.py` | API client for the running service, no sudo (`python -m pixelgrid.ctl status/play/skip/restart`); reads port + token from config |
| `pixelgrid/run.py` | One-off runner for testing a single mode (`python -m pixelgrid.run`); refuses to start while the service is up |
| `pixelgrid/display_manager.py` | `DisplayManager`: owns the matrix and frame loop, scheduling, bad-pixel masking, crash recovery |
| `pixelgrid/api.py` | Standard-library HTTP API (port 8080) |
| `pixelgrid/store.py` | SQLite queue + history (`data/pixelgrid.db`, WAL mode) |
| `pixelgrid/matrix.py` | Builds the `RGBMatrix` (`SIZE` = 64); falls back to `/dev/gpiomem` and software timing when not root |
| `pixelgrid/config.py` | `ROOT`, `CONFIG_PATH`, `FONT_DIR`, `load_config()`, `resolve()` (config paths are relative to the repo root) |
| `pixelgrid/states/__init__.py` | Mode registry (`STATES`); register new modes here |
| `pixelgrid/component.py` | `Component`: shared base for modes and widgets (options, config defaults + `INHERITS`, lifecycle, `every()`) |
| `pixelgrid/states/base.py` | `State(Component)`: base for modes (defaults in `states.<name>`) |
| `pixelgrid/states/snow.py` | Snow mode |
| `pixelgrid/states/clock.py` | Clock mode: time in an explicit IANA timezone (DST-safe), small AM/PM, date line; centered on visible pixels |
| `pixelgrid/states/selftest.py` | Selftest mode: solid R/G/B/W, coordinate grid, diagonal rainbow; runs at service startup; doesn't mask bad pixels (`MASK_BAD_PIXELS = False`) |
| `pixelgrid/widgets/base.py` | `Widget(Component)`: overlay drawn on top of any mode (defaults in `widgets.<name>`) |
| `pixelgrid/widgets/clock.py` | Clock widget: the clock mode's layout (inherits `states.clock`), `top` row (-1 = centered), black `outline` ring so the mode underneath never touches the text |
| `pixelgrid/widgets/__init__.py` | Widget registry (`WIDGETS`) |
| `pixelgrid/states/text.py` | BDF font renderer (`load_font`, `render`, `ink_bounds`) shared by text modes |
| `tools/rainbow_test.py`, `tools/pixel_check.py` | Standalone panel tests (`python -m tools.pixel_check solid`; solid/grid/walk/pixel/circle) |
| `fonts/` | Public-domain BDF fonts (10x20, 9x18B, 6x10, 5x7, 4x6); add more from `rpi-rgb-led-matrix/fonts/` |
| `deploy/pixelgrid.service` | systemd unit; runs `python -m pixelgrid.manager` as root |
| `deploy/setup_root.sh` | One-time root setup (apt packages, disable audio) |
| `deploy/git-hooks/post-commit` | Git hook (symlinked from `.git/hooks/post-commit`): after a commit that touches `pixelgrid/` or `fonts/`, runs `ctl restart` if the service is up |
| `docs/PANEL_NOTES.md` | Known bad pixels on this panel |
| `config.json` | Local config, **gitignored** (holds `api_token`). Template: `config.example.json` |

## Config (`config.json`)

- `display`: brightness, mapping, slowdown, default fps, `bad_pixels`.
- `manager`: `http_host`/`http_port`, `api_token` (null = no auth), `db_path`,
  `random_modes` (what plays when the queue is empty), `random_duration` (null = until replaced),
  `startup_selftest` (run the selftest mode, about 10s, every time the service starts).
- `run`: defaults for `pixelgrid.run` (`state`, `duration`; `"indefinite"` or 0 = forever).
- `states.<mode>`: default options for each mode. Every declared option must be present, either
  there or inherited: a component with `INHERITS = ("clock",)` takes matching options from
  `states.clock` first (`Component.defaults()`), so it stays in sync with that mode.
- `widgets.<widget>`: widget defaults (on top of inherited ones). `widgets.clock` sets
  `date_format: ""`, `top`, `outline`, `outline_color`.
- `presets.<name>`: `{"state", "options"?, "widgets"?}`, a named mode + widgets combination usable
  anywhere a mode name is (API, queue, `random_modes`, `pixelgrid.run --state`).

## Scheduling rules

- Each item plays for `duration` seconds, or until replaced if `duration` is null.
- An until-replaced item gives way as soon as something is in the queue.
- When an item ends: the next queue item plays, else a random mode from
  `random_modes` (never the same random mode twice in a row when there's a choice).
- `PUT /state` interjects immediately; afterwards the queue resumes. The item it
  replaced does not resume.
- At startup: the selftest first (if `manager.startup_selftest`). Then, after a requested restart
  (`ctl restart` / `POST /admin/restart`), the item that was playing resumes with its remaining time,
  but only if it was a deliberate pick (API or queue; random picks are re-chosen from the config);
  otherwise the queue first, else random. A reboot
  or `systemctl restart` does not resume.
- A mode that raises is logged, recorded in history as `error`, and skipped.

## HTTP API

If `api_token` is set, send `Authorization: Bearer <token>`.

- `GET /modes`: modes, options, config defaults
- `GET /state`: what's playing (with `remaining` seconds when timed)
- `GET /widgets`: widgets, options, config defaults (`/modes` also lists presets)
- `PUT /state` with `{"state", "options"?, "duration"?, "widgets"?}`: play now. `state` may be a
  preset. `widgets` is a list of names or `{"name", "options"}`; omitted = the preset's widgets,
  `[]` = none.
- `POST /state/skip`: move on to the next item
- `GET /queue`, `POST /queue`, `DELETE /queue`, `DELETE /queue/<id>`: manage the queue
- `GET /history?limit=N`: recent plays with `source` (random/queue/api/cli/resume) and `end_reason`
- `GET /health`: pid, start time, loaded code version (git short hash, `+dirty` if uncommitted)
- `POST /admin/restart`: clean stop + exit code 75; systemd (`Restart=on-failure`) starts a fresh
  process with the latest code and config. The current item resumes with its remaining time
  (saved in the `meta` table), and history records `restart`.

`options` holds only overrides; config defaults fill in the rest at play time.

## Adding a mode

1. Create `pixelgrid/states/<name>.py` with a `State` subclass. Set `name`, `OPTIONS = {opt: (type, help)}`,
   and optionally `FPS` (e.g. 2 for a clock). Implement `update(dt)` and `draw(canvas)`, and
   optionally `enter()`/`exit()` and `validate()` (raise `ValueError` for bad option combinations).
   To overlay something on other modes, write a widget (`pixelgrid/widgets/`, same lifecycle) and
   combine it with a mode in a preset, rather than writing a combined mode.
2. Keep `__init__` cheap with no side effects: the manager builds throwaway instances to
   validate API requests. Do setup in `enter()`.
3. Fetch network data with `self.every(seconds, fn)` (a background thread that stops on
   exit), never in `update()`/`draw()`.
4. Register it in `pixelgrid/states/__init__.py`, add its defaults under `states.<name>` in **both**
   `config.json` and `config.example.json`, and add it to `manager.random_modes` if it
   should rotate in.
5. `draw()` gets an already-cleared canvas; the manager masks bad pixels after it.
6. For text, use `pixelgrid/states/text.py` (`load_font(name).render(text)` gives pixel offsets, so you
   can measure the ink bounds and center exactly). See `pixelgrid/states/clock.py`. Fonts go in `fonts/`.

## Running

```bash
# Service (start at boot)
sudo cp deploy/pixelgrid.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now pixelgrid
systemctl status pixelgrid
journalctl -u pixelgrid -f
sudo systemctl stop pixelgrid          # required before pixelgrid.run or the tools

# Control the running service (no sudo)
.venv/bin/python -m pixelgrid.ctl status
.venv/bin/python -m pixelgrid.ctl play snow-clock            # --duration S, --widget W, --opt k=v
.venv/bin/python -m pixelgrid.ctl restart                    # load new code/config; waits until back up

# One-off test of a mode (service must be stopped)
sudo .venv/bin/python -m pixelgrid.run --state snow --duration 60 --rate 10
sudo .venv/bin/python -m pixelgrid.run --state snow-clock               # preset
sudo .venv/bin/python -m pixelgrid.run --state snow --widget clock      # any mode + widget
.venv/bin/python -m pixelgrid.run --help          # every flag with its config default
.venv/bin/python -m tools.pixel_check grid          # panel diagnostics
```

Without root, the scripts still run through `/dev/gpiomem` (the user is in the `gpio` group),
but with software timing and more flicker. Root gets hardware PWM timing. Optionally,
`sudo setcap 'cap_sys_nice=eip' /usr/bin/python3.13` lets non-root runs use real-time
priority. That permission is lost whenever apt updates python3.13; check with `getcap`.

## Working notes for Claude sessions

- Claude can't use `sudo` (it needs a password, and `!` commands have no terminal for the
  prompt). Give the user root commands to run in their own terminal. Interactive editors
  don't work through `!` either.
- Committing changes under `pixelgrid/` or `fonts/` restarts the service automatically (post-commit hook).
  Config-only or uncommitted changes don't; run `ctl restart` for those.
- After changing code or config, reload the service with `python -m pixelgrid.ctl restart` (no sudo;
  needs the service to already be running code that has `/admin/restart`). Unit-file changes still
  need `sudo systemctl daemon-reload` by the user.
- To show something on the panel while the service runs, use `pixelgrid.ctl play`, not `pixelgrid.run`.
- Only one program can drive the panel. Stop the service before running anything on the hardware.
- Test logic without the hardware by replacing `display_manager.build_matrix` with a fake
  matrix/canvas (`Clear`, `SetPixel`, `CreateFrameCanvas`, `SwapOnVSync`) and driving the
  API over HTTP on a spare port with a temporary DB. Then do a short run on the panel.
- Never print or copy the `api_token` from `config.json`.

## Fresh setup (new SD card / clone)

```bash
sudo bash deploy/setup_root.sh                            # apt deps, disable audio; reboot after
cp config.example.json config.json                        # then set api_token
ln -sf ../../deploy/git-hooks/post-commit .git/hooks/post-commit   # auto-restart after commits
python3 -m venv .venv
curl -sL https://github.com/hzeller/rpi-rgb-led-matrix/archive/refs/heads/master.tar.gz | tar xz
mv rpi-rgb-led-matrix-master rpi-rgb-led-matrix
.venv/bin/pip install pillow
# The library's Python build needs Pillow's internal Imaging.h, which isn't in its repo:
V=$(.venv/bin/python -c "import PIL; print(PIL.__version__)")
mkdir -p build-deps && curl -sL "$(curl -s https://pypi.org/pypi/pillow/$V/json | python3 -c \
  "import sys,json; print([u['url'] for u in json.load(sys.stdin)['urls'] if u['packagetype']=='sdist'][0])")" \
  | tar xz -C build-deps
CFLAGS="-I$PWD/build-deps/pillow-$V/src/libImaging" .venv/bin/pip install ./rpi-rgb-led-matrix
```
