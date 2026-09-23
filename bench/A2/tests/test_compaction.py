"""Compaction semantics: newest segment wins, tombstones propagate and drop.

Each test builds explicit segment files (oldest first) via
`kve.log.write_segment` and checks the merged output.
"""

from pathlib import Path

from kve import compaction
from kve import log as klog


def _write_segments(tmp_path: Path, names_entries: list[tuple[str, list]]) -> list[Path]:
    """names_entries: [(name, [(op, key, value), ...]), ...] oldest first."""
    paths = []
    for name, entries in names_entries:
        p = tmp_path / name
        klog.write_segment(p, entries)
        paths.append(p)
    return paths


def _read_segment(path: Path):
    return dict(
        (k, v) for op, k, v in klog.replay_segment(path) if op == "put"
    ), {k for op, k, _v in klog.replay_segment(path) if op == "delete"}


def test_newest_wins_across_segments(tmp_path):
    segs = _write_segments(tmp_path, [
        ("seg-000000.log", [("put", "k", "old"), ("put", "j", "keep")]),
        ("seg-000001.log", [("put", "k", "new")]),
    ])
    out = tmp_path / "out.log"
    written = compaction.compact(segs, out)
    live, deleted = _read_segment(out)
    assert live == {"k": "new", "j": "keep"}
    assert deleted == set()
    assert written == 2


def test_newest_wins_three_segments(tmp_path):
    segs = _write_segments(tmp_path, [
        ("seg-000000.log", [("put", "k", "v1")]),
        ("seg-000001.log", [("put", "k", "v2")]),
        ("seg-000002.log", [("put", "k", "v3")]),
    ])
    out = tmp_path / "out.log"
    compaction.compact(segs, out)
    live, _ = _read_segment(out)
    assert live == {"k": "v3"}


def test_tombstone_hides_older_values(tmp_path):
    segs = _write_segments(tmp_path, [
        ("seg-000000.log", [("put", "k", "old")]),
        ("seg-000001.log", [("delete", "k", None)]),
    ])
    out = tmp_path / "out.log"
    written = compaction.compact(segs, out)
    assert written == 0
    live, deleted = _read_segment(out)
    assert live == {}
    assert deleted == set()  # tombstones do not survive compaction


def test_newer_value_over_tombstone_survives(tmp_path):
    # delete in the middle, put in the newest segment -> key lives
    segs = _write_segments(tmp_path, [
        ("seg-000000.log", [("put", "k", "v1")]),
        ("seg-000001.log", [("delete", "k", None)]),
        ("seg-000002.log", [("put", "k", "v2")]),
    ])
    out = tmp_path / "out.log"
    compaction.compact(segs, out)
    live, _ = _read_segment(out)
    assert live == {"k": "v2"}


def test_single_segment_identity(tmp_path):
    segs = _write_segments(tmp_path, [
        ("seg-000000.log", [("put", "a", "1"), ("put", "b", "2"), ("delete", "c", None)]),
    ])
    out = tmp_path / "out.log"
    written = compaction.compact(segs, out)
    live, _ = _read_segment(out)
    assert live == {"a": "1", "b": "2"}
    assert written == 2


def test_needs_compaction_heuristic(tmp_path):
    paths = []
    for i in range(5):
        p = tmp_path / f"seg-{i:06d}.log"
        klog.write_segment(p, [("put", f"k{i}", "v")])
        paths.append(p)
    assert compaction.needs_compaction(paths)
    assert not compaction.needs_compaction(paths[:2])
    assert compaction.compact_size_estimate(paths) == 5  # one unique key each