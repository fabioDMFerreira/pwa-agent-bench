# Limits and fairness (contractual)

The partner agreement defines the limit **per user, across the whole
service** — not per pod:

- **Sustained rate:** 600 requests per minute per user (10 req/s average).
- **Bursts:** a user who has been idle may send a burst of **up to 60
  requests back-to-back**; they are then held to the sustained rate.
- **Accuracy:** over any 60-second window a user must never be allowed more
  than **660 requests** (limit + burst allowance) — auditors replay our access
  logs against this rule, and exceeding it is a contract breach. Being
  somewhat *too strict* for a few seconds (e.g. during a pod restart) is
  acceptable; being too lenient is not.
- Rejected requests get HTTP 429 with a `Retry-After` header (seconds).
- Rejections must not count against the user's budget.
