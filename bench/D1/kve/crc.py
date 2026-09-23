"""Framing for log records.

Frame layout (big-endian):

    +--------+--------+----------------+
    | crc32  | length | payload bytes  |
    | u32    | u32    | `length` bytes |
    +--------+--------+----------------+

`crc32` covers the payload only. Offsets are byte positions within a segment.
"""

import struct
import zlib

from .errors import CorruptionError

_HEADER = struct.Struct(">II")
MAGIC_PUT = b"put"
MAGIC_DELETE = b"del"


def frame_crc(payload: bytes) -> int:
    return zlib.crc32(payload) & 0xFFFFFFFF


def pack_frame(payload: bytes) -> bytes:
    return _HEADER.pack(frame_crc(payload), len(payload)) + payload


def unpack_frame(blob: bytes, offset: int):
    """Decode one frame at `offset`. Returns (payload, length) where length is
    the full on-disk frame size (header + payload)."""
    if offset < 0 or offset + _HEADER.size > len(blob):
        raise CorruptionError(f"truncated frame header at offset {offset}")
    crc, length = _HEADER.unpack_from(blob, offset)
    start = offset + _HEADER.size
    end = start + length
    if end > len(blob):
        raise CorruptionError(f"truncated frame body at offset {offset}")
    payload = blob[start:end]
    if frame_crc(payload) != crc:
        raise CorruptionError(f"checksum mismatch at offset {offset}")
    return payload, _HEADER.size + length


def encode_put(key: str, value: str) -> bytes:
    """Payload for a put: `<magic>|<key>|<value>`."""
    return MAGIC_PUT + b"|" + key.encode("utf-8") + b"|" + value.encode("utf-8")


def encode_delete(key: str) -> bytes:
    """Payload for a tombstone: `<magic>|<key>`."""
    return MAGIC_DELETE + b"|" + key.encode("utf-8")


def decode_payload(payload: bytes):
    """Decode into (op, key, value) — value is None for tombstones."""
    parts = payload.split(b"|", 2)
    if len(parts) < 2 or parts[0] not in (MAGIC_PUT, MAGIC_DELETE):
        raise CorruptionError(f"unrecognized payload magic: {parts[0]!r}")
    key = parts[1].decode("utf-8")
    if parts[0] == MAGIC_PUT:
        return "put", key, parts[2].decode("utf-8")
    return "delete", key, None