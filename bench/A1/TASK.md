# A1 — Explain the ingest pipeline's data flow

Work only inside `bench/A1/`. Do not modify any code.

`bench/A1/src/ingest/pipeline.py` is an event-ingest pipeline: raw JSON events
go in through `IngestPipeline.submit()` and come out in batches at a sink.

Write `bench/A1/ANALYSIS.md` explaining the module's data flow precisely enough
that a new maintainer could predict its behaviour without running it. Cover:

1. The path of one event from `submit()` to the sink — every stage, in order.
2. Duplicate detection: what makes two events "the same", how long that memory
   lasts, and any edge cases in how it interacts with the other stages.
3. The user-enrichment cache: when a lookup happens, what is cached, and
   when entries expire.
4. Ordering: what ordering guarantees the sink does and does not get.
5. When batches are sent, and what happens to events and to the caller when
   the sink raises.
6. Any behaviour a caller would likely find surprising.

Be concrete: cite function names / line numbers and back claims with small
examples (you may run code in a scratch script, but do not change the module
or its tests). Correct, specific claims matter more than length; wrong claims
cost points.
