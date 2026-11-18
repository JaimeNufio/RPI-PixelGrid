"""Regenerate the activity/widget/preset reference in docs/API.md from the code.

The endpoint documentation in docs/API.md is written by hand; the part between the
BEGIN/END GENERATED markers is rebuilt here from the activity and widget registries
(OPTIONS, SCREENS) and config.example.json (defaults and presets). Never config.json:
it holds the api_token and local values.

    .venv/bin/python -m tools.api_docs           # rewrite the generated section
    .venv/bin/python -m tools.api_docs --check   # exit 1 if docs/API.md is out of date
"""
import argparse
import json
import sys

from pixelgrid.activities import ACTIVITIES
from pixelgrid.config import ROOT
from pixelgrid.widgets import WIDGETS

DOC = ROOT / "docs" / "API.md"
EXAMPLE = ROOT / "config.example.json"
BEGIN = "<!-- BEGIN GENERATED: python -m tools.api_docs -->"
END = "<!-- END GENERATED -->"


def cell(value):
    return json.dumps(value).replace("|", "\\|")


def options_table(cls, config):
    defaults = cls.defaults(config)
    rows = ["| Option | Type | Default | Description |", "|---|---|---|---|"]
    for opt, (typ, help_text) in cls.OPTIONS.items():
        rows.append(f"| `{opt}` | {typ.__name__} | `{cell(defaults.get(opt))}` | {help_text.replace('|', '/')} |")
    return rows


def generate():
    config = json.loads(EXAMPLE.read_text())
    out = [BEGIN, "", "## Activities", "",
           "Options and defaults below come from the code and `config.example.json`.", ""]
    for name, cls in sorted(ACTIVITIES.items()):
        out.append(f"### `{name}`")
        out.append("")
        doc = (sys.modules[cls.__module__].__doc__ or "").strip().splitlines()
        if doc:
            out += [doc[0], ""]
        facts = [f"frame rate: {cls.FPS or 'display default'} fps"]
        if getattr(cls, "SCREENS", ()):
            facts.append("screens: " + ", ".join(f"`{s}`" for s in cls.SCREENS)
                         + " (null `<screen>_seconds` split the play time evenly)")
        out += ["- " + f for f in facts] + [""]
        out += options_table(cls, config) + [""]
    out += ["## Widgets", "", "Overlays drawn on top of any activity (`widgets` in a request).", ""]
    for name, cls in sorted(WIDGETS.items()):
        out += [f"### `{name}`", ""] + options_table(cls, config) + [""]
    out += ["## Presets", "", "Named activity + options + widgets, usable anywhere an activity name is.", "",
            "| Preset | Activity | Options | Widgets |", "|---|---|---|---|"]
    for name, p in sorted(config.get("presets", {}).items()):
        out.append(f"| `{name}` | `{p['activity']}` | `{cell(p.get('options', {}))}` | `{cell(p.get('widgets', []))}` |")
    out += ["", END]
    return "\n".join(out)


def render(current):
    start, end = current.index(BEGIN), current.index(END) + len(END)
    return current[:start] + generate() + current[end:]


def main():
    p = argparse.ArgumentParser(description="Regenerate the generated part of docs/API.md.")
    p.add_argument("--check", action="store_true", help="exit 1 if docs/API.md is out of date")
    args = p.parse_args()
    current = DOC.read_text()
    updated = render(current)
    if args.check:
        if updated != current:
            sys.exit("docs/API.md is out of date; run: .venv/bin/python -m tools.api_docs")
        return
    DOC.write_text(updated)
    print("docs/API.md " + ("updated" if updated != current else "already up to date"))


if __name__ == "__main__":
    main()
