# R1 — Review pull request #1 (notify service)

Work only inside `bench/R1/`. Do not modify any code.

`bench/R1/src/notify/` is a small notification service (user lookup, template
rendering, webhook delivery with retry). Pull request #1 lives on the git
branch `review/pr-1`. Review the changes on `review/pr-1` against `bench-v1`:

```
git diff bench-v1...review/pr-1
```

(You can also `git show review/pr-1:bench/R1/src/notify/<file>` to read the
full post-change files. The public tests pass on both sides:
`cd bench/R1 && python3 -m pytest -q`.)

The module docstrings describe the intended behaviour of the service.

## Deliverable

Write `bench/R1/REVIEW.md`. For **each** issue you find, give:

- **Location** — `file:line` in the post-change (`review/pr-1`) version
- **Severity** — one of `critical`, `high`, `medium`, `low`
- **Category** — `bug`, `security`, `performance`, or `other`
- **Explanation** — what is wrong, the concrete consequence, and a suggested fix

Only report real problems. Findings that are not actual defects count against
you, so do not pad the list with style nits or speculative concerns. End the
file with a one-line verdict: `approve` or `request changes`.
