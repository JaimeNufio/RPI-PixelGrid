"""Rotation order: what plays next when the queue is empty, from the tags on config
manager.rotation items.

    active   in the cycle. Every active item plays once before any plays again.
    clock    an interlude: one clock item plays between active items (they take turns
             the same way, each once before any repeats).
    group    items with the same "group" (a field, not a tag) play back to back in
             config order, with no clock between them, and count as one pick
             (weather "now" then "forecast").

An item with neither tag is listed but doesn't play (drop "active" to bench something).
peek()/next() take `avoid`: rotation indices that would show the same screen as what's on
the panel now (the manager works these out, including after an API/queue play). A pick
in `avoid` waits for a later turn in its round; if nothing else is left in the round, an
item is borrowed from the next one, or failing that one plays again early: no repeat
beats once-per-round. Only when every candidate repeats does one play anyway.
With no tags anywhere, every item plays in turn, like before tags existed.
shuffle: true shuffles each round (a new round never starts with what just played);
false keeps config order.

    order = Rotation(items, shuffle=True)
    order.peek(avoid)   # index of the item that plays next (stays the same until next())
    order.next(avoid)   # index of the item to play now
"""
import random
from collections import deque

TAGS = ("active", "clock")


class Bag:
    """Hands out units (lists of rotation indices) one at a time, each once per round."""

    def __init__(self, units, shuffle, rng):
        self.units = units
        self.shuffle = shuffle
        self.rng = rng
        self.pending = []
        self.borrowed = set()   # drawn early from the next round, so that round skips them
        self.last = None

    def new_round(self):
        order = [k for k in range(len(self.units)) if k not in self.borrowed]
        self.borrowed = set()
        if self.shuffle:
            self.rng.shuffle(order)
            if len(order) > 1 and order[0] == self.last:
                order.append(order.pop(0))   # no back-to-back repeat across rounds
        return order

    def draw(self, avoid=frozenset()):
        """Key of the unit to play next, skipping units whose first item is in `avoid`."""
        if not self.pending:
            self.pending = self.new_round()
        ok = [k for k in self.pending if self.units[k][0] not in avoid]
        if ok:
            k = ok[0]
        else:
            # Everything left this round repeats what's on now: borrow from the next round.
            spare = [k for k in range(len(self.units))
                     if k not in self.pending and k not in self.borrowed and self.units[k][0] not in avoid]
            if spare:
                k = self.rng.choice(spare) if self.shuffle else spare[0]
                self.borrowed.add(k)
                self.last = k
                return k
            # Still nothing: play one again early rather than show the same screen twice.
            again = [k for k in range(len(self.units)) if self.units[k][0] not in avoid]
            if again:
                self.last = self.rng.choice(again) if self.shuffle else again[0]
                return self.last
            k = self.pending[0]   # nothing else to play at all: repeat
        self.pending.remove(k)
        self.last = k
        return k

    def put_back(self, k):
        """Return a drawn unit to the front of the round (it hasn't played)."""
        if k in self.borrowed:
            self.borrowed.discard(k)
        else:
            self.pending.insert(0, k)


class Rotation:
    def __init__(self, items, shuffle=False, rng=None):
        rng = rng or random.Random()
        units, clocks, groups = [], [], {}
        tagged = any(item.get("tags") for item in items)
        for i, item in enumerate(items):
            tags = set(item.get("tags") or ())
            if not tagged or ("active" in tags and "clock" not in tags):
                group = item.get("group")
                if group is None:
                    units.append([i])
                elif group in groups:
                    groups[group].append(i)
                else:
                    groups[group] = [i]
                    units.append(groups[group])
            elif "clock" in tags:
                clocks.append([i])
        self.active = Bag(units, shuffle, rng)
        self.clocks = Bag(clocks, shuffle, rng)
        self.upcoming = deque()
        self.clock_next = False   # start with an active item
        self.drawn = None         # (bag, key, clock_next before) of a unit not started yet

    def _fill(self, avoid):
        if self.upcoming:
            return
        before = self.clock_next
        if self.clocks.units and (self.clock_next or not self.active.units):
            bag, self.clock_next = self.clocks, False
        elif self.active.units:
            bag, self.clock_next = self.active, True
        else:
            raise ValueError("manager.rotation has nothing to play: tag at least one item \"active\" or \"clock\"")
        k = bag.draw(avoid)
        self.upcoming.extend(bag.units[k])
        self.drawn = (bag, k, before)

    def _redraw_if_repeat(self, avoid):
        """A unit picked earlier (e.g. at prefetch time) that now repeats what's on, because
        something else was played over the API meanwhile, goes back and another is drawn."""
        if self.drawn and self.upcoming and self.upcoming[0] in avoid:
            bag, k, before = self.drawn
            bag.put_back(k)
            self.upcoming.clear()
            self.clock_next = before
            self.drawn = None

    def peek(self, avoid=frozenset()):
        self._redraw_if_repeat(avoid)
        self._fill(avoid)
        return self.upcoming[0]

    def next(self, avoid=frozenset()):
        self._redraw_if_repeat(avoid)
        self._fill(avoid)
        self.drawn = None   # started: the rest of a group follows no matter what
        return self.upcoming.popleft()
