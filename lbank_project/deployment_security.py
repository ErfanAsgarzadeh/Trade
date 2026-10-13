"""File-backed dashboard credentials and bounded login throttling."""
import os
from pathlib import Path
import time


def dashboard_secret() -> str:
    filename = os.getenv('BOT_PIN_FILE')
    if filename:
        try:
            path = Path(filename)
            if path.stat().st_size > 4096:
                return ''
            return path.read_text(encoding='utf-8').strip()
        except OSError:
            return ''
    return os.getenv('BOT_PIN', '')


class LoginThrottle:
    def __init__(self, limit=10, window=60., max_clients=2048):
        self.limit, self.window, self.max_clients = limit, window, max_clients
        self.failures = {}

    def blocked(self, client: str) -> bool:
        now = time.monotonic()
        self.failures = {k: v for k, v in self.failures.items() if v[0] + self.window > now}
        item = self.failures.get(client)
        return item is not None and item[1] >= self.limit

    def failed(self, client: str):
        now = time.monotonic()
        if client not in self.failures and len(self.failures) >= self.max_clients:
            self.failures.pop(next(iter(self.failures)))
        start, count = self.failures.get(client, (now, 0))
        self.failures[client] = (start, count + 1)

    def succeeded(self, client: str):
        self.failures.pop(client, None)
