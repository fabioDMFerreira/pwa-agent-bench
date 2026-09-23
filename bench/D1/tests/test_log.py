"""Unit tests: WAL append, rotation, replay."""

import pytest

from kve import CorruptionError
from kve import log as klog


def test_append_and_replay(tmp_path):
    w = klog.Log(tmp_path)
    f1 = w.append_put("a", "1")
    f2 = w.append_put("b", "2")
    f3 = w.append_delete("a")
    assert (f1.seq, f2.seq, f3.seq) == (0, 1, 2)
    frames = list(w.iter_all())
    assert len(frames) == 3
    replayed = list(klog.replay_segment(w.segments()[0]))
    assert replayed == [
        ("put", "a", "1"),
        ("put", "b", "2"),
        ("delete", "a", None),
    ]


def test_offsets_are_contiguous(tmp_path):
    w = klog.Log(tmp_path)
    f1 = w.append_put("a", "1")
    f2 = w.append_put("bb", "22")
    assert f2.offset == f1.offset + f1.length


def test_rotation_creates_segments(tmp_path):
    w = klog.Log(tmp_path)
    w.SEGMENT_BYTES = 64
    for i in range(8):
        w.append_put(f"k{i}", "value" * 10)
    assert len(w.segments()) >= 2
    assert w.total_frames() == 8


def test_offsets_reset_per_segment(tmp_path):
    w = klog.Log(tmp_path)
    w.SEGMENT_BYTES = 64
    for i in range(8):
        w.append_put(f"k{i}", "value" * 10)
    for seg in w.segments()[1:]:
        _payload, offset, _length = next(klog.iter_segment_frames(seg))
        assert offset == 0  # offset restarts at 0 in each new segment