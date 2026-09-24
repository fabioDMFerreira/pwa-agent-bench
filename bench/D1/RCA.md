# D1 — Root Cause Analysis: kve store

Two defects, each in a single line of control flow, explain both user
reports. The tests encode the intended semantics; the module docstrings
were the source of truth the code had drifted from.

---

## Defect 1 — Compaction inverted the segment precedence (Report A)

**File/function:** `kve/compaction.py` → `compact(segment_paths, out_path)`

**How it produces the reported symptoms.** The contract (module
docstring, function docstring, and the tests) is: input segments are
ordered oldest → newest, and when the same key appears in several
segments the entry from the **newest** segment wins, with tombstones
propagating. The merge loop iterated `for path in reversed(segment_paths)`,
i.e. **newest first**. Because every replayed entry *overwrites*
`survivors[key]`, the last-written survivor for a key was the one from
the **oldest** segment — the precedence was silently inverted:

- **Stale values after compaction.** A key overwritten in a newer segment
  (`put k=v1` in seg-000000, `put k=v2` in seg-000001) came back as `v1`
  after `compact()`, because the oldest put won the merge.
- **Deleted keys reappearing.** A delete written after a put (e.g.
  `put gone=x`, `del gone`) was masked by the older put: the delete
  (newer segment) was applied first and then overwritten by the older
  put, so the key survived compaction even though the tombstone was the
  final word for that key.

Reads were fine before compaction because the store's read path
(`KvStore.get` / `scan`) consults the memtable and tables
newest-first; the inversion only materialised when `compact()` merged the
segments on disk — exactly "reads are fine until `compact()` runs".

**Fix.** Iterate the segments in the order they are documented
(ascending / oldest first) so that each newer entry overwrites the older
one and the newest entry is the survivor:

```python
for path in segment_paths:            # was: for path in reversed(segment_paths)
    for op, key, value in log.replay_segment(Path(path)):
        survivors[key] = None if op == "delete" else value
```

The misleading comment ("Newest first ... earlier segments fill in
anything missing") described the *opposite* strategy (first-write-wins
with fill-in) that was never implemented; the comment was corrected to
match the last-write-wins merge that was actually in place.

**Bug class.** Inverted iteration order / priority inversion in a merge
(the "which side wins" question answered backwards); the overwriting
assignment made it a *silent* inversion — no error, just wrong values.

**How it could have been caught earlier.** A property test that builds
segments in known oldest→newest order and asserts the compacted output
equals a last-writer-wins reference merge (or simply a round-trip test:
`compact([s1, s2])` must equal the value of the newest segment for
overwritten keys) would have failed on the first run.

---

## Defect 2 — Replication ack lagged the sink by one frame (Report B)

**File/function:** `kve/replication.py` → `Replicator.ship(frame)`
(the same off-by-one also poisoned the `in_flight` value in
`Replicator.stats()`).

**How it produces the reported symptoms.** The documented semantics in
the module docstring: `acked_seq` is the sequence number of the **last
frame the sink has durably stored** — after shipping frame N,
`acked_seq == N`, and a failover replays every frame with
`seq <= acked_seq`. The `ship()` code instead set

```python
self.acked_seq = seq - 1            # was: ack one behind, per a bogus comment
```

on the theory that "the sink can only confirm the previous frame as
durable". No such lag exists: `sink.append()` has already returned, i.e.
the frame is durably in the sink, so the just-shipped frame *is* the last
acked one. Consequences:

- **Most recent write always missing after failover.** After every
  successful `ship()` the ack permanently trailed the durable sink by
  one frame, so `replay_sink()` (which replays `seq <= acked_seq`)
  dropped the last frame — precisely "the most recent write is always
  missing, even though `ship()` returned successfully" (the failure is
  deterministic and independent of timing, which is why it *always*
  happened).
- **Deletes not visible on the replica.** A delete is the newest frame;
  when it was the last one shipped it fell off the acked prefix, so
  `failover_snapshot()` rebuilt state from everything *except* the
  delete and reported the key as still present on the replica.

**Fix.** Ack the frame the sink just durably stored:

```python
self.acked_seq = seq                # was: self.acked_seq = seq - 1
```

and correct the accompanying comment. The `in_flight` diagnostic in
`stats()` carried the same one-behind assumption
(`shipped - (acked_seq + 1) + 1 if shipped else 0`, which reported a
spurious "1 in flight" after the last ship) and was reduced to
`shipped - (acked_seq + 1)`: exactly 0 once everything is acked, and
correct for any genuine partial-ack state as well.

**Bug class.** Off-by-one / incorrect acknowledgement state
(a monotonic water mark advanced one step short), compounded by a
misleading comment that rationalised the wrong behaviour.

**How it could have been caught earlier.** A test asserting the
documented invariant after a single ship — `ship(frame_0)` ⇒
`acked_seq == 0` and `replay_sink()` yields frame 0 — plus an
`in_flight == 0` assertion when `acked_seq == shipped - 1`, would have
caught the lag immediately; the docstring already stated the invariant,
so a docstring-driven test was all that was missing.

---

## Verification

`cd bench/D1 && python3 -m pytest -q` → **53 passed** (was 37 passed,
16 failed). The fixes are two lines of logic plus their comments; no
public names or signatures changed, no test files modified.