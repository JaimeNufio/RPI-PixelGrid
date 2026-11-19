"""Rotation order: what plays next when the queue is empty, from the tags on config
manager.rotation items.

    active   in the cycle. Every active item plays once before any plays again.
    clock    an interlude: one clock item plays between active items (they take turns
             the same way, each once before any repeats).
    group    items with the same "group" (a field, not a tag) play back to back in
             config order, with no clock between them, and count as one pick
             (weather "now" then "forecast").

An item with neither tag is listed but doesn't play (drop "active" to bench something).
With no tags anywhere, every item plays in turn, like before tags existed.
shuffle: true shuffles each round (a new round never starts with what just played);
false keeps config order.

    order = Rotation(items, shuffle=True)
    order.peek()   # index of the item that plays next (stays the same until next())
    order.next()   # index of the item to play now
"""
import random
from collections import deque

TAGS = ("active", "clock")


class Bag:
    """Hands out units one at a time, each once per round."""

    def __init__(self, units, shuffle, rng):
        self.units = units
        self.shuffle = shuffle
        self.rng = rng
        self.pending = []
        self.last = None

    def draw(self):
        if not self.pending:
            order = list(range(len(self.units)))
            if self.shuffle:
                self.rng.shuffle(order)
                if len(order) > 1 and order[0] == self.last:
                    order.append(order.pop(0))   # no back-to-back repeat across rounds
            self.pending = order
        self.last = self.pending.pop(0)
        return self.units[self.last]


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
                clocks.append(i)
        self.active = Bag(units, shuffle, rng)
        self.clocks = Bag(clocks, shuffle, rng)
        self.upcoming = deque()
        self.clock_next = False   # start with an active item

    def _fill(self):
        if self.upcoming:
            return
        if self.clocks.units and (self.clock_next or not self.active.units):
            self.upcoming.append(self.clocks.draw())
            self.clock_next = False
        elif self.active.units:
            self.upcoming.extend(self.active.draw())
            self.clock_next = True
        else:
            raise ValueError("manager.rotation has nothing to play: tag at least one item \"active\" or \"clock\"")

    def peek(self):
        self._fill()
        return self.upcoming[0]

    def next(self):
        self._fill()
        return self.upcoming.popleft()
