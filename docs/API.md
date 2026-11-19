# Pixelgrid HTTP API

Reference for external applications. **Keep this file current:** update the endpoint
sections by hand whenever `pixelgrid/api.py` changes, and run
`.venv/bin/python -m tools.api_docs` whenever an activity, widget, option or preset
changes (it rebuilds the reference at the bottom; `--check` tells you if it's stale).

## Basics

- Base URL: `http://<pi>:8080` (config `manager.http_host` / `http_port`).
- JSON in, JSON out (`Content-Type: application/json`). Request bodies are at most 64 KB.
- Auth: if `manager.api_token` is set, send `Authorization: Bearer <token>`, or you get
  `401 {"error": "unauthorized"}`.
- Errors: `400` (bad request: unknown activity, bad option value, bad JSON), `401`, `404`
  (unknown route or queue id), always with a body of `{"error": "<message>"}`.
- Timestamps are local time, ISO 8601 to the second (`2026-11-18T10:54:27`). Durations are seconds.

## Concepts

- **Activity**: what fills the panel (`snow`, `clock`, `weather`, ...). Listed by `GET /activities`.
- **Screen**: some activities cycle through several screens (weather: `now`, `forecast`).
  By default they split the play time evenly; options `<screen>_seconds` override that.
- **Widget**: an overlay drawn on top of any activity (e.g. `clock`).
- **Preset**: a named activity + options + widgets (e.g. `snow-clock`). Accepted anywhere an
  activity name is.
- **Item**: one play request: `{"activity", "options"?, "duration"?, "widgets"?}`.
  - `activity` (required): activity or preset name.
  - `options`: overrides only; config defaults fill in the rest. Unknown options are rejected.
  - `duration`: seconds; `null` or left out = until replaced (gives way as soon as something is queued).
  - `widgets`: list of names or `{"name", "options"}`; left out = the preset's widgets
    (none for a plain activity); `[]` = no widgets.
- **What plays when**: an interjection (`PUT /activity`) plays immediately; when an item ends,
  the next queued item plays; with an empty queue, the rotation (config `manager.rotation`)
  continues in order, cycling forever. Interjected and queued items don't advance the rotation.
  Activities that show outside data (weather) are fetched ahead of time; if the next item's data
  still isn't there when the current one ends, the current one stays up until it is (at most 20s,
  so `remaining` can sit at 0 briefly). `PUT /activity` never waits.

## Endpoints

### `GET /activities`

Every activity with its frame rate and options (type, help, current config default), plus presets.

```json
{
  "weather": {"fps": 2, "options": {"days": {"type": "int", "help": "...", "default": 3}, "...": {}}},
  "snow-clock": {"preset": {"activity": "snow", "widgets": ["clock"]}}
}
```

`GET /` is the same.

### `GET /widgets`

Every widget with its options, same shape as activities.

### `GET /activity`

What's playing now.

```json
{
  "activity": "weather",
  "preset": null,
  "widgets": [],
  "options": {},
  "duration": 120.0,
  "source": "rotation",
  "started_at": "2026-11-18T11:05:00",
  "ends_at": "2026-11-18T11:07:00",
  "remaining": 87.4
}
```

`remaining` and a non-null `ends_at` appear only when `duration` is set. `source` is one of
`rotation`, `queue`, `api`, `resume` (continued after a restart), `selftest`, `cli`.
Before anything plays: `{"activity": null}`.

### `PUT /activity`

Play an item now, replacing what's on. The replaced item does not resume (nor does an item still
waiting to resume after a restart); afterwards the queue, then the rotation, carry on.

```json
{"activity": "weather", "duration": 60, "options": {"forecast_seconds": 0}}
```

`202 {"playing": <normalized item>}`, where the normalized item is
`{"activity", "preset", "options", "duration", "widgets": [{"name", "options"}]}`.

### `POST /activity/skip`

End the current item and move on. `202 {"skipped": "<activity>"}`.

### `GET /queue`

Queued items in play order: `[{"id", "activity", "preset", "options", "duration", "widgets", "created_at"}]`.

### `POST /queue`

Append an item (same body as `PUT /activity`). `201 {"id": 12, ...item}`.

### `DELETE /queue`

Clear the queue. `200 {"removed": <count>}`.

### `DELETE /queue/<id>`

Remove one queued item. `200 {"removed": <id>}`, or `404`.

### `GET /history?limit=N`

Recent plays, newest first (default 50, max 500):
`[{"id", "activity", "preset", "options", "duration", "widgets", "source", "started_at", "ended_at", "end_reason"}]`.
`end_reason` is one of `finished`, `skipped`, `interrupted`, `replaced by queue`, `error`,
`restart`, `shutdown`, `unclean shutdown`, or `null` while still playing.

### `GET /health`

`{"pid", "started_at", "version", "activity"}`. `version` is the git short hash of the loaded code,
with `+dirty` if it had uncommitted changes.

### `POST /admin/restart`

Restart the service to load new code and config. `202 {"restarting": true, "pid": <old pid>}`.
The API is down for a few seconds (the startup selftest then plays for about 10s); poll
`GET /health` until `pid` changes. A deliberately chosen item (API or queue) resumes with its
remaining time; rotation items don't.

## Changelog

- 2026-11-19: snow options `melt_interval`, `floor`, `floor_above_widget`; clock widget options
  `colon_raise`, `digit_bounce`, `colon_bounce`, `bounce_period`, `bounce_stagger`, `bounce_every` (a ripple across the time every few seconds). `snow-clock` now puts a small clock in the bottom-right corner, in a snowbank
  between 15 and 30 rows deep that melts back a row every 5s (while it keeps snowing) once a flake
  settles in row 30.
- 2026-11-19: clock widget options `bottom`, `left`, `right` (CSS-style placement; -1 = auto).
  `PUT /activity` now also drops an item still waiting to resume after a restart. New activity
  `christmas` (screens `snowflakes`, `christmas-lights`, `christmas-tree`).
- 2026-11-18: "states"/"modes" renamed to activities: `/state` → `/activity`, `/state/skip` →
  `/activity/skip`, `/modes` → `/activities`; the `"state"` key → `"activity"` in requests,
  responses, history and `/health`. Rotation source `random` → `rotation`. Added the `weather`
  activity and screens.

<!-- BEGIN GENERATED: python -m tools.api_docs -->

## Activities

Options and defaults below come from the code and `config.example.json`.

### `christmas`

Christmas activity: holiday screens: "snowflakes", then "christmas-lights".

- frame rate: display default fps
- screens: `snowflakes`, `christmas-lights`, `christmas-tree` (null `<screen>_seconds` split the play time evenly)

| Option | Type | Default | Description |
|---|---|---|---|
| `snowflakes_seconds` | float or null | `null` | seconds on the snowflakes screen each cycle; null = share the play time evenly with other unset screens; 0 = never |
| `size` | int | `13` | snowflake width in pixels (odd, 9-21) |
| `min_per_row` | int | `3` | fewest flakes in a row |
| `max_per_row` | int | `4` | most flakes in a row (each row picks at random); a row too wide for the panel (4 x 17px) spreads out and its outer flakes are clipped by the edges |
| `spacing` | int | `20` | average rows from one row of flakes to the next |
| `speed` | float | `5` | fall speed in rows per second |
| `jitter` | int | `2` | max pixels each flake is nudged sideways from its even spot (as far as the row has room) and the gap between rows varies by |
| `y_jitter` | int | `5` | max rows each flake is nudged up/down from its row, so rows don't line up; a flake that would come too close to one below is moved up instead |
| `sway` | float | `1` | side-to-side drift in pixels while falling; 0 = straight down |
| `colors` | str | `"#ffffff,#d8ecff,#a8d4ff"` | comma-separated #rrggbb colors picked at random per flake |
| `christmas_lights_seconds` | float or null | `null` | seconds on the christmas-lights screen each cycle; null = share the play time evenly with other unset screens; 0 = never |
| `light_rows` | int | `3` | rows of lights, evenly spaced down the panel (1-4) |
| `min_lights` | int | `4` | fewest bulbs in a row (each row picks at random, spread evenly across) |
| `max_lights` | int | `6` | most bulbs in a row |
| `sag` | float | `5` | deepest the wire droops between two bulbs, in pixels (each droop is random up to this) |
| `row_sag` | float | `6` | how far the rows droop in the middle, hung from just past the panel edges (75-100% of this, the same for every row so they stay parallel) |
| `light_row_spacing` | float or null | `null` | pixels from one row of lights to the next; null = 85% of the spacing that would fill the panel |
| `wire_color` | str | `"#0e5a1c"` | wire color as #rrggbb |
| `light_colors` | str | `"#ff1a1a,#1aff3a,#1a5aff,#ffb300,#ff5a00,#c81aff"` | comma-separated #rrggbb bulb colors |
| `change_every` | float | `3` | average seconds before a bulb changes color (each bulb on its own random timer) |
| `sparkle_every` | float | `5` | average seconds between sparkles per light: a quick flash toward white with a flared glow, each light on its own random timer (christmas-lights and christmas-tree); 0 = no sparkle |
| `glow` | float | `0.15` | brightness of the halo around each bulb, 0-1 (0 = none) |
| `christmas_tree_seconds` | float or null | `null` | seconds on the christmas-tree screen each cycle; null = share the play time evenly with other unset screens; 0 = never |
| `ornaments_per_tier` | str | `"3-4,5-6,6-8"` | ornament count range for each tier, top to bottom, e.g. "3-4,5-6,6-8" (each play picks within each range); one evenly spaced strand per tier |
| `ornament_colors` | str | `"#e01a28,#ffc028,#2a5aff,#d0d0e0,#b020d0"` | comma-separated #rrggbb ornament colors |
| `garlands` | int | `4` | strands of lights wrapped around the tree (1-4); they use light_colors, change_every and glow like the christmas-lights screen |
| `tree_light_spacing` | int | `4` | pixels between lights along a strand |

### `clock`

Clock activity: the time centered on the panel, AM/PM beside it, the date along the bottom.

- frame rate: 2 fps

| Option | Type | Default | Description |
|---|---|---|---|
| `timezone` | str | `"America/New_York"` | IANA timezone, e.g. America/New_York (handles DST automatically) |
| `time_format` | str | `"%-I:%M"` | strftime format for the big time; %-I:%M = 12-hour, no leading zero |
| `ampm_format` | str | `"%p"` | strftime format shown small beside the time (%p = AM/PM); empty hides it |
| `date_format` | str | `"%a %b %-d"` | strftime format for the date line (e.g. %a %b %-d); empty hides it |
| `font` | str | `"10x20"` | BDF font for the time, from fonts/ (e.g. 10x20, 9x18B) or a .bdf path |
| `small_font` | str | `"5x7"` | BDF font for AM/PM and the date (e.g. 5x7, 4x6, 6x10) |
| `color` | str | `"#ffffff"` | time and AM/PM color as #rrggbb |
| `date_color` | str | `"#ffffff"` | date color as #rrggbb |
| `date_gap` | int | `5` | empty rows between the time and the date |
| `date_space` | int | `2` | width in pixels of a space in the date (the font's own is 5) |

### `selftest`

Self-test activity: a short panel check, run at service startup before anything else.

- frame rate: display default fps

| Option | Type | Default | Description |
|---|---|---|---|
| `color_seconds` | float | `1` | seconds for each solid color (red, green, blue, white) |
| `grid_seconds` | float | `2` | seconds for the coordinate grid (lines every 8 px, red top-left corner) |
| `rainbow_seconds` | float | `4` | seconds for the scrolling diagonal rainbow |

### `snow`

Snow activity: falling flakes that drift, land, and level out into a pile.

- frame rate: display default fps

| Option | Type | Default | Description |
|---|---|---|---|
| `rate` | float | `6` | new flakes per second |
| `speed` | float | `4` | average fall speed in rows per second |
| `drift` | float | `0.25` | chance per row that a flake drifts sideways, 0-1 |
| `max_step` | int | `1` | steepest allowed step between neighboring columns; 1 = smoothest |
| `mound` | int | `6` | starting mound height at its peak |
| `shift_at` | float | `0.15` | share of the panel the pile may cover before it sinks; 0 = melt mode |
| `shift_rows` | int | `5` | rows to sink once shift_at is reached |
| `shift_interval` | float | `2` | seconds between each row of sinking |
| `max_pile` | int | `40` | melt mode only: rows from the bottom the pile's highest point may reach before it melts back down (to the mound, on top of any floor) |
| `melt_interval` | float | `0.25` | melt mode: seconds between melting steps; each sinks the whole surface a row, keeping its shape (snow landing on it meanwhile melts too) |
| `floor` | int | `0` | rows from the bottom the snow's surface never sinks below; the mound starts on top of it and melts settle back to that; 0 = none |
| `floor_above_widget` | int or null | `null` | keep the snow's surface at least this many rows above the top of the widgets drawn over it (negative = below), so e.g. a corner clock sits in a snowbank; the mound starts on top of it and melts settle back to that; null = off |

### `tetris`

Tetris activity: a self-playing game on a 16 x 16 well of 4 x 4 px cells.

- frame rate: 30 fps
- screens: `play-keep` (null `<screen>_seconds` split the play time evenly)

| Option | Type | Default | Description |
|---|---|---|---|
| `play_keep_seconds` | float or null | `null` | seconds on the play-keep screen (full rows stay, the AI packs the board until it tops out) each cycle; null = share the play time evenly with other unset screens; 0 = never |
| `move_interval` | float | `0.08` | seconds per rotate or shift step in the spawn row |
| `drop_interval` | float | `0.04` | seconds per row while a piece falls |
| `lock_delay` | float | `0.15` | pause in seconds after a piece lands, before the next one appears |
| `lookahead` | int | `8` | how many of the best placements the AI rechecks against the next piece (0 = only look at the current piece) |
| `temperature` | float | `0` | randomness in the AI's choice: 0 = always the best placement; around 0.1-0.5 it sometimes takes a worse one |
| `misdrop_rate` | float | `0` | chance (0-1) that a piece lands one column off from the AI's choice |
| `ghost` | float | `0.2` | brightness of the landing preview while a piece moves, 0-1 (0 = none) |
| `piece_colors` | str | `"#00d8d8,#1a40ff,#ff7a00,#f0d000,#18d018,#a020f0,#f01010"` | comma-separated #rrggbb colors for the I, J, L, O, S, T, Z pieces |
| `edge` | float | `0.45` | brightness of each cell's right/bottom edge relative to its fill, 0-1 |
| `end_pause` | float | `3` | seconds the final board stays up before it wipes and a new game starts |
| `seed` | int or null | `null` | random seed for repeatable games; null = different every play |

### `weather`

Weather activity, using Open-Meteo (https://open-meteo.com, free, no API key).

- frame rate: 2 fps
- screens: `now`, `forecast` (null `<screen>_seconds` split the play time evenly)

| Option | Type | Default | Description |
|---|---|---|---|
| `latitude` | float | `40.5068` | location latitude (decimal degrees) |
| `longitude` | float | `-74.2654` | location longitude (decimal degrees) |
| `units` | str | `"fahrenheit"` | fahrenheit or celsius |
| `refresh` | int | `600` | seconds between weather fetches (Open-Meteo updates every 15 min) |
| `icon_set` | str | `"twemoji"` | main icons: pixel, twemoji, lbc |
| `icon_size` | int | `20` | main icon size in pixels |
| `font` | str | `"10x20"` | BDF font for the big temperature |
| `small_font` | str | `"4x6"` | BDF font for labels and small temperatures |
| `color` | str | `"#ffffff"` | temperature color as #rrggbb |
| `label_color` | str | `"#9a9ac0"` | label color (day names, hours, H/L) as #rrggbb |
| `demo` | float | `0` | seconds per condition when cycling through all icons with fake data; 0 = live |
| `now_seconds` | float or null | `null` | seconds on the now screen each cycle; null = share the play time evenly with other unset screens; 0 = never |
| `forecast_seconds` | float or null | `null` | seconds on the forecast screen each cycle; null = share evenly; 0 = never |
| `icon_gap` | int | `3` | pixels between the big icon and the temperature |
| `hours` | int | `2` | upcoming whole hours on the now screen (0-3) |
| `hour_icon_set` | str | `"pixel"` | icons for the hourly row: pixel, twemoji, lbc |
| `hour_icon_size` | int | `9` | hourly icon size in pixels (pixel set: 9 is native) |
| `days` | int | `3` | forecast days, starting tomorrow (1-3) |
| `forecast_icon_set` | str | `"twemoji"` | forecast screen icons: pixel, twemoji, lbc |
| `forecast_icon_size` | int | `16` | forecast screen icon size in pixels |
| `forecast_font` | str | `"5x7"` | BDF font for forecast day names and temperatures |
| `low_color` | str | `"#7080a8"` | forecast low temperature color as #rrggbb |

## Widgets

Overlays drawn on top of any activity (`widgets` in a request).

### `clock`

| Option | Type | Default | Description |
|---|---|---|---|
| `timezone` | str | `"America/New_York"` | IANA timezone, e.g. America/New_York (handles DST automatically) |
| `time_format` | str | `"%-I:%M"` | strftime format for the big time; %-I:%M = 12-hour, no leading zero |
| `ampm_format` | str | `"%p"` | strftime format shown small beside the time (%p = AM/PM); empty hides it |
| `date_format` | str | `""` | strftime format for the date line (e.g. %a %b %-d); empty hides it |
| `font` | str | `"10x20"` | BDF font for the time, from fonts/ (e.g. 10x20, 9x18B) or a .bdf path |
| `small_font` | str | `"5x7"` | BDF font for AM/PM and the date (e.g. 5x7, 4x6, 6x10) |
| `color` | str | `"#ffffff"` | time and AM/PM color as #rrggbb |
| `date_color` | str | `"#ffffff"` | date color as #rrggbb |
| `date_gap` | int | `5` | empty rows between the time and the date |
| `date_space` | int | `2` | width in pixels of a space in the date (the font's own is 5) |
| `top` | int | `8` | row of the top of the time's digits; -1 = auto (centered, unless bottom is set) |
| `bottom` | int | `-1` | rows between the clock's lowest pixel and the bottom edge; -1 = auto (wins over top) |
| `left` | int | `-1` | pixels between the left edge and the clock; -1 = auto (centered, unless right is set) |
| `right` | int | `-1` | pixels between the clock and the right edge; -1 = auto |
| `outline` | int | `1` | outline thickness in pixels around every character, 0-3 (0 = none) |
| `outline_color` | str | `"#000000"` | outline color as #rrggbb (black keeps other content off the text) |
| `digit_bounce` | int | `2` | how high (pixels) each digit of the time rides a sine wave that runs across the time; their normal place is the bottom of the wave; 0 = still |
| `colon_bounce` | int | `2` | the same for the colon(s); 0 = still |
| `colon_raise` | int | `1` | pixels the colon's resting place sits above where the font puts it |
| `bounce_period` | float | `1.0` | seconds for one bob up and down (1 = a digital clock's blink pace) |
| `bounce_every` | float | `5` | seconds between ripples: each character bobs once, then all rest until the next (in step with the clock's seconds); 0 = a continuous wave |
| `bounce_stagger` | float | `0.2` | seconds each character lags the one to its left, so the wave travels left to right (0 = all together) |

## Presets

Named activity + options + widgets, usable anywhere an activity name is.

| Preset | Activity | Options | Widgets |
|---|---|---|---|
| `snow-clock` | `snow` | `{"shift_at": 0, "max_pile": 30, "floor": 15, "melt_interval": 5}` | `[{"name": "clock", "options": {"font": "6x10", "small_font": "4x6", "bottom": 2, "right": 2}}]` |
| `tetris-clock` | `tetris` | `{}` | `[{"name": "clock", "options": {"font": "6x10", "small_font": "4x6", "top": 4, "left": 2}}]` |
| `weather-test-forecast` | `weather` | `{"demo": 3, "now_seconds": 0}` | `[]` |
| `weather-test-now` | `weather` | `{"demo": 3, "forecast_seconds": 0}` | `[]` |

<!-- END GENERATED -->
