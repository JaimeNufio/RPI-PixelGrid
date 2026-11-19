"""Rotation order from tags (pixelgrid/scheduler.py), and entries that play one screen.

    .venv/bin/python -m unittest discover tests
"""
import random
import unittest
from unittest import mock

from pixelgrid.scheduler import Rotation

ITEMS = [
    {"activity": "weather", "screen": "now", "tags": ["active"], "group": "weather"},
    {"activity": "weather", "screen": "forecast", "tags": ["active"], "group": "weather"},
    {"activity": "christmas", "screen": "snowflakes", "tags": ["active"]},
    {"activity": "christmas", "screen": "christmas-lights", "tags": ["active"]},
    {"activity": "tetris", "screen": "play-keep", "tags": ["active"]},
    {"activity": "snow-clock", "tags": ["clock"]},
    {"activity": "clock", "tags": ["clock"]},
    {"activity": "selftest"},   # untagged: benched
]
NOW, FORECAST, CLOCKS, ACTIVE_PICKS = 0, 1, {5, 6}, 4   # 4 picks: weather group, 3 singles


def take(order, n):
    return [order.next() for _ in range(n)]


class RotationTest(unittest.TestCase):
    def test_clock_between_active_picks_but_not_inside_weather(self):
        seq = take(Rotation(ITEMS, shuffle=True, rng=random.Random(1)), 200)
        for a, b in zip(seq, seq[1:]):
            self.assertFalse(a in CLOCKS and b in CLOCKS, "two clocks in a row")
            if a == NOW:
                self.assertEqual(b, FORECAST, "forecast must follow now")
            elif a not in CLOCKS and a != NOW:
                self.assertIn(b, CLOCKS, "a clock item plays after each active pick")
        self.assertNotIn(7, seq, "untagged items don't play")

    def test_every_active_item_plays_once_per_round(self):
        seq = [i for i in take(Rotation(ITEMS, shuffle=True, rng=random.Random(2)), 400)
               if i not in CLOCKS and i != FORECAST]
        for start in range(0, len(seq) - ACTIVE_PICKS + 1, ACTIVE_PICKS):
            self.assertEqual(sorted(seq[start:start + ACTIVE_PICKS]), [0, 2, 3, 4])

    def test_no_repeat_across_rounds(self):
        seq = [i for i in take(Rotation(ITEMS, shuffle=True, rng=random.Random(3)), 400) if i not in CLOCKS]
        seq = [i for i in seq if i != FORECAST]
        self.assertTrue(all(a != b for a, b in zip(seq, seq[1:])))
        clocks = [i for i in take(Rotation(ITEMS, shuffle=True, rng=random.Random(3)), 400) if i in CLOCKS]
        self.assertTrue(all(a != b for a, b in zip(clocks, clocks[1:])))

    def test_in_order_without_shuffle(self):
        self.assertEqual(take(Rotation(ITEMS, shuffle=False), 9), [0, 1, 5, 2, 6, 3, 5, 4, 6])

    def test_peek_matches_next(self):
        order = Rotation(ITEMS, shuffle=True, rng=random.Random(4))
        for _ in range(50):
            p = order.peek()
            self.assertEqual(order.peek(), p)
            self.assertEqual(order.next(), p)

    def test_untagged_rotation_plays_everything_in_turn(self):
        items = [{"activity": "a"}, {"activity": "b"}, {"activity": "c"}]
        self.assertEqual(take(Rotation(items), 6), [0, 1, 2, 0, 1, 2])

    def test_only_clocks_or_only_active(self):
        clocks = [{"activity": "a", "tags": ["clock"]}, {"activity": "b", "tags": ["clock"]}]
        self.assertEqual(take(Rotation(clocks), 4), [0, 1, 0, 1])
        active = [{"activity": "a", "tags": ["active"]}, {"activity": "b", "tags": ["active"]}]
        self.assertEqual(take(Rotation(active), 4), [0, 1, 0, 1])

    def test_nothing_playable(self):
        with self.assertRaises(ValueError):
            Rotation([{"activity": "a", "tags": ["other"]}]).peek()


class AvoidTest(unittest.TestCase):
    ACTIVE = [{"activity": n, "tags": ["active"]} for n in "abcd"]

    def test_avoided_pick_waits_for_later_in_the_round(self):
        order = Rotation(self.ACTIVE, shuffle=False)
        self.assertEqual(order.next(avoid={0}), 1)
        self.assertEqual([order.next() for _ in range(3)], [0, 2, 3])   # 0 still plays this round

    def test_borrows_from_the_next_round_when_only_a_repeat_is_left(self):
        order = Rotation(self.ACTIVE, shuffle=False)
        self.assertEqual([order.next() for _ in range(3)], [0, 1, 2])
        self.assertEqual(order.next(avoid={3}), 0)                       # borrowed
        self.assertEqual([order.next() for _ in range(4)], [3, 1, 2, 3])  # next round skips 0

    def test_repeat_only_when_nothing_else(self):
        order = Rotation([{"activity": "a", "tags": ["active"]}], shuffle=True)
        self.assertEqual(order.next(avoid={0}), 0)

    def test_peeked_pick_is_redrawn_if_it_would_repeat(self):
        order = Rotation(self.ACTIVE, shuffle=True, rng=random.Random(5))
        p = order.peek()
        self.assertNotEqual(order.next(avoid={p}), p)
        self.assertIn(p, [order.next() for _ in range(3)])                # still plays this round

    def test_group_is_not_split(self):
        order = Rotation(ITEMS, shuffle=False)
        self.assertEqual(order.next(), NOW)
        self.assertEqual(order.next(avoid={FORECAST}), FORECAST)        # mid-group: always follows


class FakeCanvas:
    def Clear(self): pass
    def SetPixel(self, *a): pass


class FakeMatrix:
    def Clear(self): pass
    def CreateFrameCanvas(self): return FakeCanvas()
    def SwapOnVSync(self, c): return c


class ScreenEntryTest(unittest.TestCase):
    def setUp(self):
        from pixelgrid import display_manager
        from pixelgrid.config import CONFIG_PATH, load_config
        path = CONFIG_PATH.with_name("config.example.json")
        with mock.patch.object(display_manager, "build_matrix", lambda *a: FakeMatrix()):
            self.dm = display_manager.DisplayManager(load_config(path))

    def test_screen_zeroes_the_others(self):
        e = self.dm.make_entry("weather", screen="forecast")
        self.assertEqual(e["options"], {"now_seconds": 0, "forecast_seconds": None})
        self.assertEqual(e["screen"], "forecast")

    def test_unknown_screen(self):
        with self.assertRaises(ValueError):
            self.dm.make_entry("weather", screen="radar")
        with self.assertRaises(ValueError):
            self.dm.make_entry("clock", screen="now")

    def test_debug_mode_shortens_rotation_items(self):
        item = {"activity": "weather", "screen": "now", "duration": 120, "tags": ["active"]}
        self.assertEqual(self.dm.rotation_entry(item)["duration"], 120)
        self.dm.config["manager"]["debug"] = True
        self.assertEqual(self.dm.rotation_entry(item)["duration"], 12)
        self.assertEqual(self.dm.make_entry("weather", duration=120)["duration"], 120)   # API plays aren't

    def test_same_screen_never_twice_in_a_row(self):
        # tetris-clock (clock) shows the same screen as tetris play-keep (active); with only
        # one other clock item, the rotation would put them back to back without avoid.
        self.dm.config["manager"]["rotation"] = [
            {"activity": "tetris", "screen": "play-keep", "duration": 1, "tags": ["active"]},
            {"activity": "snow", "duration": 1, "tags": ["active"]},
            {"activity": "tetris-clock", "duration": 1, "tags": ["clock"]},
            {"activity": "snow-clock", "duration": 1, "tags": ["clock"]},
        ]
        self.dm._order = Rotation(self.dm.rotation(), shuffle=True, rng=random.Random(9))
        shown = []
        for i in range(60):
            if i % 7 == 3:   # now and then something is played over the API
                self.dm._switch(self.dm.make_entry("snow", duration=1), "api", "interrupted")
            else:
                self.dm._play_rotation("finished")
            cur = self.dm.current["_entry"]
            shown.append((self.dm.current["source"],
                          self.dm._screens(cur.get("preset") or cur["activity"], cur.get("screen"))))
        self.dm._end_current("shutdown")
        for (_, a), (source, b) in zip(shown, shown[1:]):
            if source == "rotation":   # an API play is the user's call; the rotation never repeats
                self.assertFalse(a & b, f"{a} twice in a row")

    def test_rotation_items_start_and_draw_in_manager_order(self):
        # The manager enters the activity before its widgets, then updates and draws. An activity
        # that asks its widgets where they are must wait for its first update (christmas-lights).
        for item in self.dm.rotation():
            if item["activity"] == "weather":
                continue   # would fetch from the network
            self.assertTrue(self.dm._switch(self.dm.rotation_entry(item), "rotation", "test"), item)
            for _ in range(3):
                self.dm.activity.update(0.04)
                for w in self.dm.widgets:
                    w.update(0.04)
                self.dm.activity.draw(FakeCanvas())
                for w in self.dm.widgets:
                    w.draw(FakeCanvas())
            self.dm._end_current("test")

    def test_example_rotation_is_valid(self):
        for item in self.dm.rotation():
            e = self.dm.rotation_entry(item)
            self.assertEqual(e["tags"], item.get("tags", []))


if __name__ == "__main__":
    unittest.main()
