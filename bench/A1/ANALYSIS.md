# A1 — Ingest pipeline data flow

Source: `bench/A1/src/ingest/pipeline.py` (183 lines). All line numbers refer to this file.

## 1. Path of one event from `submit()` to the sink

`IngestPipeline.submit(raw)` (L143) processes one raw event through five stages:

1. **Closed check** (L145–146): if `self._closed` is set, raise `RuntimeError("pipeline closed")`.
2. **Parse** — `_parse(raw)` (L105–114, called at L148): `bytes` input is decoded as strict UTF-8 (L106–107); `json.loads` (L109). Bad JSON → `InvalidEvent("not JSON")` (L110–111); JSON that is not an object (list, number, string, null) → `InvalidEvent("event must be an object")` (L112–113). `submit` catches only `InvalidEvent` (L149): increments `stats["invalid"]` (L150) and returns `"invalid"`.
3. **Dedup** (L152–154): key is `(event.get("source"), event.get("id"))` (L152). If `_Window.seen()` reports the key as seen, increment `stats["duplicate"]` (L153) and return `"duplicate"`. On a first sighting the key is registered in the window (L31) before processing continues.
4. **Validate** — `_validate(event)` (L117–125, called at L156): `source`, `id`, `type`, `ts`, `user_id` must all be present (L118–120); `type` must be in `ALLOWED_TYPES` = {`click`, `view`, `purchase`, `signup`} (L13, checked at L121). A shallow copy is made (L123) whose `ts` string is replaced by a `datetime` via `_parse_ts` (L124; L60–70): non-string `ts` → `InvalidEvent` (L62); trailing `Z` is rewritten to `+00:00` (L63); naive timestamps are assumed UTC (L68–69); all results are normalised to UTC (L70). Failure → `stats["invalid"]` (L158), return `"invalid"`.
5. **Enrich** — `_enrich(event)` (L127–139, called at L160): resolves the user for `event["user_id"]` through the TTL cache (see §3) and always sets an added `user` key (L138) to the user dict or `None`.

The event is then buffered (L161): `self._buffer.append((event["ts"], self._arrival, event))` with `self._arrival += 1` (L162) — a per-pipeline monotonic counter that increments only for accepted events — and `stats["accepted"] += 1` (L163). If `len(self._buffer) >= self.batch_size` (default 100, L79), `flush()` is called inline (L164–165). `submit` returns `"accepted"` (L166).

The event reaches the sink only when `flush()` runs (L168–176): it builds a sorted copy of the buffer (L172, see §4), calls `self.sink(batch)` (L173; sink interface is `sink(batch: list[dict])`, L84), clears the buffer (L174), increments `stats["batches"]` (L175), and returns the batch size (L176). `close()` (L178–180) calls `flush()` and then sets `_closed = True`.

Note: the dict delivered to the sink is the validated+enriched dict: `ts` is now a `datetime`, a `user` key has been added, and any extra fields from the raw JSON are preserved.

## 2. Duplicate detection

- **What makes events "the same"**: equality of the `(source, id)` pair, taken via `event.get()` so a missing field contributes `None` (L152). `ts`, `type`, `user_id` and extra fields are ignored — a resend with a different timestamp is still a duplicate. The comparison is type-sensitive (`"id": 1` ≠ `"id": "1"`).
- **How long the memory lasts**: `_Window` (L20–37) is a capacity-bounded LRU over an `OrderedDict`, not time-based. First sightings insert the key (L31); when the window holds more than `dedupe_capacity` keys (default 1024, L80/89) the oldest key is evicted (L32–33); a hit refreshes the key's position (L29). A key is therefore remembered until the pipeline object dies or the key is evicted by 1024+ other distinct `(source, id)` keys — there is no TTL. A resent event whose key was evicted is accepted again and delivered to the sink a second time.
- **Edge cases**:
  - **Ordering with validation**: the window check (L152) runs *before* `_validate` (L156), yet the key is registered during the first `seen()` call (L31). So an event that parses as a JSON object but fails validation still consumes a dedupe slot: the first send returns `"invalid"`, and every later identical send returns `"duplicate"` instead. Example: submit `{"source":"web","id":1,"type":"fly","ts":"2026-01-01T00:00:00Z","user_id":1}` → `"invalid"`; resend the same → `"duplicate"`.
  - Two events that both lack `source` and `id` share the key `(None, None)` (e.g. `{"x":1}` twice: first `"invalid"` — missing `source` — second `"duplicate"`).
  - The key must be hashable: if `source` or `id` is a list or dict, `key in self._keys` (L28) raises `TypeError: unhashable type`, which propagates out of `submit` — it is not reported as `"invalid"`.
  - Duplicates are dropped before enrichment and buffering, so they trigger no `user_lookup` calls and are never delivered.

## 3. User-enrichment cache

- **When a lookup happens**: `_enrich` (L127) runs synchronously inside `submit()` for every event that passes validation, keyed by `event["user_id"]` (L128). On a cache miss or expiry, `stats["lookups"]` increments (L131) and `self.user_lookup(uid)` is called (L133).
- **What is cached**: `_TtlCache.put` (L56–57) stores `(value, clock() + enrich_ttl)` where `value` is whatever `user_lookup` returned. A successful lookup that returns `None` (unknown user) is cached too — the `else` branch (L136–137) runs regardless of value — so later events for that user get `user: None` with no further lookups for the full TTL (negative caching). An *exception* from `user_lookup` is swallowed (L134–135, "enrichment is best-effort"): the event is accepted with `user: None` and the failure is *not* cached — every subsequent event for that user retries the lookup and re-increments `stats["lookups"]`.
- **When entries expire**: an entry expires when `clock() >= put_time + ttl` (L51), checked lazily on `get` only (L46–54); an expired entry is deleted when hit (L52) but never garbage-collected otherwise. `ttl` defaults to 300.0 s (L81); `clock` defaults to `time.monotonic` (L82) and is injectable. TTL is measured from the last successful lookup, not the last access (hits do not refresh expiry). The cached user dict is stored by reference, so every event for the same user within the TTL shares the same dict object — the same object the sink receives (see §6).

## 4. Ordering

The buffer holds `(ts, arrival_seq, event)` triples (L161). `flush()` sorts by `(ts, arrival_seq)` (L172):

- **Within a batch**: events are delivered in event-`ts` order, with ties broken by arrival order (submission order among accepted events). An event that arrives late but carries an early `ts` moves to the front of the batch. Example (`batch_size=2`): submit `ts=10:00` then `ts=09:00` → the batch arrives as `[09:00, 10:00]`.
- **Across batches**: no global `ts` order. Batches are sent in flush order, so a `09:00` event arriving after an earlier batch was sent is delivered in a later batch, after `10:00`–`12:00` events.
- `arrival_seq` counts only accepted events (L162), giving a deterministic total order for equal-`ts` events.

## 5. When batches are sent; sink-failure behaviour

Batches are sent in exactly three situations:

1. The buffer reaches `batch_size` (default 100) — inline in the `submit()` that pushed it over the threshold (L164–165).
2. An explicit `flush()` call (L168) — drains the current buffer; returns 0 and sends nothing when empty (L170–171).
3. `close()` (L178–180) — flushes the remainder, then marks the pipeline closed (further `submit()` raises `RuntimeError`, L145–146).

There is no timer: with defaults, events can sit in the buffer indefinitely until 100 are buffered, `flush()`, or `close()`.

**If `sink(batch)` raises (L173)**:

- `self._buffer.clear()` (L174) and `stats["batches"] += 1` (L175) do not run: all buffered events — including the one that triggered the flush — stay in the buffer and are re-sent on the next successful flush. If the sink partially processed the batch, it receives those events again; if the process dies before the next flush the events are lost (the buffer is in-memory only — no persistence).
- The exception propagates to the caller of `flush()`. If the flush was triggered inline by `submit()`, the caller gets the exception instead of `"accepted"` — although `stats["accepted"]` was already incremented (L163) and the event remains buffered.
- If triggered by `close()`, the exception propagates out of `close()` *before* `self._closed = True` (L180) runs: the pipeline is still open, the buffer is still full, and a later `flush()`/`close()` retries delivery.

## 6. Surprising behaviours

1. **Invalid events occupy a dedupe slot** (§2): after a validation failure, resending the same `(source, id)` returns `"duplicate"`, not `"invalid"`.
2. **Malformed input can crash `submit`**: non-UTF-8 `bytes` raises `UnicodeDecodeError` (L107, outside the `InvalidEvent`-only catch at L149); an unhashable `source`/`id` raises `TypeError` (L28/L152). Neither is reported as `"invalid"`.
3. **`"accepted"` means "buffered", not "delivered"**: acceptance only means the event entered the in-memory buffer; a crash before the next `flush()`/`close()` loses buffered events.
4. **A sink exception does not drop events** (§5): they are re-sent on the next flush, so a partially-processed batch can be delivered twice.
5. **`close()` can fail to close**: if its `flush()` raises, `self._closed = True` (L180) is skipped and the pipeline stays open; a double `close()` in the normal path is harmless (second `flush()` returns 0).
6. **The sink gets a mutated dict**: `ts` is a `datetime`, not the original string; a `user` key was added; the same `user` dict object is shared across all events for a user within the TTL — sink-side mutation corrupts the cache.
7. **Negative caching vs retry**: an unknown user (`user_lookup` → `None`) is cached for the full TTL, but a failing `user_lookup` (exception) is retried on every event.
8. **Dedupe is capacity-LRU, not TTL**: after 1024+ distinct `(source, id)` keys have passed through, an old key is forgotten and a resend is accepted again.
9. `batch_size=0` flushes on every submit (`len(buffer) >= 0` is always true, L164).
10. `stats` semantics: `accepted` counts buffer insertions (including events later re-delivered after a sink failure); `batches` counts successful `sink` calls; `lookups` counts `user_lookup` invocations (misses/expiries), not events.