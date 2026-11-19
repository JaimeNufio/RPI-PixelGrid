# Pixelgrid

An always-on LED display: a Raspberry Pi 4 (8 GB, Debian 13 "trixie") drives an
Adafruit 64x64 RGB matrix through the Adafruit RGB Matrix HAT. A manager
service rotates through display activities (`snow`, `clock`, `weather`, `christmas`, `tetris`) with optional overlay widgets
(`clock`) and named presets (`snow-clock` = snow + a small clock widget in the bottom-right corner), a persistent queue,
on-demand interjections over HTTP, and a SQLite play history.

Planned activities: stock ticker, more Christmas screens, more tetris screens (normal line clears, a tetris-seeking or sloppy AI).

Terms: an **activity** fills the panel (snow, clock, weather; called "states"/"modes" before
2026-11-18). An activity can have several **screens** it cycles through (weather: `now`, `forecast`;
christmas: `snowflakes`, `christmas-lights`, `christmas-tree`; tetris: `play-keep`).
A **widget** is an overlay drawn on top of any activity; a **preset** names an activity + widgets.

## Hardware facts

- The GPIO4–GPIO18 jumper is soldered, so always use `mapping: adafruit-hat-pwm`.
- **Dead green LED at x=32, y=5** (0-indexed, top-left origin): white shows purple there.
  It's listed in `config.json` -> `display.bad_pixels`, and the manager draws it black in
  every activity. See `docs/PANEL_NOTES.md`.
- `gpio_slowdown` 3 is in use (4–5 also work, but refresh more slowly).
- **Power is marginal:** a 5V/10A adapter feeds the HAT, which back-powers the Pi through the header.
  The Pi logs under-voltage about 110 times an hour, even on dark scenes, and stays throttled to 600 MHz
  (`vcgencmd get_throttled` = 0x50005). Flicker and brightness flashes trace back to this. The hardware
  fix (raise the supply to ~5.2V, run the panel's power straight from the supply, or power the Pi
  separately) is still pending. Software mitigation: `display.matrix_options` below.
- **The frame shades the top row** at some viewing angles, so white there can look blue. The snow
  activity keeps it dark (`top_margin` 1); other activities still draw there.
- Onboard audio is disabled (`dtparam=audio=off`, and `snd_bcm2835` is blacklisted) because
  it conflicts with the matrix driver's PWM timer.

## Layout

Run everything from the repository root (`python -m ...`), so `pixelgrid` and `tools` import as packages.

| Path | Role |
|---|---|
| `pixelgrid/manager.py` | Service entry point (`python -m pixelgrid.manager`, run by systemd at boot): queue, rotation, HTTP API, history |
| `pixelgrid/ctl.py` | API client for the running service, no sudo (`python -m pixelgrid.ctl status/play/skip/restart`); reads port + token from config |
| `pixelgrid/run.py` | One-off runner for testing a single activity (`python -m pixelgrid.run`); refuses to start while the service is up |
| `pixelgrid/display_manager.py` | `DisplayManager`: owns the matrix and frame loop, scheduling, bad-pixel masking, crash recovery |
| `pixelgrid/api.py` | Standard-library HTTP API (port 8080) |
| `pixelgrid/scheduler.py` | `Rotation`: rotation order from item tags (`active`, `clock`) and `group`s; `peek()`/`next()` |
| `pixelgrid/store.py` | SQLite queue + history (`data/pixelgrid.db`, WAL mode) |
| `pixelgrid/matrix.py` | Builds the `RGBMatrix` (`SIZE` = 64); falls back to `/dev/gpiomem` and software timing when not root |
| `pixelgrid/config.py` | `ROOT`, `CONFIG_PATH`, `FONT_DIR`, `load_config()`, `resolve()` (config paths are relative to the repo root) |
| `pixelgrid/activities/__init__.py` | Activity registry (`ACTIVITIES`); register new activities here |
| `pixelgrid/component.py` | `Component`: shared base for activities and widgets (options, config defaults + `INHERITS`, lifecycle, `every()`) |
| `pixelgrid/activities/base.py` | `Activity(Component)`: base for activities (defaults in `activities.<name>`) |
| `pixelgrid/activities/snow.py` | Snow activity: shift mode (`shift_at`: sink rows at a coverage share) or melt mode (`shift_at` 0: melt back down when the pile's highest point reaches `max_pile` rows); `floor` (rows the surface never sinks below) or `floor_above_widget` (rows above the widgets' top); the `mound` sits on top of the floor so it's never flat; `fill_air()` starts each play with flakes already at random heights (back-dated spawns); `top_margin` rows at the top stay dark (no flakes drawn, pile capped below) |
| `pixelgrid/activities/clock.py` | Clock activity: time in an explicit IANA timezone (DST-safe), small AM/PM, date line; centered on visible pixels |
| `pixelgrid/activities/selftest.py` | Selftest activity: solid R/G/B/W, coordinate grid, diagonal rainbow; runs at service startup; doesn't mask bad pixels (`MASK_BAD_PIXELS = False`) |
| `pixelgrid/activities/weather.py` | Weather activity (Open-Meteo, no key): `now` screen (icon + temp, today's H/L, next `hours` hours) alternating with `forecast` screen (next `days` days); `demo` cycles fake data |
| `pixelgrid/activities/christmas.py` | Christmas activity: `snowflakes` screen (random 8-fold symmetric star flakes, 13px; `make_flake()` rejects bare, clumped or square/round-outlined patterns; rows of 3-4 mirrored around the center, each flake scattered up/down by `y_jitter`; `clear_of_below()` moves a new flake up if it could touch one below, so flakes never touch); `christmas-lights` screen (`light_rows` (2) rows of 5x8 bulbs, `min_lights`-`max_lights` (3-4) per row at random, on a 3px green wire; rows hang parallel in one shared curve (`row_sag`), `light_row_spacing` apart (default 85% of filling the panel), and droop again a random depth between bulbs (`sag`); each bulb fades to a new color on its own random timer, never matching its neighbors; block centered on the bulbs, not the dim wire); `christmas-tree` screen (3-tier fir mirrored around the center, star always `TREE_TOP_MARGIN` (3) rows below the top, trunk, snow; per tier: light strand(s) then an ornament strand lowest (count per tier from `ornaments_per_tier` ranges, strand moves down until they fit, evenly spaced, mirrored); lights change colors like christmas-lights, greens skipped). Both light screens sparkle: each light flashes toward white on its own timer (`sparkle_every`) |
| `pixelgrid/activities/tetris.py` | Tetris activity: a self-playing game on a 16x16 well of 4x4 px cells (3x3 fill + darker right/bottom `edge`). `play-keep` screen: full rows are never cleared (they glint and stay); the `packer` AI packs the board until a piece can't spawn, then the board holds `end_pause` s, wipes top-down and a new game starts (~1 min per game, ~90% full). Pieces rotate + shift in the spawn row (`move_interval`), then drop (`drop_interval`); dim `ghost` at the landing spot. The AI thinks one piece ahead, `THINK_BUDGET` (8ms) per frame, so it never stalls a frame. `SCREEN_RULES` maps screen -> (personality, clear rows?) |
| `pixelgrid/tetris/` | Pure tetris logic, no display code: `game.py` (bit-packed board, SRS rotation states, 7-bag, `Well.legal_moves`/`simulate`, `Game`), `agent.py` (El-Tetris features, weighted search with `lookahead` beam, `temperature`, `misdrop_rate`, `PERSONALITIES`) |
| `pixelgrid/activities/weather_icons.py` | Icon sets: `pixel` (hand-drawn 9x9, in code), `twemoji` (downscaled), `lbc` (animated 16x16/8x8); WMO code -> condition |
| `assets/icons/` | Icon images + licenses (Twemoji CC-BY 4.0, LoveBootCaptain MIT); see its README |
| `pixelgrid/widgets/base.py` | `Widget(Component)`: overlay drawn on top of any activity (defaults in `widgets.<name>`) |
| `pixelgrid/widgets/clock.py` | Clock widget: the clock activity's layout (inherits `activities.clock`), placed CSS-style with `top`/`bottom`/`left`/`right` (-1 = auto/centered; bottom wins over top, left over right), black `outline` ring so the activity underneath never touches the text; the time's characters ride a sine wave (`digit_bounce`/`colon_bounce` px, `bounce_period`, `bounce_stagger`; one ripple every `bounce_every` s, default 5); list it more than once for several clocks |
| `pixelgrid/widgets/__init__.py` | Widget registry (`WIDGETS`) |
| `pixelgrid/activities/text.py` | BDF font renderer (`load_font`, `render`, `ink_bounds`) shared by text activities |
| `tools/api_docs.py` | Regenerates the reference section of `docs/API.md` from the code + `config.example.json` (`--check` = verify) |
| `tools/tetris_sim.py` | Headless tetris games for tuning AI weights (`python -m tools.tetris_sim --games 20 --weights holes=-12`): fill %, holes, lines, decision time |
| `tests/` | Unit tests (`unittest`, no pytest): `.venv/bin/python -m unittest discover tests` |
| `tools/rainbow_test.py`, `tools/pixel_check.py` | Standalone panel tests (`python -m tools.pixel_check solid`; solid/grid/walk/pixel/circle) |
| `fonts/` | Public-domain BDF fonts (10x20, 9x18B, 6x10, 5x7, 4x6); add more from `rpi-rgb-led-matrix/fonts/` |
| `deploy/pixelgrid.service` | systemd unit; runs `python -m pixelgrid.manager` as root |
| `deploy/setup_root.sh` | One-time root setup (apt packages, disable audio) |
| `deploy/git-hooks/post-commit` | Git hook (symlinked from `.git/hooks/post-commit`): after a commit that touches `pixelgrid/` or `fonts/`, runs `ctl restart` if the service is up |
| `docs/PANEL_NOTES.md` | Known bad pixels on this panel |
| `docs/API.md` | HTTP API reference for external apps; activity/widget/preset tables generated by `tools/api_docs.py` |
| `config.json` | Local config, **gitignored** (holds `api_token`). Template: `config.example.json` |

## Config (`config.json`)

- `display`: brightness, mapping, slowdown, default fps, `bad_pixels`, and `matrix_options`: library
  timing settings passed to `RGBMatrixOptions` (`limit_refresh_rate_hz`, `pwm_bits`, `pwm_lsb_nanoseconds`,
  `pwm_dither_bits`, `show_refresh_rate`; see `pixelgrid/matrix.py`). Tuned on 2026-11-18 by measuring
  with `show_refresh_rate`: the defaults (11-bit, slowdown 5) gave ~98 Hz, varying 80–135. Now
  `pwm_bits` 8 + slowdown 3 reach ~122 Hz (p1 107), capped at a steady 100 Hz. To re-measure, set
  `show_refresh_rate: true`, run `ctl restart`, read `journalctl -u pixelgrid --all -o cat`
  (`--all` is needed because the readout contains backspaces), then turn it off; it floods the journal.
- `manager`: `http_host`/`http_port`, `api_token` (null = no auth), `db_path`,
  `rotation` (what plays when the queue is empty: a list of `{"activity", "duration"?, "options"?, "widgets"?,
  "screen"?, "tags"?, "group"?}` or bare names; order from the tags, see Scheduling rules and
  `pixelgrid/scheduler.py`). Currently: `active` = weather `now` + `forecast` (group `weather`),
  christmas `snowflakes`, `christmas-lights`, `christmas-tree`, tetris `play-keep`, 120s each;
  `clock` = `snow-clock`, `clock`, `tetris-clock`, 60s each.
  `shuffle` (true = shuffle each round, never the same item twice in a row; false = config order),
  `debug` (debug mode, read through `DisplayManager.debug_mode()`, to be tied to a hardware switch
  later: every rotation item plays for a tenth of its `duration`, same order; API/queue plays and
  the selftest keep their real length; the top-right LED (63, 0) stays bright blue as the indicator;
  never turns on an activity's fake-data `demo`; currently on in `config.json`),
  `startup_selftest` (run the selftest activity, about 10s, every time the service starts).
- `run`: defaults for `pixelgrid.run` (`activity`, `duration`; `"indefinite"` or 0 = forever).
- `activities.<activity>`: default options for each activity. Every declared option must be present, either
  there or inherited: a component with `INHERITS = ("clock",)` takes matching options from
  `activities.clock` first (`Component.defaults()`), so it stays in sync with that activity.
- `widgets.<widget>`: widget defaults (on top of inherited ones). `widgets.clock` sets
  `date_format: ""`, `top` (8), `bottom`/`left`/`right` (-1 = auto), `outline`, `outline_color`.
- `activities.weather`: `latitude`/`longitude` (set from the public IP: Perth Amboy, NJ), screen timing
  `now_seconds`/`forecast_seconds` (null = split the play time evenly, 0 = skip that screen), icon set/size per screen. Presets
  `weather-test-now` and `weather-test-forecast` step through every icon and -15..100° every 3s
  (reference only; not in the rotation or the startup selftest).
- `presets.snow-clock`: snow in melt mode between `floor` 15 and `max_pile` 30 rows from the bottom (the melt starts the moment a flake settles in row 30; the surface sinks a row every `melt_interval` 5s, keeping its shape, the top pixel of each column fading to black over each step, while it keeps snowing), plus the clock widget at
  `bottom`/`right` 2 in the 6x10 font. Activities can read their widgets' boxes
  (`Activity.widget_bounds()`, from `Widget.bounds()`); the manager sets `activity.widgets` before `enter()`.
- `presets.<name>`: `{"activity", "options"?, "widgets"?}`, a named activity + widgets combination usable
  anywhere an activity name is (API, queue, `rotation`, `pixelgrid.run --activity`).

## Scheduling rules

- Each item plays for `duration` seconds, or until replaced if `duration` is null.
- An until-replaced item gives way as soon as something is in the queue.
- Rotation order (`pixelgrid/scheduler.py`): items tagged `active` each play once per round before
  any repeats; one `clock`-tagged item plays between active picks (clock items take turns the same
  way); items with the same `group` play back to back in config order with no clock between, and
  count as one pick. Untagged items don't play (if no item has tags, all play in turn). The rotation
  never shows the same screen twice in a row (same activity + screen, so `tetris-clock` repeats
  `play-keep` and `snow-clock` repeats `snow`), even after an API/queue play: the manager passes
  `_avoid()` to `peek`/`next`, and the pick waits for later in its round (or one is borrowed early). An item's
  `screen` plays just that screen (`make_entry(screen=)` zeroes the others' `<screen>_seconds`).
- When an item ends: the next queue item plays, else the next `rotation` item. If that item's
  data isn't loaded yet (`Activity.ready()`), the current item stays up until it is, at most 20s. Interjected and
  queued items don't advance the rotation; it carries on where it left off.
- `PUT /activity` interjects immediately; afterwards the queue resumes. The item it
  replaced does not resume, and neither does an item still waiting to resume after a restart.
- At startup: the selftest first (if `manager.startup_selftest`). Then, after a requested restart
  (`ctl restart` / `POST /admin/restart`), the item that was playing resumes with its remaining time,
  but only if it was a deliberate pick (API or queue; rotation items aren't resumed);
  otherwise the queue first, else the rotation from its first item. A reboot
  or `systemctl restart` does not resume.
- An activity that raises is logged, recorded in history as `error`, and skipped.

## HTTP API

If `api_token` is set, send `Authorization: Bearer <token>`.

- `GET /activities`: activities, options, config defaults
- `GET /activity`: what's playing (with `remaining` seconds when timed)
- `GET /widgets`: widgets, options, config defaults (`/activities` also lists presets)
- `PUT /activity` with `{"activity", "options"?, "duration"?, "widgets"?}`: play now. `activity` may be a
  preset. `widgets` is a list of names or `{"name", "options"}`; omitted = the preset's widgets,
  `[]` = none.
- `POST /activity/skip`: move on to the next item
- `GET /queue`, `POST /queue`, `DELETE /queue`, `DELETE /queue/<id>`: manage the queue
- `GET /history?limit=N`: recent plays with `source` (rotation/queue/api/cli/resume/selftest) and `end_reason`
- `GET /health`: pid, start time, loaded code version (git short hash, `+dirty` if uncommitted)
- `POST /admin/restart`: clean stop + exit code 75; systemd (`Restart=on-failure`) starts a fresh
  process with the latest code and config. The current item resumes with its remaining time
  (saved in the `meta` table), and history records `restart`.

`options` holds only overrides; config defaults fill in the rest at play time.

**`docs/API.md` is the reference for external apps; keep it current.** When `pixelgrid/api.py`
changes, update its endpoint sections and changelog by hand. When an activity, widget, option or
preset changes, run `.venv/bin/python -m tools.api_docs` (`--check` reports a stale file).

## Adding an activity

1. Create `pixelgrid/activities/<name>.py` with an `Activity` subclass. Set `name`, `OPTIONS = {opt: (type, help)}`,
   and optionally `FPS` (e.g. 2 for a clock). Implement `update(dt)` and `draw(canvas)`, and
   optionally `enter()`/`exit()` and `validate()` (raise `ValueError` for bad option combinations).
   To overlay something on other activities, write a widget (`pixelgrid/widgets/`, same lifecycle) and
   combine it with an activity in a preset, rather than writing a combined activity.
   For several full-panel screens, set `SCREENS = ("a", "b")`, add an `a_seconds`/`b_seconds` option
   (a `-` in a screen name becomes `_`: screen `christmas-lights` -> `christmas_lights_seconds`)
   of type `optional(float)` (from `pixelgrid.component`; null in config = split the play time evenly),
   call `self.validate_screens()` in `validate()`, and pick the screen with `self.screen_at(t)`.
2. Keep `__init__` cheap with no side effects: the manager builds throwaway instances to
   validate API requests. Do setup in `enter()`.
3. Fetch network data with `self.every(seconds, fn)` (a background thread that stops on
   exit), never in `update()`/`draw()`. Keep the data in a module-level cache that outlives one
   play, and implement the classmethods `prefetch(opts)` (fill the cache; may block) and
   `ready(opts)` (cache has data). The manager prefetches every rotation item at startup and
   the next item `PREFETCH_LEAD` (60s) before a switch, and holds the current item up to
   `READY_WAIT` (20s) while the next isn't ready, so a play never opens on a blank frame.
   See `pixelgrid/activities/weather.py`.
4. Register it in `pixelgrid/activities/__init__.py`, add its defaults under `activities.<name>` in **both**
   `config.json` and `config.example.json`, and add it to `manager.rotation` if it
   should rotate in. Then run `.venv/bin/python -m tools.api_docs` to update `docs/API.md`.
5. `draw()` gets an already-cleared canvas; the manager masks bad pixels after it.
6. For text, use `pixelgrid/activities/text.py` (`load_font(name).render(text)` gives pixel offsets, so you
   can measure the ink bounds and center exactly). See `pixelgrid/activities/clock.py`. Fonts go in `fonts/`.

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

# One-off test of an activity (service must be stopped)
sudo .venv/bin/python -m pixelgrid.run --activity snow --duration 60 --rate 10
sudo .venv/bin/python -m pixelgrid.run --activity snow-clock               # preset
sudo .venv/bin/python -m pixelgrid.run --activity snow --widget clock      # any activity + widget
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
