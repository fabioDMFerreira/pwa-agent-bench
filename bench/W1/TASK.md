# W1 — Is our `requests` pin affected by CVE-2023-32681?

Work only inside `bench/W1/`. Do not modify any code (including
`requirements.txt`). Use web research.

Our dependency scanner raised an alert for **CVE-2023-32681**
(GitHub advisory **GHSA-j8r2-6x86-q33q**) against the `requests` package. Our
pinned dependencies are in `bench/W1/requirements.txt`.

## Deliverable

Write `bench/W1/RESEARCH.md` answering:

1. What is the vulnerability (one or two sentences)?
2. What is the exact affected version range, and which version fixed it?
3. **Is our pinned version affected — yes or no?** Justify with the range.
4. Are there *other* published security advisories that do affect our pinned
   `requests` version? List each (CVE/GHSA id, fixed version), and give the
   minimum `requests` version that resolves all of them.
5. Your recommended action for `requirements.txt` (do not edit it).

Cite a source URL for every factual claim (prefer primary sources: GitHub
advisory database, NVD, OSV, PyPI, the project's changelog). Put a
"Sources" list at the end with the date you accessed them.
