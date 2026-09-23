"""Unit tests: frame packing/checksums."""

import pytest

from kve import CorruptionError
from kve.crc import (
    decode_payload,
    encode_delete,
    encode_put,
    pack_frame,
    unpack_frame,
)


def test_roundtrip():
    payload = encode_put("k", "v")
    blob = pack_frame(payload)
    decoded, length = unpack_frame(blob, 0)
    assert decoded == payload
    assert length == len(blob)


def test_corruption_detected():
    blob = bytearray(pack_frame(encode_put("k", "v")))
    blob[-1] ^= 0xFF  # flip a payload byte
    with pytest.raises(CorruptionError):
        unpack_frame(bytes(blob), 0)


def test_truncated_header():
    blob = pack_frame(encode_put("k", "v"))
    with pytest.raises(CorruptionError):
        unpack_frame(blob[:4], 0)


def test_truncated_body():
    blob = pack_frame(encode_put("k", "v"))
    with pytest.raises(CorruptionError):
        unpack_frame(blob[:-1], 0)


def test_payload_decode_put():
    op, key, value = decode_payload(encode_put("alpha", "beta"))
    assert (op, key, value) == ("put", "alpha", "beta")


def test_payload_decode_delete():
    op, key, value = decode_payload(encode_delete("alpha"))
    assert (op, key, value) == ("delete", "alpha", None)


def test_second_frame_offset():
    one = pack_frame(encode_put("a", "1"))
    two = pack_frame(encode_put("b", "2"))
    blob = one + two
    _, length1 = unpack_frame(blob, 0)
    decoded2, _ = unpack_frame(blob, length1)
    assert decode_payload(decoded2) == ("put", "b", "2")