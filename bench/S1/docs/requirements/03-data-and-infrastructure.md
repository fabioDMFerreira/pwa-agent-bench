# Data and infrastructure

- The system of record is **PostgreSQL 16** (one primary, two async read
  replicas, PgBouncer in transaction-pooling mode in front of the primary).
- **No new stateful infrastructure** may be introduced for this feature. The
  platform team's decision (ADR-117, 2026-03) is explicit: **Redis, Memcached,
  etcd, Hazelcast and similar shared caches are not approved** for the Ledger
  API — the security review of our tenancy model rejected them, and the
  platform team will not operate another stateful service for one feature.
- Postgres **is** available for any shared state the design needs. Reads from
  the async replicas can lag the primary by up to a few seconds.
- PgBouncer transaction pooling means session-level features (session
  advisory locks, `LISTEN/NOTIFY` on pooled connections, temp tables across
  transactions) are not reliable; transaction-scoped features are fine.
