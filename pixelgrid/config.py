"""Project paths and config loading, shared by the entry points."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # repository root
CONFIG_PATH = ROOT / "config.json"
FONT_DIR = ROOT / "fonts"


def load_config(path=CONFIG_PATH):
    """Load config.json, or exit with a hint if it hasn't been created yet."""
    path = Path(path)
    if not path.exists():
        sys.exit(f"{path} not found. Create it with: cp config.example.json config.json")
    with open(path) as f:
        return json.load(f)


def resolve(path):
    """Paths in config.json are relative to the repository root."""
    path = Path(path)
    return path if path.is_absolute() else ROOT / path
