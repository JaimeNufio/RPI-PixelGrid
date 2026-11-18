"""SQLite storage for the display manager: the play queue and a history of what ran when.

One connection shared by the frame loop and the API threads, guarded by a lock.
Writes only happen on mode changes and queue edits, so WAL mode keeps SD-card
wear low.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS queue (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    state      TEXT NOT NULL,
    options    TEXT NOT NULL DEFAULT '{}',
    duration   REAL,                      -- seconds; NULL = until replaced
    widgets    TEXT NOT NULL DEFAULT '[]', -- [{"name", "options"}] drawn over the mode
    preset     TEXT,                      -- preset name it came from, if any
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    state      TEXT NOT NULL,
    options    TEXT NOT NULL DEFAULT '{}',
    duration   REAL,
    widgets    TEXT NOT NULL DEFAULT '[]',
    preset     TEXT,
    source     TEXT NOT NULL,             -- random, queue, api, cli, resume
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    end_reason TEXT                       -- finished, skipped, interrupted, replaced by queue, error, shutdown
);
CREATE INDEX IF NOT EXISTS history_started ON history(started_at);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL                   -- JSON
);
"""


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self._migrate()
        # Anything still "running" is from a run that didn't shut down cleanly.
        self.conn.execute("UPDATE history SET ended_at = ?, end_reason = 'unclean shutdown' "
                          "WHERE ended_at IS NULL", (now_iso(),))
        self._match_owner(path)

    def _migrate(self):
        """Add columns introduced after a database was first created."""
        for table in ("queue", "history"):
            have = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if "widgets" not in have:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN widgets TEXT NOT NULL DEFAULT '[]'")
            if "preset" not in have:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN preset TEXT")

    @staticmethod
    def _match_owner(path):
        """When running as root (the service), give the DB files to whoever owns the data
        directory, so non-root tools can still open them."""
        if os.geteuid() != 0:
            return
        st = path.parent.stat()
        for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            if p.exists():
                os.chown(p, st.st_uid, st.st_gid)

    @staticmethod
    def _entry(row):
        d = dict(row)
        d["options"] = json.loads(d["options"])
        d["widgets"] = json.loads(d.get("widgets") or "[]")
        return d

    # ---- queue ----

    def queue_add(self, entry):
        """Append an entry from DisplayManager.make_entry()."""
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO queue (state, options, duration, widgets, preset, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (entry["state"], json.dumps(entry["options"]), entry["duration"],
                 json.dumps(entry.get("widgets") or []), entry.get("preset"), now_iso()))
            return cur.lastrowid

    def queue_list(self):
        with self.lock:
            return [self._entry(r) for r in self.conn.execute("SELECT * FROM queue ORDER BY id")]

    def queue_peek(self):
        with self.lock:
            row = self.conn.execute("SELECT * FROM queue ORDER BY id LIMIT 1").fetchone()
            return self._entry(row) if row else None

    def queue_pop(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                row = self.conn.execute("SELECT * FROM queue ORDER BY id LIMIT 1").fetchone()
                if row:
                    self.conn.execute("DELETE FROM queue WHERE id = ?", (row["id"],))
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise
            return self._entry(row) if row else None

    def queue_remove(self, item_id):
        with self.lock:
            return self.conn.execute("DELETE FROM queue WHERE id = ?", (item_id,)).rowcount > 0

    def queue_clear(self):
        with self.lock:
            return self.conn.execute("DELETE FROM queue").rowcount

    # ---- history ----

    def history_start(self, state, options, duration, source, widgets=(), preset=None):
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO history (state, options, duration, widgets, preset, source, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (state, json.dumps(options), duration, json.dumps(list(widgets)), preset, source, now_iso()))
            return cur.lastrowid

    def history_end(self, history_id, reason):
        with self.lock:
            self.conn.execute("UPDATE history SET ended_at = ?, end_reason = ? WHERE id = ?",
                              (now_iso(), reason, history_id))

    def history_list(self, limit=50):
        with self.lock:
            return [self._entry(r) for r in
                    self.conn.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,))]

    # ---- small persistent values (e.g. what to resume after a restart) ----

    def meta_set(self, key, value):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, json.dumps(value)))

    def meta_pop(self, key):
        """Return and delete a stored value (None if absent)."""
        with self.lock:
            row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            self.conn.execute("DELETE FROM meta WHERE key = ?", (key,))
            return json.loads(row["value"]) if row else None

    def close(self):
        with self.lock:
            self.conn.close()
