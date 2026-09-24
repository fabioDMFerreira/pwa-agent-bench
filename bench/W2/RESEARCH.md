# W2 — Retry Library Selection: tenacity vs backoff vs stamina

**Context.** `ledger-sync` is an asyncio service (Python 3.12) that calls a
flaky partner HTTP API through `httpx.AsyncClient`. Today every call site has
a hand-rolled `for attempt in range(3): … await asyncio.sleep(1)` loop. This
document compares **tenacity**, **backoff** and **stamina** against the
requirements in `TASK.md` (R1–R6), recommends one library, and lays out an
adoption plan.

*All facts below were verified against primary sources on **2026-09-24**
(see [Sources](#5-sources)). Access date for every URL: 2026-09-24.*

---

## 1. Comparison table

| Criterion | **tenacity** 9.1.4 | **backoff** 2.2.1 | **stamina** 26.1.0 |
|---|---|---|---|
| Latest release | 9.1.4 — 2026-02-07 [1][3] | 2.2.1 — 2022-10-05 [4][5] | 26.1.0 — 2026-04-13 [6][7] |
| Licence | Apache-2.0 [1][3] | MIT [4][5] | MIT [6][7] |
| Repo status | Active (pushed 2026-09-01) [2] | **Archived** (last push 2024-05-02) [8] | Active (pushed 2026-09-07) [9] |
| Python support | ≥3.10 (classifiers 3.10–3.14) [1][3] | ≥3.7,<4.0 (classifiers only 3.7–3.10) [4][5] | ≥3.10 (classifiers 3.10–3.14) [6][7] |
| Async (asyncio) | Yes — `tenacity.asyncio.retry`, coroutine support, trio-aware sleep [10][11] | Yes — decorator wraps coroutines; `await asyncio.sleep` [5][12][13] | Yes — auto-detects async coroutines (asyncio **and** Trio); same `@stamina.retry` API [14][15] |
| Jitter | Yes — `wait_exponential_jitter`, `wait_random_exponential`, `wait_random`, `wait_combine` [16] | Yes — default `full_jitter` (AWS "Full Jitter"); `random_jitter` alternative [5] | Yes — default backoff = `min(wait_max, wait_initial·2ⁿ + random(0, wait_jitter))` [17][18] |
| Test mode | Supported: injectable `sleep=` strategy + `enabled=False` short-circuit [19][20][21] | **No** dedicated mechanism; sleeps are hard-coded `time.sleep` / `await asyncio.sleep` [13][22] | **Dedicated API**: `stamina.set_testing()` (no backoff, capped attempts) and `stamina.set_active(False)` (globally disables retries) [23][24][25] |
| Typing (`py.typed`) | Yes — `py.typed` in wheel; typed overloads incl. `ParamSpec` [26] | Yes — `py.typed` + `types.py` in wheel [27] | Yes — `py.typed`; preserves decorated signatures (`Callable[P, T]`); hints checked with Pyrefly/ty [28][29][30] |
| Runtime deps | **None** [1][3] | **None** [4][5] | **tenacity** (transitively → tenacity; nothing else) [6][7] |

Legend: numbers refer to the [Sources](#5-sources) list.

### Notes on specific cells

- **tenacity async**: `tenacity.asyncio.retry` is the documented async
  decorator ("Retry code until it succeeds" / "Retry on coroutines")
  [10][11]; the sleep strategy is trio-aware and lazily falls back to
  `asyncio.sleep` [11].
- **backoff async**: "Backoff supports asynchronous execution in Python 3.5
  and above… apply `backoff.on_exception` or `backoff.on_predicate` to
  coroutines" [5]. Internally it calls `await asyncio.sleep(seconds)`
  [13].
- **stamina async**: the tutorial shows `@stamina.retry(on=…, attempts=3)`
  used directly on an `async def` calling `httpx.AsyncClient`; async and
  Trio are both supported out of the box [14][15].
- **stamina test mode** is a first-class, documented API — the only one of
  the three that is not "just monkeypatch the sleep" [23][24].
- **backoff Python support**: `requires_python >=3.7,<4.0`; the
  `Programming Language` classifiers only list 3.7–3.10, so 3.12 is not
  *declared* in the metadata even though the pure-Python code runs there
  [4][5].

---

## 2. Evaluation against R1–R6

### R1 — Retry `async def`; retry only on `httpx.TransportError` and 5xx/429 `httpx.HTTPStatusError`

| Library | Verdict |
|---|---|
| **tenacity** | ✅ `tenacity.asyncio.retry` retries coroutines; `retry=retry_if_exception_type(httpx.TransportError)` or a custom `Retry` predicate (e.g. `retry_if_exception(lambda e: isinstance(e, httpx.TransportError) or (isinstance(e, httpx.HTTPStatusError) and (e.response.status_code == 429 or e.response.status_code >= 500)))`). Very explicit but verbose [10][11]. |
| **backoff** | ✅ Wrap the coroutine; `exception=(httpx.TransportError, httpx.HTTPStatusError)` plus a `giveup=` predicate that returns True for non-5xx/429 status codes. Works, but `giveup` inverts the logic (it decides when *not* to retry), which is error-prone [5][12]. |
| **stamina** | ✅ Cleanest fit. `on=` accepts an exception *or a backoff hook* — a callable `(exc) -> bool` that decides retryability. The docs use exactly our shape: `HTTPStatusError` → retry only when `status_code >= 500` [14][17][18]. A hook `lambda e: isinstance(e, httpx.TransportError) or (isinstance(e, httpx.HTTPStatusError) and (e.response.status_code >= 500 or e.response.status_code == 429))` is a one-liner. |

### R2 — Exponential backoff **with jitter**, cap on total attempts **and** total time

| Library | Verdict |
|---|---|
| **tenacity** | ✅ `wait=wait_exponential_jitter(...)` (jittered) [16]; `stop=stop_any(stop_after_attempt(N), stop_after_delay(T))` caps both attempts and wall time [21]. |
| **backoff** | ✅ `backoff.expo` + default `full_jitter`; `max_tries=` caps attempts, `max_time=` caps total time [5]. |
| **stamina** | ✅ Defaults already match: exponential + jittered, `attempts=10` cap **and** `timeout=45.0` (s) cap. Both knobs configurable; `wait_initial/wait_max/wait_jitter/wait_exp_base` tunable [17][18]. |

### R3 — Fast tests: a supported way to disable/short-circuit retry waits (not just monkeypatching `asyncio.sleep`)

| Library | Verdict |
|---|---|
| **tenacity** | ⚠️ Partially. Two supported mechanisms: (a) pass a no-op `sleep` strategy (the sleep is an injectable callable — the sync default is documented "may be mocked out for unit testing" [20], and the release notes add "allow mocking of nap/sleep" [22]); (b) `enabled=False` short-circuits to a single call [19][21]. Both work, but they are *per-decorator* configuration, not a global test switch — you must remember to build the decorator differently in tests (e.g. a factory function). |
| **backoff** | ❌ No supported test hook. Sleep is hard-coded `time.sleep` / `await asyncio.sleep` [13]; `on_predicate`/`on_exception` have no "fast mode". You are back to monkeypatching `asyncio.sleep`/`time.sleep`, which R3 explicitly excludes. |
| **stamina** | ✅ Best-in-class, documented test API: `stamina.set_testing(True)` → "no backoff, 1 attempt" (attempts cap configurable), and `stamina.set_active(False)` → retries off entirely. Idempotent; usable as a context manager since 25.1.0 [23][24][25]. A single autouse pytest fixture short-circuits the whole suite. |

### R4 — `py.typed` shipped (we run `mypy --strict`)

| Library | Verdict |
|---|---|
| **tenacity** | ✅ `tenacity/py.typed` present in the 9.1.4 wheel; public API typed with `ParamSpec`/`TypeVar` overloads; `AsyncRetrying.retry_with`/`_RetryDecorated` protocols handle decorated methods [26]. |
| **backoff** | ✅ `backoff/py.typed` present in 2.2.1; dedicated `types.py`. However the package's classifiers stop at Python 3.10, and it has received no type-system updates since 2022-10-05 (e.g. before PEP 695/`py.typed` ecosystem changes) [27]. |
| **stamina** | ✅ `stamina/py.typed` present; `retry` returns `Callable[[Callable[P, T]], Callable[P, T]]` so decorated signatures survive; public-API hints are machine-checked with Pyrefly and `ty` (added 25.2.0) [28][29][30]. |

### R5 — Permissive licence only (MIT, BSD, Apache-2.0)

| Library | Verdict |
|---|---|
| **tenacity** | ✅ Apache-2.0 [1][3]. |
| **backoff** | ✅ MIT [4][5]. |
| **stamina** | ✅ MIT [6][7]. (Its only runtime dependency, tenacity, is also permissive — Apache-2.0 [1][3].) |

### R6 — Not archived/unmaintained; release within last 12 months

| Library | Verdict |
|---|---|
| **tenacity** | ✅ Not archived; repo pushed 2026-09-01; 9.1.4 released 2026-02-07 (≈ 7.5 months ago) [1][2][3]. |
| **backoff** | ❌ **Fails.** The GitHub repository is **archived** (read-only; last push 2024-05-02) and the latest release (2.2.1) dates to **2022-10-05** — nearly 4 years ago [4][5][8]. Open bugs (e.g. #223, wrong exception handling in `_async.py`, open since 2025-01-18) confirm no maintenance [31]. |
| **stamina** | ✅ Not archived; repo pushed 2026-09-07; 26.1.0 released 2026-04-13 (≈ 5.5 months ago) [6][7][9]. |

### Scorecard

| Requirement | tenacity | backoff | stamina |
|---|---|---|---|
| R1 async + selective exceptions | ✅ (verbose) | ✅ (via inverted `giveup`) | ✅ (backoff hook — purpose-built) |
| R2 backoff+jitter, attempt & time caps | ✅ | ✅ | ✅ (correct defaults out of the box) |
| R3 fast-test support | ⚠️ (per-decorator `sleep`/`enabled`) | ❌ (none) | ✅ (global `set_testing`/`set_active`) |
| R4 `py.typed` for mypy --strict | ✅ | ⚠️ (stale since 2022) | ✅ |
| R5 permissive licence | ✅ Apache-2.0 | ✅ MIT | ✅ MIT |
| R6 maintained, released < 12 mo | ✅ | ❌ **archived** | ✅ |

**backoff is disqualified by R6 alone** and additionally fails R3.
tenacity passes everything but R3 only *partially*. stamina passes all six.

---

## 3. Recommendation

**Recommended: `stamina` (26.1.0).**
**Runner-up: `tenacity` (9.1.4).**

### Why stamina

1. **Meets every requirement, including the two that disqualify the others.**
   It is the only candidate that passes R3 (dedicated, documented test-mode
   API [23][24]) and R6 (active repo, release within 12 months [6][7][9]).
   backoff fails both; tenacity passes R6 but only partially satisfies R3.
2. **Purpose-built for our exact use case.** The R1 exception-filtering
   requirement is a *backoff hook* in stamina's API — `on=` takes a
   `Callable[[Exception], bool | float | timedelta]`. The official tutorial
   demonstrates retrying an `httpx` call on 5xx only, which is literally our
   R1 [14][17]. In tenacity you must hand-assemble a `Retry` predicate; in
   backoff you must invert the logic with `giveup=`.
3. **Sane, production-grade defaults.** Exponential backoff *with jitter*
   capped at 5 s per wait, 10 attempts, 45 s total — "the right thing by
   default", minimising the chance of thundering herds / cascading failures
   [15][17][18]. For `ledger-sync` we can keep the defaults or tune per
   endpoint.
4. **First-class async.** The same `@stamina.retry` works for `async def`
   (and Trio), no separate async API to learn [14][15].
5. **mypy --strict friendly.** Shipped `py.typed`, signature-preserving
   `Callable[P, T]` decorator, and the public API's hints are themselves
   checked with two independent type checkers (Pyrefly, `ty`) [28][29][30].
6. **Testability is a design goal, not an afterthought.** One autouse fixture
   makes the whole suite fast and deterministic (see §4) [23][24].
7. **Operational extras we get for free:** Prometheus / structlog / logging
   retry instrumentation [29] — useful for a service that retries a partner
   API.

### Why not the others

- **backoff**: repository is **archived** and the last release was 2022-10-05
  → violates R6 outright; it also has no test-mode hook (R3). It is a
  fine *historical* library but the wrong choice for new adoption.
- **tenacity** (runner-up): fully viable — permissive, typed, maintained,
  async, jittered backoff, and injectable sleep + `enabled=False` for tests.
  It loses to stamina only on R3 ergonomics (per-decorator test configuration
  rather than a global switch) and on the verbosity of its retry predicate.
  **If we ever need tenacity's low-level composability** (custom `stop`/`wait`
  strategies, `retry_error_callback`, tornado support), tenacity remains the
  fallback — and stamina is built on top of it anyway [7][14].

> Note: stamina's one runtime dependency *is* tenacity [6][7], so choosing
> stamina does not foreclose ever using tenacity directly elsewhere.

---

## 4. Adoption plan

### 4.1 Adding the dependency

```toml
# pyproject.toml
[project]
dependencies = [
    "httpx>=0.27",
    "stamina>=26.1.0",   # brings tenacity transitively
]
```

(No code changes to existing code until the rollout steps below.)

### 4.2 Call-site migration — one before/after example

**Before** (today's hand-rolled loop, per call site):

```python
import asyncio
import httpx


async def fetch_balance(client: httpx.AsyncClient, account_id: str) -> dict:
    url = f"{PARTNER_BASE}/accounts/{account_id}/balance"
    for attempt in range(3):
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if not _is_retryable(exc):          # hand-rolled 5xx/429 check
                raise
            if attempt == 2:
                raise
            await asyncio.sleep(1)
```

**After** (stamina):

```python
import httpx
import stamina


def _is_retryable(exc: Exception) -> bool:
    """R1: retry TransportError, and HTTPStatusError only for 5xx/429."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return False


@stamina.retry(
    on=_is_retryable,          # backoff hook: retry only R1 exceptions
    attempts=5,                # R2: cap on total attempts
    timeout=30.0,              # R2: cap on total time (s)
    wait_initial=0.5,          # R2: exponential backoff with jitter…
    wait_max=5.0,
    wait_jitter=1.0,
)
async def fetch_balance(client: httpx.AsyncClient, account_id: str) -> dict:
    url = f"{PARTNER_BASE}/accounts/{account_id}/balance"
    resp = await client.get(url)
    resp.raise_for_status()
    return resp.json()
```

Notes:

- `on=_is_retryable` is the *backoff hook* form — stamina calls it with the
  raised exception and retries only when it returns `True` [14][17]. It
  implements R1 exactly. (The hook may also return a `float`/`timedelta` to
  honour a `Retry-After` header [14].)
- `attempts` caps total attempts and `timeout` caps total wall time (R2);
  backoff is exponential with jitter by default (R2) [17][18].
- Type hints are preserved, so `fetch_balance` still type-checks under
  `mypy --strict` (R4) [28][29].
- If a 429 carries a `Retry-After` header, `_is_retryable` can return that
  value (as seconds) to drive a custom backoff instead of the default [14].

### 4.3 Test setup (R3)

Add an autouse fixture so the whole suite runs without real backoffs. Two
supported levels [23][24][25]:

```python
# tests/conftest.py
import pytest
import stamina


@pytest.fixture(autouse=True)
def no_retries_in_tests():
    """Globally disable retries for the test suite (fast + deterministic)."""
    stamina.set_active(False)
    yield
    stamina.set_active(True)
```

Or, when a test *wants* to exercise the retry loop without real waits
(`stamina.set_testing` turns backoff off and caps attempts — default 1; can
also be used as a context manager) [23][24][25]:

```python
import asyncio

import httpx
import pytest
import stamina


def test_retries_429_then_succeeds():
    calls = 0

    async def flaky():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.HTTPStatusError(
                "429 Too Many Requests",
                request=httpx.Request("GET", "https://partner.example/api"),
                response=httpx.Response(429, request=...),
            )
        return "ok"

    with stamina.set_testing(True, attempts=3):   # no backoff, ≤3 attempts
        retried = stamina.retry(on=_is_retryable)(flaky)
        assert asyncio.run(retried()) == "ok"
        assert calls == 2
```

This is a *supported* short-circuit — not monkeypatching `asyncio.sleep` —
exactly as R3 asks [23][24].

### 4.4 Rollout steps

1. **Add `stamina`** to `pyproject.toml` (4.1) and install. Confirm
   `mypy --strict` is happy with a small pilot module (R4).
2. **Land the test harness** (4.3) — the autouse fixture — ahead of any
   migration so every new test is fast by default.
3. **Migrate one low-risk endpoint end-to-end** (e.g. `fetch_balance`),
   keeping the old loop behind a feature flag if desired. Run the full suite
   plus a soak against the partner API's staging.
4. **Migrate the remaining call sites** in small batches, each with a code
   review focused on: correct `on=` hook (R1), sane `attempts`/`timeout`
   (R2), and preserved type hints (R4).
5. **Delete the hand-rolled helpers** (`_is_retryable` duplicates, the
   `asyncio.sleep(1)` loops) once no call site uses them.
6. **Enable instrumentation** (optional): `stamina.instrumentation` with
   Prometheus / structlog hooks to monitor retry rates and alert on
   retry-storms [29].
7. **Pin and monitor**: add `stamina` to the dependency-update policy and
   watch upstream releases (it has a security policy / back-compat policy
   page [6][7]).

### 4.5 Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Global `set_active`/`set_testing` state leaks between tests | Low (idempotent, fixture restores) | Use the fixture from 4.3 (restores on teardown) and the context-manager form `set_testing(...)` for scoped overrides [24][25]. |
| Retrying non-idempotent requests (POSTs that create resources) | Medium | The `on=` hook is per-call-site; for non-idempotent endpoints either don't retry, retry only on `TransportError`, or ensure the partner API is idempotent (use idempotency keys). |
| Amplifying load on an already-flaky partner (thundering herd) | Medium | Jittered backoff + `timeout`/`attempts` caps are defaults [15][17]; keep `wait_max` modest and monitor via instrumentation [29]. |
| Hidden dependency on tenacity (stamina's only dep) | Low | tenacity is Apache-2.0, active, and widely used [1][2][3]; it is a transitive dep, still visible in lockfiles. |
| API drift if we need low-level control stamina doesn't expose | Low | stamina is a thin wrapper on tenacity [14][7]; if a need arises, use tenacity directly (runner-up) without changing the migration story. |
| `mypy --strict` on `httpx` + stamina interaction (e.g. `reveal_type` of decorated async fn) | Low | Verify in the pilot (step 1); stamina's hints are themselves checked by Pyrefly/ty [29][30]. |

---

## 5. Sources

All URLs accessed **2026-09-24**.

1. tenacity — PyPI project page (latest release, licence, `requires_python`,
   runtime deps): https://pypi.org/project/tenacity/
2. tenacity — GitHub repository (status: active, not archived, recent
   pushes): https://github.com/jd/tenacity
3. tenacity — PyPI JSON API (release dates: 9.1.4 2026-02-07, 9.1.3
   2026-02-05): https://pypi.org/pypi/tenacity/json
4. backoff — PyPI project page (latest release 2.2.1, licence MIT,
   `requires_python >=3.7,<4.0`): https://pypi.org/project/backoff/
5. backoff — README (async support, jitter, `max_tries`/`max_time`,
   `giveup`): https://raw.githubusercontent.com/litl/backoff/master/README.rst
   and PyPI JSON API (release dates: 2.2.1 2022-10-05):
   https://pypi.org/pypi/backoff/json
6. stamina — PyPI project page (latest release 26.1.0, licence MIT,
   `requires_python >=3.10`, runtime dep `tenacity`):
   https://pypi.org/project/stamina/
7. stamina — PyPI JSON API (release dates: 26.1.0 2026-04-13, 25.2.0
   2025-12-11) + wheel METADATA (runtime dep `tenacity`):
   https://pypi.org/pypi/stamina/json
8. backoff — GitHub repository (**archived**: `archived: true`, last push
   2024-05-02): https://github.com/litl/backoff and
   https://api.github.com/repos/litl/backoff
9. stamina — GitHub repository (status: active, not archived, recent
   pushes): https://github.com/hynek/stamina
10. tenacity — README / docs (features incl. "Retry on coroutines"; docs
    home): https://github.com/jd/tenacity/blob/main/README.rst and
    https://tenacity.readthedocs.io/en/latest/
11. tenacity — `tenacity/asyncio/__init__.py` (async `AsyncRetrying`,
    `enabled` param, trio/asyncio sleep):
    https://github.com/jd/tenacity/blob/main/tenacity/asyncio/__init__.py
12. backoff — `_async.py` (coroutine retry, `await asyncio.sleep`):
    https://github.com/litl/backoff/blob/master/backoff/_async.py
13. backoff — `_sync.py` (hard-coded `time.sleep`):
    https://github.com/litl/backoff/blob/master/backoff/_sync.py
14. stamina — Tutorial (decorator + backoff-hook for 5xx-only retries;
    async httpx example; `Retry-After`): https://stamina.hynek.me/en/latest/tutorial.html
15. stamina — Motivation (default backoff formula, jitter, rationale):
    https://stamina.hynek.me/en/latest/motivation.html
16. tenacity — `tenacity/wait.py` (`wait_exponential_jitter`,
    `wait_random_exponential`, `wait_random`, `wait_combine`):
    https://github.com/jd/tenacity/blob/main/tenacity/wait.py
17. stamina — `stamina.retry` docstring (params: `on`, `attempts`,
    `timeout`, `wait_*`): https://github.com/hynek/stamina/blob/main/src/stamina/_core.py
18. stamina — README (feature bullets incl. backoff with jitter, attempt &
    time caps, async, typing, testing):
    https://github.com/hynek/stamina/blob/main/README.md
19. tenacity — `tenacity/__init__.py` (`enabled` parameter, overloads):
    https://github.com/jd/tenacity/blob/main/tenacity/__init__.py
20. tenacity — `tenacity/nap.py` (sync `sleep` "may be mocked out for unit
    testing"): https://github.com/jd/tenacity/blob/main/tenacity/nap.py
21. tenacity — `tenacity/stop.py` (`stop_after_attempt`,
    `stop_after_delay`, `stop_any`):
    https://github.com/jd/tenacity/blob/main/tenacity/stop.py
22. tenacity — release note "allow mocking of nap/sleep":
    https://github.com/jd/tenacity/tree/main/releasenotes/notes
23. stamina — Testing docs (`set_testing`, `set_active`):
    https://stamina.hynek.me/en/latest/testing.html
24. stamina — `stamina/_config.py` (`set_testing`, `set_active`,
    context-manager support):
    https://github.com/hynek/stamina/blob/main/src/stamina/_config.py
25. stamina — CHANGELOG (24.3.0 `set_testing`; 25.1.0 `cap` + CM):
    https://github.com/hynek/stamina/blob/main/CHANGELOG.md
26. tenacity — wheel (contains `tenacity/py.typed`):
    https://files.pythonhosted.org/packages/d7/c1/eb8f9debc45d3b7918a32ab756658a0904732f75e555402972246b0b8e71/tenacity-9.1.4-py3-none-any.whl
27. backoff — wheel (contains `backoff/py.typed`, `backoff/types.py`):
    https://files.pythonhosted.org/packages/df/73/b6e24bd22e6720ca8ee9a85a0c4a2971af8497d8f3193fa05390cbd46e09/backoff-2.2.1-py3-none-any.whl
28. stamina — wheel (contains `stamina/py.typed`, `stamina/typing.py`):
    https://files.pythonhosted.org/packages/1d/f0/1ff90a1d1dd02de23feafdf9dffaecef3958348be5c192df56670ccb4f86/stamina-26.1.0-py3-none-any.whl
29. stamina — Instrumentation docs (Prometheus / structlog / logging):
    https://stamina.hynek.me/en/latest/instrumentation.html
30. stamina — CHANGELOG (25.2.0: type hints verified with Pyrefly & ty):
    https://github.com/hynek/stamina/blob/main/CHANGELOG.md
31. backoff — open issue #223 "Bug: wrong exception handling in _async.py"
    (open since 2025-01-18, evidence of no maintenance):
    https://github.com/litl/backoff/issues/223