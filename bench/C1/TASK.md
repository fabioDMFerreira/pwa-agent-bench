# C1 — Fix an off-by-one in pagination

Work only inside `bench/C1/`. Do not modify existing tests.

There is an off-by-one bug in `src/pagination.py`: `page_count` under-counts
pages when the item count is not an exact multiple of the page size. The test
`tests/test_pagination.py::test_last_page_boundary` reproduces it.

Find the bug and fix it so the function meets the contract in its docstring.

**Deliverable:** a fixed `src/pagination.py`; all tests pass with
`cd bench/C1 && python3 -m pytest -q`.
