"""Append-only write-ahead log, organized as numbered segment files.

A segment is a plain file containing a sequence of frames (see `crc`).
Offsets are byte positions within a single segment; segments are ordered by
their numeric suffix (seg-000000.log, seg-000001.log, ...).
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

from . import crc
from .errors import CorruptionError


@dataclass(frozen=True)
class Frame:
    """One decoded log record.

    `offset` is the byte offset within its segment; `length` is the full
    on-disk frame size (header + payload); `seq` is a global monotonically
    increasing sequence number assigned by the Log.
    """

    seq: int
    offset: int
    length: int
    payload: bytes


class Log:
    SEGMENT_BYTES = 64 * 1024  # rotate after this many bytes (small for tests)

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._next_seq = 0
        self._current = self._next_segment_path()
        self._size = self._current.stat().st_size if self._current.exists() else 0
        self._fd = self._current.open("ab")
        self._closed = False

    def _next_segment_path(self) -> Path:
        existing = [p for p in self.dir.glob("seg-*.log")]
        if not existing:
            return self.dir / "seg-000000.log"
        highest = max(int(p.stem.split("-")[1]) for p in existing)
        return self.dir / f"seg-{highest + 1:06d}.log"

    def segments(self) -> list[Path]:
        """Segment paths in ascending (oldest-first) order."""
        return sorted(self.dir.glob("seg-*.log"), key=lambda p: p.stem)

    def append_put(self, key: str, value: str) -> Frame:
        return self._append(crc.encode_put(key, value))

    def append_delete(self, key: str) -> Frame:
        return self._append(crc.encode_delete(key))

    def _append(self, payload: bytes) -> Frame:
        if self._closed:
            raise CorruptionError("log is closed")
        blob = crc.pack_frame(payload)
        if self._size > 0 and self._size + len(blob) > self.SEGMENT_BYTES:
            self.rotate()
        offset = self._size
        self._fd.write(blob)
        self._fd.flush()
        self._size += len(blob)
        frame = Frame(seq=self._next_seq, offset=offset, length=len(blob), payload=payload)
        self._next_seq += 1
        return frame

    def rotate(self) -> None:
        """Seal the current segment and start a new one."""
        self._fd.close()
        self._current = self._next_segment_path()
        self._fd = self._current.open("ab")
        self._size = 0

    def close(self) -> None:
        if not self._closed:
            self._fd.close()
            self._closed = True

    def total_frames(self) -> int:
        return sum(1 for _ in self.iter_all())

    def iter_all(self):
        """Yield every frame of every segment, oldest segment first."""
        for seg in self.segments():
            for frame in iter_segment_frames(seg):
                yield frame


def iter_segment_frames(path: Path):
    """Decode all frames in one segment file, in file order."""
    blob = Path(path).read_bytes()
    offset = 0
    while offset < len(blob):
        payload, length = crc.unpack_frame(blob, offset)
        yield payload, offset, length
        offset += length


def replay_segment(path: Path):
    """Yield (op, key, value) tuples for one segment, in file order."""
    for payload, _offset, _length in iter_segment_frames(path):
        yield crc.decode_payload(payload)


def write_segment(path: Path, entries) -> int:
    """Write a segment file from an iterable of (op, key, value) entries.

    Returns the number of frames written. Used by flush and compaction.
    """
    count = 0
    with Path(path).open("wb") as f:
        for op, key, value in entries:
            payload = crc.encode_put(key, value) if op == "put" else crc.encode_delete(key)
            f.write(crc.pack_frame(payload))
            count += 1
    return count


def segment_size_bytes(path: Path) -> int:
    return Path(path).stat().st_size


def describe_segments(directory: Path) -> str:
    """One-line-per-segment summary for diagnostics/CLI."""
    lines = []
    for seg in sorted(Path(directory).glob("seg-*.log"), key=lambda p: p.stem):
        n = sum(1 for _ in iter_segment_frames(seg))
        lines.append(f"{seg.name}: {n} frames, {seg.stat().st_size} bytes")
    return "\n".join(lines)