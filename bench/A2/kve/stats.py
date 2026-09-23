"""Diagnostic statistics helpers (read-only; used by CLI and monitors)."""

from . import segment


def store_health_summary(directory) -> dict:
    """Cheap health snapshot: segment counts, sizes, tombstone pressure."""
    from pathlib import Path

    tables = sorted((Path(directory) / "tables").glob("seg-*.flush"), key=lambda p: p.stem)
    wal = Path(directory) / "wal"
    wal_segments = sorted(wal.glob("seg-*.log")) if wal.exists() else []

    total_frames = 0
    tombstones = 0
    for t in tables:
        for op, _k, _v in _replay(t):
            total_frames += 1
            if op == "delete":
                tombstones += 1

    return {
        "table_segments": len(tables),
        "wal_segments": len(wal_segments),
        "table_frames": total_frames,
        "tombstone_frames": tombstones,
        "tombstone_ratio": (tombstones / total_frames) if total_frames else 0.0,
        "total_table_bytes": sum(t.stat().st_size for t in tables),
    }


def _replay(path):
    from . import log

    return log.replay_segment(path)


def compact_advice(summary: dict, frame_threshold: int = 200, tomb_ratio: float = 0.5) -> str:
    """Rule-of-thumb maintenance advice for the CLI."""
    if summary["table_segments"] >= 4:
        return "compact: too many segments"
    if summary["tombstone_ratio"] >= tomb_ratio and summary["table_frames"] >= frame_threshold:
        return "compact: tombstone-heavy"
    return "ok"