# Pixelgrid

An always-on LED display: a Raspberry Pi 4 (8 GB, Debian 13 "trixie") drives an
Adafruit 64x64 RGB matrix through the Adafruit RGB Matrix HAT. A manager
service rotates through display modes (`snow`, `clock`), with a
persistent queue, on-demand interjections over HTTP, and a SQLite play history.

Planned modes: weather/temperature, stock ticker, Christmas/holiday animations.

## Hardware facts

- The GPIO4–GPIO18 jumper is soldered, so always use `mapping: adafruit-hat-pwm`.
- **Dead green LED at x=32, y=5** (0-indexed, top-left origin): white shows purple there.
  It's listed in `config.json` -> `display.bad_pixels`, and the manager draws it black in
  every mode. See `PANEL_NOTES.md`.
- `gpio_slowdown` 4–5 works on this Pi 4.
- Onboard audio is disabled (`dtparam=audio=off`, and `snd_bcm2835` is blacklisted) because
  it conflicts with the matrix driver's PWM timer.

## Layout

| File | Role |
|---|---|
| `manager.py` | Service entry point (run by systemd at boot): queue, random rotation, HTTP API, history |
| `display_manager.py` | `DisplayManager`: owns the matrix and frame loop, scheduling, bad-pixel masking, crash recovery |
| `api.py` | Standard-library HTTP API (port 8080) |
| `store.py` | SQLite queue + history (`data/pixelgrid.db`, WAL mode) |
| `states/base.py` | `State` base class for every mode |
| `states/snow.py` | Snow mode |
| `states/clock.py` | Clock mode: HH:MM in an explicit IANA timezone (DST-safe), centered on its visible pixels |
| `states/text.py` | BDF font renderer (`load_font`, `render`, `ink_bounds`) shared by text modes |
| `fonts/` | Public-domain BDF fonts copied from the library (10x20, 9x18B, 6x10); add more from `rpi-rgb-led-matrix/fonts/` |
| `states/__init__.py` | Mode registry (`STATES`); register new modes here |
| `run.py` | One-off runner for testing a single mode; refuses to start while the service is up |
| `snowfall.py` | Old shortcut for `run.py --state snow` |
| `matrix_setup.py` | Builds the `RGBMatrix`; falls back to `/dev/gpiomem` and software timing when not root |
| `rainbow_test.py`, `pixel_check.py` | Standalone panel tests (rainbow; solid/grid/walk/pixel/circle diagnostics) |
| `config.json` | Local config, **gitignored** (holds `api_token`). Template: `config.example.json` |
| `pixelgrid.service` | systemd unit; runs `manager.py` as root |
| `setup_root.sh` | One-time root setup (apt packages, disable audio) |

## Config (`config.json`)

- `display`: brightness, mapping, slowdown, default fps, `bad_pixels`.
- `manager`: `http_host`/`http_port`, `api_token` (null = no auth), `db_path`,
  `random_modes` (what plays when the queue is empty), `random_duration` (null = until replaced).
- `run`: defaults for `run.py` (`state`, `duration`; `"indefinite"` or 0 = forever).
- `states.<mode>`: default options for each mode. Every option a mode declares must be present.

## Scheduling rules

- Each item plays for `duration` seconds, or until replaced if `duration` is null.
- An until-replaced item gives way as soon as something is in the queue.
- When an item ends: the next queue item plays, else a random mode from
  `random_modes` (never the same random mode twice in a row when there's a choice).
- `PUT /state` interjects immediately; afterwards the queue resumes. The item it
  replaced does not resume.
- At startup: the queue first, else random.
- A mode that raises is logged, recorded in history as `error`, and skipped.

## HTTP API

If `api_token` is set, send `Authorization: Bearer <token>`.

- `GET /modes`: modes, options, config defaults
- `GET /state`: what's playing (with `remaining` seconds when timed)
- `PUT /state` with `{"state", "options"?, "duration"?}`: play now
- `POST /state/skip`: move on to the next item
- `GET /queue`, `POST /queue`, `DELETE /queue`, `DELETE /queue/<id>`: manage the queue
- `GET /history?limit=N`: recent plays with `source` (random/queue/api/cli) and `end_reason`

`options` holds only overrides; config defaults fill in the rest at play time.

## Adding a mode

1. Create `states/<name>.py` with a `State` subclass. Set `name`, `OPTIONS = {opt: (type, help)}`,
   and optionally `FPS` (e.g. 2 for a clock). Implement `update(dt)` and `draw(canvas)`, and
   optionally `enter()`/`exit()` and `validate()` (raise `ValueError` for bad option combinations).
2. Keep `__init__` cheap with no side effects: the manager builds throwaway instances to
   validate API requests. Do setup in `enter()`.
3. Fetch network data with `self.every(seconds, fn)` (a background thread that stops on
   exit), never in `update()`/`draw()`.
4. Register it in `states/__init__.py`, add its defaults under `states.<name>` in **both**
   `config.json` and `config.example.json`, and add it to `manager.random_modes` if it
   should rotate in.
5. `draw()` gets an already-cleared canvas; the manager masks bad pixels after it.
6. For text, use `states/text.py` (`load_font(name).render(text)` gives pixel offsets, so you
   can measure the ink bounds and center exactly). See `states/clock.py`. Fonts go in `fonts/`.

## Running

```bash
# Service (start at boot)
sudo cp pixelgrid.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now pixelgrid
systemctl status pixelgrid
journalctl -u pixelgrid -f
sudo systemctl stop pixelgrid          # required before run.py or the test scripts

# One-off test of a mode (service must be stopped)
sudo .venv/bin/python run.py --state snow --duration 60 --rate 10
.venv/bin/python run.py --help          # every flag with its config default
```

Without root, the scripts still run through `/dev/gpiomem` (the user is in the `gpio` group),
but with software timing and more flicker. Root gets hardware PWM timing. Optionally,
`sudo setcap 'cap_sys_nice=eip' /usr/bin/python3.13` lets non-root runs use real-time
priority. That permission is lost whenever apt updates python3.13; check with `getcap`.

## Working notes for Claude sessions

- Claude can't use `sudo` (it needs a password, and `!` commands have no terminal for the
  prompt). Give the user root commands to run in their own terminal. Interactive editors
  don't work through `!` either.
- Only one program can drive the panel. Stop the service before running anything on the hardware.
- Test logic without the hardware by replacing `display_manager.build_matrix` with a fake
  matrix/canvas (`Clear`, `SetPixel`, `CreateFrameCanvas`, `SwapOnVSync`) and driving the
  API over HTTP on a spare port with a temporary DB. Then do a short run on the panel.
- Never print or copy the `api_token` from `config.json`.

## Fresh setup (new SD card / clone)

```bash
sudo bash setup_root.sh                                   # apt deps, disable audio; reboot after
cp config.example.json config.json                        # then set api_token
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
