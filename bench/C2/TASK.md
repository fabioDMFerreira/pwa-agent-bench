# C2 — Implement `chunk`

Work only inside `bench/C2/`. Do not modify existing tests.

Implement `chunk(items, size)` in `src/chunk.py`. It splits `items` into
consecutive chunks of length `size`; the last chunk may be shorter.

## Spec

- `items` may be **any iterable** — list, tuple, string, `range`, generator,
  etc. Each element is visited once, in iteration order.
- Returns a `list` of `list`s. Chunks are always new lists (even when the
  input is a tuple or string), and the input is never mutated.
- Empty input returns `[]`.
- `size` must be an `int` (`bool` is **not** accepted). A non-int `size`
  raises `TypeError`.
- `size <= 0` raises `ValueError`.
- `size` is validated before anything else, so invalid sizes raise even when
  `items` is empty.

`tests/test_chunk.py` covers part of this spec; the full spec above is what
counts.

**Deliverable:** `src/chunk.py` implementing the spec; tests pass with
`cd bench/C2 && python3 -m pytest -q`.
