# Ingest pipeline data flow — `bench/A1/src/ingest/pipeline.py`

Maintainer-level walkthrough of the module (183 lines at revision `04266e8`).
`IngestPipeline` takes raw JSON events (`str` or `bytes`) one at a time through
`submit()` (L143) and delivers them, in sorted batches, to a caller-supplied
`sink(batch: list[dict])`.

## State

Everything the pipeline remembers lives on the instance (`__init__`, L74–100):

| Field | Type | Purpose |
| --- | --- | --- |
| `sink`, `user_lookup` | callables | delivery target and user enricher (L86–87) |
| `batch_size` | int, default 100 (L79) | events buffered before an auto-flush |
| `_window` | `_Window` (L20–37), LRU set of capacity `dedupe_capacity` (default 1024, L80) | duplicate detection |
| `_users` | `_TtlCache` (L40–57), TTL `enrich_ttl` (default 300.0 s, L81), clock injectable (default `time.monotonic`, L82) | user-enrichment cache |
| `_buffer` | `list[tuple[datetime, int, dict]]` (L91) | events awaiting the sink: `(ts, arrival, event)` |
| `_arrival` | int (L92) | monotonic counter, one per accepted event |
| `_closed` | bool (L93) | set by `close()` (L180) |
| `stats` | dict (L94–100) | `accepted`, `duplicate`, `invalid`, `batches`, `lookups` |

`ALLOWED_TYPES = {"click", "view", "purchase", "signup"}` (L13).
`InvalidEvent` (L16) is a `ValueError` used for all "bad event" signals.

## 1. Path of one event from `submit()` to the sink

`submit(raw)` (L143–166), in order:

1. **Closed check** (L145–146): if `_closed`, `raise RuntimeError("pipeline closed")` — a raise, not a return value.
2. **Stage 1 — parse** (`_parse`, L104–114, called at L148): `bytes` are decoded as UTF-8 (L106–107); `json.loads` (L109). `JSONDecodeError` → `InvalidEvent("not JSON")` (L110–111); a JSON value that is not an object (array, number, string, `null`) → `InvalidEvent("event must be an object")` (L112–113). On `InvalidEvent`: `stats["invalid"] += 1`, return `"invalid"` (L149–151). The event never reaches the dedupe window or any later stage.
3. **Stage 2 — duplicate check** (L152–154): `_window.seen((event.get("source"), event.get("id")))`. This runs *before* validation and on the raw parsed values (§2). On a hit: `stats["duplicate"] += 1`, return `"duplicate"` — the event is not validated, enriched, or buffered.
4. **Stage 3 — validate** (`_validate`, L116–125, called at L156): all of `source`, `id`, `type`, `ts`, `user_id` must be present (L118–120); `type` must be in `ALLOWED_TYPES` (L121–122); `ts` is parsed by `_parse_ts` (L60–70, applied at L124): it must be a `str` (L61–62), a trailing `"Z"` is rewritten to `"+00:00"` (L63), naive timestamps are assumed UTC (L68–69), and aware timestamps are normalized to UTC via `astimezone` (L70). The event dict is shallow-copied (L123) and its `ts` is **replaced by the UTC-aware `datetime`** (L124). On `InvalidEvent`: `stats["invalid"] += 1`, return `"invalid"` (L157–159).
5. **Stage 4 — enrich** (`_enrich`, L127–139, called at L160): consults the user cache (L129); on a miss calls `user_lookup(user_id)` (§3). `event["user"] = user` (L138) — `user` may be `None`.
6. **Stage 5 — buffer** (L161–163): `(event["ts"], self._arrival, event)` appended to `_buffer`; `_arrival += 1`; `stats["accepted"] += 1`.
7. **Auto-flush** (L164–165): if `len(_buffer) >= batch_size`, `self.flush()` runs *inside* `submit` (§5).
8. Return `"accepted"`.

Note that `"accepted"` means **buffered**, not delivered: the event reaches the
sink only when a later `flush` succeeds.

## 2. Duplicate detection

**What makes two events "the same".** The key is the tuple
`(event.get("source"), event.get("id"))` of *raw parsed JSON values* (L152).
Both must be present and equal, with no normalization:

- `id: "1"` (string) and `id: 1` (int) are **different** keys — both accepted (verified).
- But Python equality makes `1`, `1.0` and `True` the **same** key: after
  `id: 1` is submitted, `id: 1.0` → `"duplicate"`, and so does `id: true`
  (verified; `1 == 1.0 == True`, matching hashes).
- `type`, `ts`, and `user_id` are irrelevant to identity.

**How long the memory lasts.** Not time-based — it is an LRU-bounded set of
at most `dedupe_capacity` (default 1024) *distinct* keys. `_Window.seen`
(L27–34) is an `OrderedDict`:

- Hit → `move_to_end(key)` (L29), return `True`: a resubmitted duplicate
  **refreshes recency**, shielding the key from eviction.
- Miss → insert (L31); if the set then exceeds capacity,
  `popitem(last=False)` (L33) evicts the least-recently-seen key. Eviction
  happens only on new-key insertions.

So a key survives as long as it stays among the most recently seen
`dedupe_capacity` distinct keys; once evicted, resubmission is accepted and
the event is delivered a second time. Verified (capacity 2,
`submit(1), submit(2), dup(1), submit(3)`): the window ends as
`[(s,1),(s,3)]` — the duplicate of 1 kept 1 alive and evicted 2; resubmitting
1 → `"duplicate"`, resubmitting 2 → `"accepted"`.

**Edge cases in interactions with other stages:**

- **Dedupe runs before validation, and `seen()` registers the key either way**
  (L152 precedes L155). Consequences, all verified:
  - A second identical *invalid* submission returns `"duplicate"`, not
    `"invalid"`:
    ```python
    bad = '{"source":"web","id":"i9","type":"click","ts":"nope","user_id":1}'
    p.submit(bad)  # -> "invalid"   (bad ts)
    p.submit(bad)  # -> "duplicate" (key (web, "i9") already registered)
    ```
  - Malformed events consume LRU slots: each distinct invalid `(source, id)`
    can push out a legitimate event's entry.
  - Events missing *both* `source` and `id` all share the key `(None, None)`
    (the `.get()` calls at L152): any second such event, even a different one,
    is reported `"duplicate"`.
  - **Unhashable `source`/`id`** (JSON objects or arrays) make the key itself
    unhashable: `seen()` raises `TypeError("unhashable type: 'dict'")`, and
    L152 sits outside every `try/except` in `submit`, so the exception
    propagates out of `submit` instead of returning a status (verified). The
    same applies to an unhashable `user_id` (`_TtlCache.get` → `dict.get`,
    L129) and an unhashable `type` (membership test against the
    `ALLOWED_TYPES` frozenset, L121).
- **Dedupe precedes enrichment**: duplicates trigger no `user_lookup` (no
  `stats["lookups"]` increment, no cache entry) and invalid events do not
  reach the cache either — only accepted events can cause lookups.
- Dedupe is in-process only; a restarted pipeline forgets everything.

## 3. User-enrichment cache

**When a lookup happens.** Only for an event that survived parse + dedupe +
validate, and only on a cache miss: `_users.get(user_id)` (L129); a miss
increments `stats["lookups"]` (L131) and calls `user_lookup(user_id)` (L133).
A miss occurs when the user was never looked up, its entry expired, or its
lookup previously raised (next item).

**What is cached.** `_TtlCache.put` stores `(value, clock() + ttl)` keyed by
`user_id` (L56–57). The value is exactly what `user_lookup` returned —
**including `None`**: a `None` result *is* cached (verified: a lookup
returning `None` was called once for two events of the same user,
`stats["lookups"] == 1`). By contrast, a lookup that **raises** is *not*
cached — `put` sits in the `else` branch of the `try/except` (L134–137) — so
the next event for that user retries `user_lookup` immediately (verified: a
raising lookup was called once per event). Its exception is swallowed
(L134–135, "enrichment is best-effort") and the event is delivered with
`user = None`.

**When entries expire.** Lazily, on the next `get` for that user
(L46–54): an entry expires when `clock() >= put_time + enrich_ttl` (L51),
i.e. exactly `enrich_ttl` (default 300 s) after the most recent `put`
(verified with a fake clock, `ttl=300`, put at t=1000: cached at t=1299.9,
expired at t=1300.0). A cache hit does **not** refresh the deadline (no
sliding TTL). Expiry only removes entries for keys that get re-queried; the
cache dict itself is unbounded in size — it grows with the number of distinct
`user_id`s until entries expire. The clock is injectable (L43, L82), which is
how the tests control time.

## 4. Ordering

Buffered records are `(ts, arrival, event)` (L161); `arrival` is unique per
accepted event (L92, L161–162). At flush time the buffer is sorted with key
`(ts, arrival)` (L172). Therefore the sink gets:

- **Within a batch**: events ordered by normalized UTC event timestamp, ties
  broken by submission (acceptance) order. Verified: submitting
  `A(ts=00:02)` then `B(ts=00:01)` yields batch `[B, A]`.
- **Not** wall-clock submission order: a later-submitted event with an earlier
  `ts` precedes earlier-submitted ones (the same example above).
- **No cross-batch ordering**: batches close whenever the buffer fills
  (L164–165) or `flush()`/`close()` is called, so an earlier batch may contain
  *later* timestamps than a later batch. Verified with `batch_size=2`:
  batch 1 = `[ts 00:01:00, 00:02:00]`, then batch 2 =
  `[ts 00:00:10, 00:00:30]` — every event in batch 2 is older than every
  event in batch 1.
- `arrival` guarantees a total order inside a batch (it is unique per
  pipeline instance, so `(ts, arrival)` ties are impossible).
- Timestamp comparison is safe: all `ts` are normalized to UTC-aware
  `datetime`s in `_parse_ts` (L68–70), so no naive/aware mixing.
- The sort builds a new `list` per batch (L172); `_buffer` itself is not
  reordered, only cleared on success (L174).

## 5. When batches are sent; sink-failure semantics

**When:**

- Automatically in `submit` when the append brings `len(_buffer)` to
  `batch_size` (L164–165; the `>=` check means the buffer reaches exactly
  `batch_size` before each auto-flush, since `flush` clears it).
- Explicitly via `flush()` (L168–176): returns the number of events sent, or
  `0` for an empty buffer (L170–171).
- On `close()` (L178–180): `flush()` delivers any remainder, then `_closed`
  is set; later `submit`s raise `RuntimeError` (L145–146, verified).

**When the sink raises** (`self.sink(batch)`, L173):

- The exception **propagates** to the caller — of `flush()`, of `submit()`
  (when the auto-flush at L164–165 fires), or of `close()`. There is no
  catch, retry, or fallback in the module.
- **Events are not lost**: `_buffer.clear()` (L174) and
  `stats["batches"] += 1` (L175) execute only *after* the sink call returns.
  On failure the whole batch stays in `_buffer` and is re-sent — together
  with any events appended in the meantime — by the next successful flush.
  Verified with `batch_size=2` and a sink that fails once: after the raising
  auto-flush, `pending() == 2`, `stats["accepted"] == 2`,
  `stats["batches"] == 0`; the next successful flush delivered the two
  retained events plus one new one (ids `[1, 2, 3]`).
- Consequence for counters: `stats["accepted"]` counts *buffered* events,
  `stats["batches"]` counts *successful deliveries* — after a sink failure
  `accepted` exceeds what has been delivered until a later successful flush.
  A persistently failing sink leaves events piling up in `pending()`.
- In `close()`, a raising final flush leaves `_closed` **False** and the
  buffer intact — the pipeline is still usable (verified: `submit` after a
  failed `close()` returns `"accepted"`).
- If the sink *partially* applies a batch and then raises, that same batch
  (plus any new events) is delivered again on the next flush: the sink must
  tolerate duplicates.

## 6. Surprising behaviours (all verified by running the module)

1. **`submit` can raise instead of returning a status**, even for "bad
   input":
   - Non-`str`/`bytes` raw values: `json.loads(123)` raises `TypeError`, but
     `_parse` only catches `json.JSONDecodeError` (L108–111) — so
     `submit(123)` and `submit(None)` raise `TypeError` (verified).
   - Unhashable `source`/`id`/`type`/`user_id` (JSON objects/arrays) raise
     uncaught `TypeError`s from `seen()` (L152), the `ALLOWED_TYPES`
     membership test (L121), or `dict.get` (L129) (verified).
   - A raising sink during the auto-flush propagates out of `submit`
     (L164–165).
   - `submit` after `close()` raises `RuntimeError` (L145–146).
2. **`"accepted"` ≠ delivered** — it means "buffered"; delivery happens only
   at a later successful flush (§5).
3. **`ts` changes type on the way to the sink**: the module docstring says
   events carry an ISO-8601 `ts` (L1–6), but the delivered dict contains a
   UTC-aware `datetime` (L124, L70) — e.g. `"2026-06-01T12:00:00+02:00"`
   arrives as `2026-06-01 10:00:00+00:00`. JSON-serializing a batch needs a
   datetime-aware encoder.
4. **Dedupe-before-validate interactions**: malformed events occupy dedupe
   slots; a resubmitted malformed event reports `"duplicate"` (not
   `"invalid"`); events missing both `source` and `id` collide on
   `(None, None)` (§2).
5. **Dedupe keys are raw JSON values**: `1`, `1.0`, and `true` collide, while
   `"1"` and `1` do not (§2).
6. **Dedupe is LRU, not time-based**: a "duplicate" older than
   `dedupe_capacity` distinct keys is re-accepted and re-delivered (§2).
7. **Asymmetric negative caching**: a `user_lookup` returning `None` is cached
   for the full TTL (no retry); a raising `user_lookup` is retried on every
   event and its exception is silently swallowed (§3).
8. **A failed `close()` leaves the pipeline open** and its buffer intact
   (§5).
9. **Unbounded user cache**: `_TtlCache._data` grows with distinct
   `user_id`s; entries are only removed when re-queried after expiry (§3).
10. **No concurrency protection**: there are no locks; `_arrival`,
    `_buffer`, and the caches assume a single calling thread.