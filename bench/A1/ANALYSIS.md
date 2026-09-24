# A1 — Ingest pipeline data flow

Source: `bench/A1/src/ingest/pipeline.py` (184 lines). All line numbers below refer to that file.
All behaviours described here were verified by running the module in a scratch script (no code was modified).

## 1. Path of one event from `submit()` to the sink

`IngestPipeline.submit(raw)` (L143–166) processes a single raw JSON event (str or bytes) through
five stages, in order:

1. **Closed check** (L145–146): if the pipeline was `close()`d, `submit` raises
   `RuntimeError("pipeline closed")` before anything else.
2. **Parse** — `IngestPipeline._parse` (L104–114): bytes are UTF-8 decoded, then `json.loads`.
   A JSON decode error becomes `InvalidEvent("not JSON")`; a top-level value that is not a JSON
   object (e.g. a list or string) becomes `InvalidEvent("event must be an object")`. On
   `InvalidEvent` the caller gets back `"invalid"` and `stats["invalid"]` is incremented (L149–151);
   nothing else is touched.
3. **Deduplicate** (L152–154): the key `(event.get("source"), event.get("id"))` — computed from the
   *raw* parsed dict, before any validation — is handed to the `_Window` LRU set (see §2). If the key
   was seen within the window, the caller gets `"duplicate"` and `stats["duplicate"]` is incremented.
   **The key is remembered even if the event later turns out invalid** (see §2 edge cases).
4. **Validate** — `IngestPipeline._validate` (L116–125): checks presence of `source`, `id`, `type`,
   `ts`, `user_id` (missing → `InvalidEvent(f"missing {field}")`); checks `type` is in
   `ALLOWED_TYPES = {"click", "view", "purchase", "signup"}` (L13, otherwise
   `InvalidEvent(f"unknown type ...")`); then shallow-copies the dict (`out = dict(event)`, L123) and
   replaces `ts` with the parsed value from `_parse_ts` (L60–70): trailing `"Z"` is rewritten to
   `"+00:00", ` naive timestamps are assumed UTC, everything is normalised to an aware
   `datetime` in UTC. Invalid → `"invalid"` return, `stats["invalid"] += 1` (L157–159).
5. **Enrich** — `IngestPipeline._enrich` (L127–139): looks up `event["user_id"]` in the TTL cache
   (see §3); on miss calls `self.user_lookup(user_id)` (exceptions swallowed → `user = None`) and
   caches the result. `event["user"]` is set to the lookup result or `None`.

Then (L161–166): the event is appended to the internal buffer as a tuple
`(event["ts"], self._arrival, event)`, where `_arrival` (L92) is a monotonically increasing per-
pipeline counter incremented only for accepted events; `stats["accepted"] += 1`; and if
`len(self._buffer) >= self.batch_size` (L164) the pipeline calls `self.flush()` **synchronously,
inside `submit`**. `flush()` (L168–176) sorts the whole buffer by `(ts, arrival-index)` (L172),
passes the resulting list of event dicts to `self.sink(batch)`, clears the buffer, and increments
`stats["batches"]`. `submit` finally returns `"accepted"`.

So the event reaches the sink only when a batch is flushed (§5); until then it sits in
`self._buffer` (L91), retrievable via `pending()` (L182–183).

## 2. Duplicate detection

- **What makes two events "the same"**: only the `(source, id)` pair (L152). `type`, `ts`, and
  `user_id` do not participate — an event `(web, 42, click)` and `(web, 42, purchase)` are the
  "same" event. Because the key is built with `event.get(...)`, a missing field contributes `None`: an event
  with neither `source` nor `id` uses the key `(None, None)`. Verified: submitting
  `{"type": "click"}` (missing both) returns `"invalid"`, and a following `{"foo": 1}` — which is
  also missing both — returns `"duplicate"`, because the `(None, None)` key was already in the
  window and the dedup check runs before validation. `id: null` passes validation (presence is the
  only check) and also collides in the window: two `id: null` events → `"accepted"` then
  `"duplicate"`.
- **How long the memory lasts**: `_Window` (L20–37) is a bounded LRU set holding the last
  `dedupe_capacity` distinct keys (default 1024, `__init__` L80). It is **count-based, not
  time-based**: a key is remembered until the window overflows — i.e. until `dedupe_capacity`
  *other* distinct keys have been seen since, and an already-seen key refreshes its position
  (`move_to_end`, L29), so hot keys survive longer. There is no TTL and no periodic purge.
- **Edge cases interacting with other stages**:
  - **Dedup runs before validation** (L152 before L156): a key is recorded in the window even if the
    event is then rejected as invalid (missing fields, bad `type`, bad `ts`). Verified: submitting
    `{"source": "web", "id": 5}` (missing `type`/`ts`/`user_id`) returns `"invalid"`, and a
    subsequently *valid* event with the same `(source, id)` returns `"duplicate"` — so one bad
    payload can permanently (up to the window) block a good one. Conversely, a *second* invalid
    event with an already-seen key is reported as `"duplicate"`, not `"invalid"` (duplicate wins,
    because the dedup check comes first).
  - **Dedup runs before enrichment**: a duplicate event never touches the user cache and never
    triggers/refreshes a lookup (verified: after the cache TTL elapses, re-submitting a duplicate
    still reports `"duplicate"` with `stats["lookups"]` unchanged).
  - **Dedup is independent of delivery**: a duplicate of an event that is still sitting in the
    buffer (sink not yet called) is still reported `"duplicate"` — the window keys on *submission*,
    not on successful delivery (verified). After a failed sink send (see §5), the caller cannot
    re-submit the same `(source, id)`; the only way the batch gets out is a retried `flush()`.
  - **Unhashable keys escape as `TypeError`**: `source`, `id` (or `user_id`, via the cache dict)
    being JSON arrays (e.g. `"id": [1, 2]`) makes the tuple/dict lookup raise
    `TypeError: unhashable type: 'list'` — this is *not* caught by `submit` (only `InvalidEvent` is)
    and propagates to the caller, with no stats update.
  - **Buffered-but-undelivered events keep their window slot**; the window is never shrunk by
    flushes or sink failures.

## 3. User-enrichment cache

`_TtlCache` (L40–57) wraps `user_lookup`, keyed by `user_id`.

- **When a lookup happens**: in `_enrich` (L127–139), only on a cache miss for that `user_id`
  (L129–131). `stats["lookups"]` counts *actual* `user_lookup` calls, not cache hits. Events that
  were parsed but are invalid, or duplicates, are dropped before `_enrich` runs, so they never
  consult the cache.
- **What is cached**: exactly what `user_lookup(user_id)` returns — **including `None`**. A
  "user not found" answer is therefore cached *negatively* for the full TTL: with a lookup that
  returns `None`, two events for the same `user_id` cause exactly one lookup (verified). The stored
  value is the very object returned by `user_lookup` (no copy): if it is a mutable dict, later
  batches share it and the caller's mutations would be visible to the pipeline.
  One asymmetry: if `user_lookup` **raises**, the result is *not* cached (L134–135) — the exception
  is swallowed, `user = None` is attached to that one event, and the *next* event for the same
  `user_id` retries the lookup (verified: a lookup that always raises is attempted once per event).
- **When entries expire**: on `put`, the entry's deadline is `clock() + ttl` (L57); default TTL is
  300 s with `clock=time.monotonic` (both injectable, L81–82). On `get`, an entry is expired when
  `clock() >= expires_at` (L51) — so it is expired *at exactly* `ttl` elapsed, and deleted lazily,
  only when that key is next looked up. The cache is never scanned: entries for `user_id`s that are
  never seen again linger in `self._users._data` forever (unbounded in distinct users, unlike the
  dedup window).

## 4. Ordering

- **Inside a batch**: `flush()` sorts the buffer by `(ts, arrival-index)` (L172). `ts` is the
  normalised aware-UTC `datetime` (so events from different input offsets sort by true instant),
  and the arrival index (L161–162) breaks ties by *submission* order. Example (verified): submitting
  events with `ts` 10:00, 09:00, 09:00 yields a batch ordered `09:00#1, 09:00#2, 10:00`.
- **What the sink does *not* get**:
  - **No delivery deadline**: there is no timer and no time-based flush. An event waits in the
    buffer until the buffer fills (`batch_size`), until `flush()` is called, or until `close()`.
  - **No cross-batch ordering**: a batch that flushed at 09:00 can be followed by a batch containing
    events with earlier `ts` values that were merely submitted later. Within *one* batch the order
    is chronological, but batches as a stream are not guaranteed globally sorted.
  - **No fixed batch size**: auto-flushed batches have exactly `batch_size` events, but any
    `flush()`/`close()` may send a shorter batch (or zero events — an empty `flush()` is a no-op
    returning 0 without calling the sink, verified).
  - **No serialization guarantee**: the sink receives plain Python dicts whose `ts` is a
    `datetime` object (not the original ISO string) plus a `user` key; the batch is *not*
    JSON-serializable as-is (`datetime` fails `json.dumps`, verified). Extra unknown fields are
    passed through untouched.

## 5. When batches are sent; sink failure

Batches are sent in exactly three ways:

1. **Automatically inside `submit`** when the buffer reaches `batch_size` (L164–165) — the sink call
   happens synchronously within the caller's `submit()` (with `batch_size=1` or `batch_size=0`,
   every accepted event triggers an immediate one-event batch; `len(buffer) >= 0` is always true,
   verified).
2. **Explicitly** via `flush()` (L168–176).
3. **On `close()`** (L178–180), which calls `flush()` first to drain the remainder, then sets
   `_closed = True`. (A second `close()` is safe: the buffer is empty, the sink is not called.)

**If `self.sink(batch)` raises** (L173):

- **Events are not lost and are not cleared**: `self._buffer.clear()` (L174) only runs if the sink
  returned. The buffer still holds all the events (verified: after a failing auto-flush,
  `pending()` is still `batch_size`), so the next `flush()` re-sends the *same* batch — the sink has
  **at-least-once** delivery semantics for the same `(source, id)` set if the caller retries.
- **The exception propagates to the caller**: for an auto-flush, it escapes out of `submit()` — the
  caller does not get the `"accepted"` return value. For `flush()`, it escapes out of `flush()`; for
  `close()`, out of `close()`.
- **Stats skew**: `stats["accepted"]` was already incremented *before* the flush (L163) and
  `stats["batches"]` is incremented only after a successful sink call (L175). So after a failed
  auto-flush: `accepted` counts events the sink never received, `batches` is unchanged, and a
  subsequent successful retry of the *same* events increments `batches` once (verified).
- **`close()` failure leaves the pipeline open**: `_closed = True` (L180) is not reached, so
  subsequent `submit()` calls still work (verified) and `close()` can be retried.
- Note the interplay with dedup: because window memory is independent of delivery, events stuck in
  a failed batch cannot be re-submitted individually — their `(source, id)` keys are already in the
  window, so re-submission returns `"duplicate"`. Recovery is only via `flush()`.

## 6. Surprising behaviours (summary)

- **`submit()` can call your sink synchronously** (auto-flush at `batch_size`, L164): a slow or
  failing sink blocks or breaks the caller's `submit()`.
- **`stats["accepted"]` overcounts deliveries**: incremented before the auto-flush (L163), so it
  includes events lost to a failed sink call until a retry succeeds.
- **A failed `close()` does not close the pipeline** — `submit()` keeps working afterwards (§5).
- **Invalid events poison their `(source, id)` key** for up to the whole dedupe window, so a later
  corrected event with the same key is rejected as `"duplicate"` (§2).
- **Dedup wins over validation in reporting**: a second, invalid occurrence of a known key is
  reported `"duplicate"`, not `"invalid"`.
- **`user: None` has two meanings** — either `user_lookup` returned `None` (which is *cached* for
  the full TTL) or `user_lookup` raised (which is *not* cached and retried per event); the sink
  cannot distinguish them.
- **Delivered events are not JSON**: `ts` arrives as a `datetime` object and the batch is not
  `json.dumps`-able. The sink also receives the *same dict objects* the pipeline buffers (the
  buffer stores the enriched event dict itself, L161 — no copy). After a sink failure the same
  objects are re-sent on the next `flush()`, so a sink that mutates its inputs during a failed
  call mutates the very events it will receive again on retry.
- **`flush()` after `close()` is allowed** (it doesn't check `_closed`); on an empty buffer it
  returns 0 without touching the sink.
- **`batch_size=0` means "flush every event immediately"**, not "never flush" (L164's `>= 0` is
  always true).
- **Unhashable `source`/`id`/`user_id` (JSON arrays) crash `submit()` with a raw `TypeError`** —
  not an `InvalidEvent`, no stats update.
- **The user cache is unbounded in distinct users** (lazy per-key expiry only), while the dedup
  window is strictly capacity-bounded; the two memory structures have opposite bounds.