# S1 — Choose a rate-limiting design

Work only inside `bench/S1/`. Do not modify any code. No web access is needed:
everything you need is in `bench/S1/docs/requirements/`.

Read all of the requirement documents in `bench/S1/docs/requirements/`. Then
choose a rate-limiting **algorithm and design** for the Ledger API's per-user
limit.

## Deliverable

Write `bench/S1/RESEARCH.md` containing:

1. **Constraints** — the requirements that drive the decision, each citing the
   document it comes from.
2. **Options considered** — at least four candidate designs (algorithm +
   where the state lives). For each: how it works, and whether it satisfies
   each hard constraint. Reject options explicitly, citing the constraint
   they violate.
3. **Recommendation** — the chosen algorithm and design, including the exact
   state kept per user, how a request is checked and admitted atomically
   (concrete SQL or pseudo-code is welcome), how the configured numbers map
   to the algorithm's parameters, and how `Retry-After` is computed.
4. **Risks and mitigations** — load, failure modes (e.g. the state store is
   slow or down), storage growth/cleanup, clock issues.
5. **Open questions** for the product/platform owners, if any.
