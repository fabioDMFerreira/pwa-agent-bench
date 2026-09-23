"""Append-only event store with optimistic concurrency and optional JSONL
persistence.

* `append` assigns the next global `position` and the next per-stream
  `version`. Passing `expected_version` enforces optimistic concurrency
  (0 means "stream must not exist yet").
* In-process listeners registered with `subscribe` are called synchronously,
  in registration order, after each successful append. A listener that
  raises does not undo the append and does not stop other listeners.
* With `path` set, every event is appended as one JSON line and the file is
  replayed on construction.
"""

import json
import logging
import time
import uuid
from pathlib import Path

from .errors import ConcurrencyError, EventStoreError
from .events import Event

logger = logging.getLogger("eventstore")


class EventStore:
    def __init__(self, path=None, *, clock=time.time, id_factory=None):
        self._path = Path(path) if path is not None else None
        self._clock = clock
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._events: list[Event] = []
        self._streams: dict[str, list[Event]] = {}
        self._listeners: list = []
        if self._path is not None and self._path.exists():
            self._load()

    # -- writes -------------------------------------------------------------

    def append(self, stream: str, type: str, data: dict | None = None, *, expected_version=None) -> Event:
        if not stream or not isinstance(stream, str):
            raise EventStoreError("stream must be a non-empty string")
        if not type or not isinstance(type, str):
            raise EventStoreError("type must be a non-empty string")
        current = self.stream_version(stream)
        if expected_version is not None and expected_version != current:
            raise ConcurrencyError(
                f"{stream}: expected version {expected_version}, actual {current}"
            )
        event = Event(
            position=len(self._events) + 1,
            stream=stream,
            version=current + 1,
            type=type,
            data=dict(data or {}),
            id=self._id_factory(),
            recorded_at=float(self._clock()),
        )
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")
        self._record(event)
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:  # noqa: BLE001 - listeners must not break appends
                logger.exception("listener failed for event %s", event.position)
        return event

    def _record(self, event: Event) -> None:
        self._events.append(event)
        self._streams.setdefault(event.stream, []).append(event)

    def _load(self) -> None:
        with self._path.open(encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                event = Event.from_dict(json.loads(line))
                if event.position != len(self._events) + 1:
                    raise EventStoreError(f"{self._path}:{lineno}: position gap")
                self._record(event)

    # -- reads --------------------------------------------------------------

    def stream_version(self, stream: str) -> int:
        return len(self._streams.get(stream, ()))

    @property
    def head_position(self) -> int:
        """Position of the newest event (0 when empty)."""
        return len(self._events)

    def read_stream(self, stream: str, from_version: int = 1) -> list[Event]:
        events = self._streams.get(stream, [])
        return events[max(from_version, 1) - 1 :]

    def read_all(self, after_position: int = 0, limit: int | None = None) -> list[Event]:
        """Events with position > after_position, oldest first."""
        out = self._events[max(after_position, 0) :]
        return out[:limit] if limit is not None else list(out)

    # -- listeners ----------------------------------------------------------

    def subscribe(self, listener):
        """Register `listener(event)`; returns a function that unregisters it."""
        self._listeners.append(listener)

        def unsubscribe():
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe
