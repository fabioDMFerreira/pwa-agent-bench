# Ledger API — overview

The Ledger API is the public HTTP API that partner integrations use to read
and post ledger entries. We need to add **per-user rate limiting** before the
partner programme opens to self-serve sign-ups next quarter.

Terminology: a *user* is an authenticated API principal (one API key = one
user). Anonymous traffic is rejected at the edge and is out of scope.

Goals, in priority order:

1. **Fairness** — one heavy user must not be able to consume another user's
   share. See `04-limits-and-fairness.md` — these numbers are contractual.
2. **Correctness under our deployment model** — see `02-deployment.md`.
3. **Operational simplicity** — see `03-data-and-infrastructure.md`.
4. **Resource budget** — see `05-capacity.md`.

Non-goals: global (all-users) throttling, cost-based/weighted limits,
per-endpoint limits. Those may come later.
