# Review of PR #1 — notify service (per-locale templates, timeout in ms, request logging)

Review of branch `review/pr-1` against `bench-v1` (the `bench-v1` tag and the branch
base are the same commit, `04266e8`). Public tests pass on both sides (18 on the PR,
15 on base). All findings below are verified against the post-change files and are
reproducible against the documented contracts in the module docstrings.

The PR is a mixed bag: the new `get_localized` template helper and the dedupe
simplification are fine, but it introduces **one critical batch-stopping bug, a
security issue, and two behavioral regressions** that break the service's documented
contracts. Details follow.

---

## Finding 1 — Webhook-less user aborts the whole batch (early `return`)

- **Location:** `bench/R1/src/notify/service.py:43` (inside `NotificationService.notify`)
- **Severity:** `critical`
- **Category:** `bug`

### Explanation
The new branch for webhook-less users ends with `return summary` instead of
`continue`:

```python
if not user.webhook_url:
    summary.skipped.append(uid)
    return summary        # <-- aborts the batch
```

The docstring for `notify` states that skipped users "never stop the rest of the
batch", and the base implementation used `continue` so delivery proceeded for every
remaining user. With this change, the *first* user in the batch who has no
`webhook_url` silently stops delivery to every user that comes after them.

Concrete consequence (reproduced with the PR code, `notify([1, 2, 3])` where user 2
has no webhook):

```
summary => sent=1, failed=0, skipped=[2]
```

User 3 (a valid, webhook-bearing user) is **never notified**, and the returned
`Summary` no longer reflects the whole batch. In a production batch where any
inactive/webhook-less account appears before active ones, a large fraction of
recipients silently miss the notification.

**Suggested fix:** replace `return summary` with `continue` so the loop proceeds to
the next user, matching the documented contract.

---

## Finding 2 — API token (Authorization header) written to the log

- **Location:** `bench/R1/src/notify/webhook.py:56` (inside `WebhookSender.send`)
- **Severity:** `high`
- **Category:** `security`

### Explanation
The new logging line dumps the full request headers at `INFO` level:

```python
logger.info("POST %s headers=%s", url, headers)
```

`headers` (built in `_headers`) contains
`{"Authorization": "Bearer <api_token>", "X-Signature": "sha256=...", ...}`. So the
raw bearer **API token** is written verbatim into the application log for every
delivery. Reproduced with the PR code:

```
POST u headers={'Authorization': 'Bearer SECRET_TOKEN_abc123', 'Content-Type': 'application/json', 'X-Signature': 'sha256=deadbeef'}
```

This is a credentials leak: anyone with log access (log aggregators, SaaS log
vendors, rotated/retained files) obtains the live API token. It also contradicts the
module docstring's contract that only the body's HMAC signature is meant to be
externally verifiable — the token itself is never supposed to leave the process.

**Suggested fix:** do not log the `Authorization` header (or any headers containing
credentials). Either log a redacted representation, e.g.
`logger.info("POST %s", url)`, or explicitly drop the `Authorization`/signature
fields before logging.

---

## Finding 3 — Timeout conversion is off by 10x (`/100` instead of `/1000`)

- **Location:** `bench/R1/src/notify/config.py:32` (inside `Settings.from_env`)
- **Severity:** `high`
- **Category:** `bug`

### Explanation
The PR renames `NOTIFY_TIMEOUT` (seconds) to `NOTIFY_TIMEOUT_MS` (milliseconds) and
converts to seconds, but divides by `100` instead of `1000`:

```python
timeout=float(env.get("NOTIFY_TIMEOUT_MS", 5000)) / 100,
```

`5000 ms` therefore yields `timeout=50.0` seconds rather than the intended `5.0`.
Verified with the PR code: `Settings.from_env({"NOTIFY_API_TOKEN": "x",
"NOTIFY_TIMEOUT_MS": "5000"}).timeout == 50.0`.

Consequences:
- The HTTP request timeout is **10x longer than documented** (5s → 50s). Against a
  slow or hung endpoint, each attempt (and each of up to `max_attempts` attempts with
  backoff) can hang far longer than intended, stalling the whole batch beyond the
  documented budget.
- The new test `test_settings_timeout_ms` only asserts `s.timeout > 0`, which passes
  for `50.0` and masks the incorrect factor.

**Suggested fix:** divide by `1000` so milliseconds convert to seconds
(`... / 1000`), and tighten the test to assert the expected value (`== 5.0`).

---

## Finding 4 — 500-status responses are no longer retried

- **Location:** `bench/R1/src/notify/webhook.py:49` (`_should_retry`)
- **Severity:** `medium`
- **Category:** `bug`

### Explanation
The retry predicate changed from `status >= 500` to `status > 500`:

```python
return status == 429 or status > 500
```

This excludes exactly `500` (Internal Server Error). The module docstring contract
states *"any 5xx status"* is retryable, so `500` should be retried but is now
treated as a final failure. Verified with the PR code: a `500`-then-`200` sequence
yields `ok=False, attempts=1` (final), whereas the base retried it to
`ok=True, attempts=2`. `501` and above (e.g. `503`) still retry correctly, so only
the `500` case is affected.

Consequence: transient `500` responses (common for flaky upstreams) cause a delivery
to be reported as a permanent failure when a retry would likely have succeeded.

**Suggested fix:** restore `status >= 500` (i.e. `status == 429 or status >= 500`).

---

## Finding 5 — Per-user directory lookups replace the batch lookup (N round-trips)

- **Location:** `bench/R1/src/notify/service.py:37` (inside `NotificationService.notify`)
- **Severity:** `low`
- **Category:** `performance`

### Explanation
The base code resolved the whole batch with a single call,
`users = self.directory.get_many(ids)` (one round-trip). The PR instead calls
`self.directory.get(uid)` inside the loop, once per distinct user. The `users.py`
docstring explicitly documents this: *"in production each lookup is a DB
round-trip, so `queries` counts round-trips and callers should prefer the batch
`get_many` over repeated `get` calls."*

Verified: for a 3-user batch the PR issues 3 `get` round-trips versus 1 for the base
`get_many` (one call for the whole batch). For a batch of N users this is an N-fold
increase in directory round-trips (O(N) instead of O(1)).

This is a correctness-neutral performance regression that directly contradicts the
documented guidance, and it becomes noticeable as batch size grows.

**Suggested fix:** restore the batch lookup (`get_many`) and iterate over the
returned mapping, as the base did.

---

## Notes (non-issues / verified correct)

- **`templates.get_localized`** (`bench/R1/src/notify/templates.py:28-30`): correct.
  `self._templates.get(f"{name}.{locale}") or self.get(name)` prefers the localized
  template and falls back to the default; the `or` also handles a stored empty
  string, and `get` still raises `KeyError` for a truly unknown base template.
- **`_dedupe`** (`service.py:24`): `list(dict.fromkeys(user_ids))` preserves
  first-seen order and drops repeats; equivalent to the base for hashable ids and
  covered by `test_dedupe_keeps_first_seen_order`.
- **Backoff schedule** (`webhook.py:57-71`): `range(max_attempts)` with the delay
  `base_delay * 2 ** (attempt - 1)` for `attempt >= 1` reproduces the documented
  schedule (base, 2·base, 4·base, …) with at most `max_attempts` total attempts, and
  the `attempts` counter is reported correctly (`attempt + 1` compensates the
  zero-based loop).

---

## Verdict

`request changes`

The PR must address Finding 1 (batch-stopping early return) and Finding 2 (API token
leaked to logs) before merge; Findings 3 and 4 (timeout factor, 500 not retried) and
Finding 5 (N directory round-trips) should also be fixed as they regress the
documented contracts.