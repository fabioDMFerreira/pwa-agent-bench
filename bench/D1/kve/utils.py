"""Small shared utilities."""

import time


def monotonic_ns() -> int:
    return time.monotonic_ns()


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def human_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GiB"


def chunked(seq, size: int):
    """Yield lists of at most `size` items (for paged dumps)."""
    if size < 1:
        raise ValueError("size must be >= 1")
    batch = []
    for item in seq:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch