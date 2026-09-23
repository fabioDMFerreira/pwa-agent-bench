# Capacity and resource budget

- ~2 million registered API users; ~40 000 are active on a typical day, with a
  long tail of keys that make a handful of calls per month.
- Peak total traffic: **3 000 requests/s** across all pods (batch window).
  Median request latency budget: 25 ms; the rate-limit check may add at most
  **5 ms p99**.
- Each pod's memory limit is 256 MiB, of which the app already uses ~200 MiB.
  The rate limiter may use **at most 8 MiB per pod**.
- The Postgres primary currently runs at ~1 500 simple writes/s with headroom
  measured to ~9 000 simple single-row writes/s. Postgres p99 for a
  single-row `UPDATE ... RETURNING` via PgBouncer from the pods is ~2 ms.
- Storage growth for this feature should be bounded (no unbounded per-request
  rows kept beyond what the algorithm needs).
