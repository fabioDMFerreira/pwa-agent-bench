# C3 — Add a `done` subcommand to the todo CLI

Work only inside `bench/C3/`. Do not modify or delete existing tests (you may
add new test files or new test functions).

`src/todo_cli.py` is a small argparse-based todo CLI with two subcommands,
`add` and `list`. Persistence is `state.json` in the current working
directory via `load_state` / `save_state`. Each todo is a dict
`{"text": str, "done": bool}`.

## Requirements

1. Add a subcommand `done <index>` that marks the todo at the given
   **1-based** index as done and saves the state. On success it prints
   `done: <text>`.
2. Marking an already-done item again is allowed and leaves it done.
3. An index that is not an integer, or is out of range (`0`, negative, or
   greater than the number of todos), must exit with a **non-zero**
   `SystemExit` and must not change `state.json`.
4. `list` shows done items prefixed `[x] ` and open items `[ ] `, e.g.
   `1. [x] buy milk`. Numbering is unchanged.
5. Keep `main(argv)` as the entry point; register `done` the same way the
   existing subcommands are registered.
6. **Write tests** for the new subcommand in `tests/` (happy path, display,
   persistence, invalid indexes). They must pass.

**Deliverable:** updated `src/todo_cli.py` plus new tests; all tests pass with
`cd bench/C3 && python3 -m pytest -q`.
