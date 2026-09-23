# A2 — Audit the kve store against its documented contract

Work only inside `bench/A2/`. Do not modify any code — this is a read-only
audit. The only file you may create is the deliverable below (scratch scripts
must live outside the repo or be deleted before you finish).

`bench/A2/kve/` is a small embedded key-value store (~17 modules).
**All 53 tests in `bench/A2/tests/` currently pass**
(`cd bench/A2 && python3 -m pytest -q`). However, a recent review suggests the
implementation has drifted from its documented contract in at least one
place. The module and function **docstrings are the source of truth** for
intended behaviour.

Audit `kve/` against its documented semantics and find every place where the
implementation deviates from what the docstrings specify — even if no test
catches it.

## Deliverable

Write `bench/A2/AUDIT.md`. For each deviation give:

(a) file and function (with line number),
(b) the documented contract it violates (quote it),
(c) how the implementation deviates and the observable symptom — ideally a
    minimal reproduction (a few lines of Python and the wrong vs expected output),
(d) the fix you would make (describe it or show a diff in the markdown; do not
    apply it).

Then add a short "contracts checked" section listing the other docstring
contracts you verified and why they hold. If you find no deviations, say so
explicitly. Report only real deviations — incorrect findings count against you.

## Project map

| Module | Role |
|---|---|
| `kve/log.py` | append-only write-ahead log (segments of framed records) |
| `kve/crc.py` | frame packing / CRC32 checksums |
| `kve/compaction.py` | segment merge (newest segment wins, tombstones propagate) |
| `kve/replication.py` + `kve/sink.py` | shipping log frames to a sink, ack tracking, failover replay |
| `kve/store.py` + `kve/client.py` | the store / high-level client (read-write path, flush, compact) |
| `kve/memtable.py`, `kve/table.py`, `kve/segment.py`, `kve/lru.py`, `kve/clock.py`, `kve/stats.py`, `kve/config.py`, `kve/utils.py`, `kve/errors.py`, `kve/cli.py` | supporting modules |
