# pwa-agent-bench

> **BENCHMARK FIXTURE — DRAFT.** Agent output must never be merged to `main`.
> `main` is frozen at tag `bench-v1`; every run branches from it.

Fixture repo for comparing PWA agents (Pi, OpenCode, OpenHands) through PWA agent assignments.

Each task lives in `bench/<id>/` and is self-contained: `TASK.md` (the prompt), plus `src/`, `tests/`
or `docs/` as needed. Work only inside the task's directory unless `TASK.md` says otherwise.

Run public tests for a task: `cd bench/<id> && python3 -m pytest -q`

Hidden tests, answer keys and scoring live outside this repo on purpose.
