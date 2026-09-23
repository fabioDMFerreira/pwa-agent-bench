"""Event ingest pipeline.

Raw events (JSON text) are submitted one at a time and delivered to a sink in
batches. Each event is a JSON object with at least `source`, `id`, `type`,
`ts` (ISO-8601) and `user_id`.
"""

import json
import time
from collections import OrderedDict
from datetime import datetime, timezone

ALLOWED_TYPES = frozenset({"click", "view", "purchase", "signup"})


class InvalidEvent(ValueError):
    pass


class _Window:
    """Bounded recently-seen set."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        self._keys: OrderedDict = OrderedDict()

    def seen(self, key) -> bool:
        if key in self._keys:
            self._keys.move_to_end(key)
            return True
        self._keys[key] = None
        if len(self._keys) > self.capacity:
            self._keys.popitem(last=False)
        return False

    def __len__(self) -> int:
        return len(self._keys)


class _TtlCache:
    def __init__(self, ttl: float, clock):
        self.ttl = ttl
        self.clock = clock
        self._data: dict = {}

    def get(self, key):
        hit = self._data.get(key)
        if hit is None:
            return False, None
        value, expires_at = hit
        if self.clock() >= expires_at:
            del self._data[key]
            return False, None
        return True, value

    def put(self, key, value) -> None:
        self._data[key] = (value, self.clock() + self.ttl)


def _parse_ts(value) -> datetime:
    if not isinstance(value, str):
        raise InvalidEvent("ts must be a string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        ts = datetime.fromisoformat(text)
    except ValueError as exc:
        raise InvalidEvent(f"bad ts: {value!r}") from exc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


class IngestPipeline:
    def __init__(
        self,
        sink,
        user_lookup,
        *,
        batch_size: int = 100,
        dedupe_capacity: int = 1024,
        enrich_ttl: float = 300.0,
        clock=time.monotonic,
    ):
        """`sink(batch: list[dict])` delivers a batch; `user_lookup(user_id)`
        returns a user dict or None."""
        self.sink = sink
        self.user_lookup = user_lookup
        self.batch_size = batch_size
        self._window = _Window(dedupe_capacity)
        self._users = _TtlCache(enrich_ttl, clock)
        self._buffer: list[tuple[datetime, int, dict]] = []
        self._arrival = 0
        self._closed = False
        self.stats = {
            "accepted": 0,
            "duplicate": 0,
            "invalid": 0,
            "batches": 0,
            "lookups": 0,
        }

    # -- stages ----------------------------------------------------------

    @staticmethod
    def _parse(raw) -> dict:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvalidEvent("not JSON") from exc
        if not isinstance(event, dict):
            raise InvalidEvent("event must be an object")
        return event

    @staticmethod
    def _validate(event: dict) -> dict:
        for field in ("source", "id", "type", "ts", "user_id"):
            if field not in event:
                raise InvalidEvent(f"missing {field}")
        if event["type"] not in ALLOWED_TYPES:
            raise InvalidEvent(f"unknown type {event['type']!r}")
        out = dict(event)
        out["ts"] = _parse_ts(event["ts"])
        return out

    def _enrich(self, event: dict) -> dict:
        uid = event["user_id"]
        found, user = self._users.get(uid)
        if not found:
            self.stats["lookups"] += 1
            try:
                user = self.user_lookup(uid)
            except Exception:  # noqa: BLE001 - enrichment is best-effort
                user = None
            else:
                self._users.put(uid, user)
        event["user"] = user
        return event

    # -- public API --------------------------------------------------------

    def submit(self, raw) -> str:
        """Ingest one raw event. Returns "accepted", "duplicate" or "invalid"."""
        if self._closed:
            raise RuntimeError("pipeline closed")
        try:
            event = self._parse(raw)
        except InvalidEvent:
            self.stats["invalid"] += 1
            return "invalid"
        if self._window.seen((event.get("source"), event.get("id"))):
            self.stats["duplicate"] += 1
            return "duplicate"
        try:
            event = self._validate(event)
        except InvalidEvent:
            self.stats["invalid"] += 1
            return "invalid"
        event = self._enrich(event)
        self._buffer.append((event["ts"], self._arrival, event))
        self._arrival += 1
        self.stats["accepted"] += 1
        if len(self._buffer) >= self.batch_size:
            self.flush()
        return "accepted"

    def flush(self) -> int:
        """Send buffered events to the sink. Returns the batch size sent."""
        if not self._buffer:
            return 0
        batch = [event for _ts, _n, event in sorted(self._buffer, key=lambda r: (r[0], r[1]))]
        self.sink(batch)
        self._buffer.clear()
        self.stats["batches"] += 1
        return len(batch)

    def close(self) -> None:
        self.flush()
        self._closed = True

    def pending(self) -> int:
        return len(self._buffer)
