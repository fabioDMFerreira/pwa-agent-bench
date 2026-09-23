# D1 — Debug the kve store

Work only inside `bench/D1/`. Do not modify existing tests.

`kve/` is a small embedded key-value store (~17 modules, ~1,500 lines):
append-only log, memtable, segment files, compaction, and log replication
to a sink with failover. Several tests in `tests/` fail. We have these
reports from users:

> **Report A.** "After a compaction, some keys come back with an *older*
> value than the one I last wrote. Worse, keys I deleted before compacting
> sometimes reappear. Reads are fine until `compact()` runs."

> **Report B.** "After failing over to the replica, the most recent write is
> always missing — even though `ship()` returned successfully. If I delete a
> key and then fail over, the key is still there on the replica."

The documented semantics in the module docstrings are the source of truth.
The tests encode the intended behaviour.

## Requirements

1. Find the root cause(s) and fix them so `cd bench/D1 && python3 -m pytest -q`
   passes fully.
2. Do not change the public API (module/class/function names or
   signatures). Prefer minimal, surgical fixes; keep surrounding code intact.
   Do not paper over symptoms (e.g. special-casing in tests' call paths).
3. Write `bench/D1/RCA.md`: for each defect — the file/function, how it
   produces the reported symptoms, the fix, the bug class, and one sentence
   on how it could have been caught earlier.

**Deliverable:** fixed `kve/` code plus `RCA.md`.
