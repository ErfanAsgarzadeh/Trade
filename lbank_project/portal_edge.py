"""Small in-process protections for the public site: a per-IP token bucket and a short page cache. Both are bounded."""
from collections import OrderedDict
import math
import threading
import time


class TokenBuckets:
    """`per_minute` requests per minute per client with a burst of the same size. At most `max_clients` are tracked;
    the least recently seen client is dropped first, so a flood of addresses cannot grow memory."""

    def __init__(self, per_minute=120, max_clients=10000, clock=time.monotonic):
        self.capacity, self.rate, self.max_clients, self.clock = float(per_minute), per_minute / 60.0, max_clients, clock
        self.buckets, self.lock = OrderedDict(), threading.Lock()

    def take(self, client):
        """0 when the request may go on, otherwise the whole seconds to wait."""
        now = self.clock()
        with self.lock:
            tokens, seen = self.buckets.pop(client, (self.capacity, now))
            tokens = min(self.capacity, tokens + (now - seen) * self.rate)
            wait = 0 if tokens >= 1 else max(1, math.ceil((1 - tokens) / self.rate))
            self.buckets[client] = (tokens - 1 if not wait else tokens, now)
            while len(self.buckets) > self.max_clients:self.buckets.popitem(last=False)
        return wait


class TTLCache:
    """Rendered pages for a few seconds. Entries are tagged with a generation; bumping it (a blog save or delete) drops them all."""

    def __init__(self, seconds=30, limit=256, clock=time.monotonic):
        self.seconds, self.limit, self.clock = seconds, limit, clock
        self.items, self.lock = OrderedDict(), threading.Lock()

    def get(self, key, generation=0):
        with self.lock:
            hit = self.items.get(key)
            if hit and hit[1] == generation and hit[0] > self.clock():return hit[2]
            self.items.pop(key, None)
        return None

    def put(self, key, value, generation=0):
        with self.lock:
            self.items.pop(key, None)
            self.items[key] = (self.clock() + self.seconds, generation, value)
            while len(self.items) > self.limit:self.items.popitem(last=False)
        return value
