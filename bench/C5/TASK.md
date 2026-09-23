# C5 — Feature-flag system

Work only inside `bench/C5/`. Do not modify existing tests.

Build a small, production-grade feature-flag system from scratch in
`src/feature_flags.py` (you may turn it into a package `src/feature_flags/`
instead, as long as the imports and `python -m feature_flags` below work).
Python stdlib only.

## Data model

`Flag` is a `@dataclass` with fields, in this order:

| field | type | default | rules |
|---|---|---|---|
| `name` | `str` | — | required, non-empty |
| `enabled` | `bool` | `False` | must be a real `bool` |
| `rollout_percent` | `int` | `0` | integer 0–100 inclusive; `bool` is not accepted |
| `allowlist` | `list[str]` | `[]` | list of strings |
| `rules` | `list[dict]` | `[]` | segment rules, see below |

A **segment rule** is a dict with exactly two keys: `"attribute"` (non-empty
str) and one of `"in"` / `"not_in"` (a list of str). Example:
`{"attribute": "country", "in": ["PT", "ES"]}`.

`Flag.validate()` raises `ValueError` if any rule in the table above is
violated (wrong type, out of range, malformed rule, unknown rule operator…).

## Storage

Flags live in a JSON file containing a list of flag objects:

```json
[
  {"name": "dark-mode", "enabled": false, "rollout_percent": 100, "allowlist": [], "rules": []},
  {"name": "new-checkout", "enabled": true, "rollout_percent": 25, "allowlist": ["u1", "u2"],
   "rules": [{"attribute": "country", "in": ["PT", "ES"]}]}
]
```

`allowlist`, `rules`, `rollout_percent` and `enabled` may be omitted in the
file (defaults apply). `name` is required. Unknown keys are an error.

## API — `class FlagStore`

- `FlagStore(path)` — `str` or `Path`; remember it, do not load yet.
- `load() -> None` — read the file. A missing file means an empty store.
  Raises `ValueError` if the content is not a JSON list, if any entry is
  invalid (see data model / unknown keys / missing `name`), or if two entries
  share a `name`. If `load()` raises, the store's in-memory flags are left
  exactly as they were.
- `save() -> None` — write all flags, **atomically**: write the full content
  to a temporary file in the same directory, then `os.replace()` it over the
  target. If anything fails, the existing file is left untouched, no
  temporary file is left behind, and the exception propagates. Output is
  pretty-printed (2-space indent), flags sorted by `name`, every field
  written explicitly, file ends with a newline.
- `get(name) -> Flag | None`
- `names() -> list[str]` — sorted flag names.
- `upsert(flag) -> None` — validates (`ValueError` if invalid, store
  unchanged), then adds or replaces by name.
- `remove(name) -> bool` — `True` if removed, `False` if absent.
- `is_enabled(name, user_id, attributes=None) -> bool` — rules below.

Module-level `bucket(flag_name: str, user_id: str) -> int`:
`int(hashlib.md5(f"{flag_name}:{user_id}".encode()).hexdigest()[:8], 16) % 100`.
It must be identical across processes and interpreter runs (never use the
built-in `hash()`).

### `is_enabled` rules, in order

1. Unknown flag → `False`.
2. `enabled` is `False` → `False`.
3. `user_id` in `allowlist` → `True` (allowlist bypasses segment rules and rollout).
4. Segment rules: **every** rule must match, else `False`. `attributes` is a
   `dict[str, str]` (treat `None` as `{}`). An `"in"` rule matches when the
   attribute is present and its value is in the list; a `"not_in"` rule
   matches when the attribute is present and its value is not in the list. A
   missing attribute never matches.
5. Rollout: `True` iff `bucket(name, user_id) < rollout_percent`.

## CLI

`python -m feature_flags --file PATH COMMAND ...` (with `src/` on
`PYTHONPATH`). Also expose `main(argv: list[str]) -> int` returning the exit
status (the `__main__` entry calls `sys.exit(main(sys.argv[1:]))`).

| command | behaviour | stdout |
|---|---|---|
| `list` | one line per flag, sorted by name | `<name> <on\|off> <rollout_percent>%` |
| `enable NAME` | set `enabled=True`, save | `<name> enabled` |
| `disable NAME` | set `enabled=False`, save | `<name> disabled` |
| `check NAME USER_ID [--attr KEY=VALUE]...` | evaluate `is_enabled` | `on` or `off` |

- Success → exit 0 (`check` exits 0 whether the answer is on or off).
- Runtime errors (unknown flag for `enable`/`disable`, invalid flags file)
  → message starting with `error:` on stderr, exit 1, file not modified.
- Usage errors (unknown command, missing args, `--attr` without `=`) → exit 2
  (argparse's default behaviour is fine).

The tests in `tests/` cover part of this spec. The full spec above is what
counts.

**Deliverable:** the implementation under `src/`; tests pass with
`cd bench/C5 && python3 -m pytest -q`.
