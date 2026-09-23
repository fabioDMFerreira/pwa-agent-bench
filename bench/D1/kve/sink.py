"""Sinks: where replicated frames land.

A sink is the durable end of a replication channel. The primary ships
frames to it; after a failover the new primary (or a recovery process)
replays the sink's frames to rebuild state.
"""

from pathlib import Path

from .errors import ReplicationError


class MemorySink:
    """In-memory sink (tests, demos). Frames are an append-only list."""

    def __init__(self):
        self.frames: list[bytes] = []
        self.writes = 0

    def append(self, payload: bytes) -> int:
        """Append a frame; returns its 0-based sequence number."""
        self.frames.append(payload)
        self.writes += 1
        return len(self.frames) - 1

    def replay(self, upto_seq: int):
        """Yield payloads with seq <= upto_seq (upto_seq < 0 -> none)."""
        if upto_seq < 0:
            return
        for payload in self.frames[: upto_seq + 1]:
            yield payload

    def __len__(self):
        return len(self.frames)


class FileSink:
    """Append-only file sink: one frame per line (base64-ish escaping via
    percent encoding so arbitrary payloads stay line-oriented)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch()

    def append(self, payload: bytes) -> int:
        line = payload.replace(b"%", b"%25").replace(b"\n", b"%0A") + b"\n"
        with self.path.open("ab") as f:
            f.write(line)
        return self.__len__() - 1

    def __len__(self):
        with self.path.open("rb") as f:
            return sum(1 for _ in f)

    def replay(self, upto_seq: int):
        if upto_seq < 0:
            return
        with self.path.open("rb") as f:
            for i, raw in enumerate(f):
                if i > upto_seq:
                    break
                yield raw.rstrip(b"\n").replace(b"%0A", b"\n").replace(b"%25", b"%")