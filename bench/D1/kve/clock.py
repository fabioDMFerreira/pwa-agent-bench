"""Small logical clock: a strictly monotonic counter for ordering events."""


class LogicalClock:
    def __init__(self, start: int = 0):
        self._now = start

    def tick(self) -> int:
        self._now += 1
        return self._now

    def now(self) -> int:
        return self._now

    def sync(self, observed: int) -> None:
        """Merge an observed remote timestamp (max-semantics)."""
        if observed > self._now:
            self._now = observed