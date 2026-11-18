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

Play an item now, replacing what's on. The replaced item does not resume; afterwards the queue,
then the rotation, carry on.

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

- 2026-11-18: "states"/"modes" renamed to activities: `/state` → `/activity`, `/state/skip` →
  `/activity/skip`, `/modes` → `/activities`; the `"state"` key → `"activity"` in requests,
  responses, history and `/health`. Rotation source `random` → `rotation`. Added the `weather`
  activity and screens.

<!-- BEGIN GENERATED: python -m tools.api_docs -->

## Activities

Options and defaults below come from the code and `config.example.json`.

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
| `max_pile` | int | `40` | melt mode only: pile height that triggers the melt |

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
| `top` | int | `8` | row of the top of the time's digits; -1 centers the clock vertically |
| `outline` | int | `1` | outline thickness in pixels around every character, 0-3 (0 = none) |
| `outline_color` | str | `"#000000"` | outline color as #rrggbb (black keeps other content off the text) |

## Presets

Named activity + options + widgets, usable anywhere an activity name is.

| Preset | Activity | Options | Widgets |
|---|---|---|---|
| `snow-clock` | `snow` | `{}` | `["clock"]` |
| `weather-test-forecast` | `weather` | `{"demo": 3, "now_seconds": 0}` | `[]` |
| `weather-test-now` | `weather` | `{"demo": 3, "forecast_seconds": 0}` | `[]` |

<!-- END GENERATED -->
