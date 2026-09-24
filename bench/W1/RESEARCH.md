# W1 — Is our `requests` pin affected by CVE-2023-32681?

**Pinned version under review:** `requests==2.31.0` (from `bench/W1/requirements.txt`)

## 1. What is the vulnerability?

CVE-2023-32681 (GHSA-j8r2-6x86-q33q): since `requests` 2.3.0, the library can
leak the `Proxy-Authorization` header to destination servers when a request is
redirected to an HTTPS origin (HTTP→HTTPS and HTTPS→HTTPS). The leak only occurs
when proxy credentials are supplied in the proxy URL's user information
component (e.g. `https://user:pass@proxy:8080`): for tunneled HTTPS connections
the proxy cannot strip the header, so it reaches the destination server and
proxy credentials can be exfiltrated [1][2]. Severity: Medium,
CVSS v3.1 score 6.1 (CWE-200) [1][4].

## 2. Affected version range and fix

- **Affected range:** `>= 2.3.0, < 2.31.0` (per the GitHub advisory and OSV;
  earlier versions < 2.3.0 are not affected by *this* CVE) [1][5]
- **First fixed version:** `2.31.0` — released 2023-05-22, which no longer
  re-attaches `Proxy-Authorization` to HTTPS redirects [1][3]

## 3. Is our pinned version (2.31.0) affected?

**No.** Our pin is exactly `requests==2.31.0`, which is the *first fixed*
release for CVE-2023-32681. The vulnerable range is `>= 2.3.0, < 2.31.0`, and
2.31.0 is not included in it (the upper bound is exclusive) [1][5]. The scanner
alert is therefore a false positive for this specific CVE — the pin already
contains the fix. (If proxy credentials were historically used via URL
user-info, the advisory still recommends rotating them once the upgrade is
deployed, but that concern applies to past versions, not to 2.31.0 itself [1].)

## 4. Other published advisories that DO affect 2.31.0

Three published security advisories for `requests` cover our pin
(`2.31.0 < 2.32.0 < 2.32.4 < 2.33.0`):

| CVE / GHSA | Issue | Affected range | Fixed in | Severity (CVSS v3) | Affects 2.31.0? |
|---|---|---|---|---|---|
| CVE-2024-35195 / GHSA-9wx4-h78v-vm56 | A `Session` that makes its first request with `verify=False` causes all subsequent requests to the *same origin* to skip TLS certificate verification | `< 2.32.0` | **2.32.0** | Medium (5.6) | **Yes** |
| CVE-2024-47081 / GHSA-9hjg-9r4m-mvj7 | Maliciously crafted URL can cause `requests` to pick up credentials for the wrong host from `~/.netrc` | `< 2.32.4` | **2.32.4** | Medium (5.3) | **Yes** |
| CVE-2026-25645 / GHSA-gc5v-m9x4-r6x2 | Insecure temp-file reuse in the `extract_zipped_paths()` utility (only relevant to code that calls that helper directly) | `< 2.33.0` | **2.33.0** | Medium (4.4) | **Yes** (exposure only if the utility is used) |

Sources: [6][7][8][9]

Older CVEs on the `requests` record (CVE-2014-1829/1830 fixed in 2.3.0,
CVE-2015-2296 fixed in 2.6.0, CVE-2018-18074 fixed in 2.20.0) are all
already fixed in 2.31.0 and do not apply [5].

**Minimum version that resolves all of them: `2.33.0`** (the maximum of the
individual fix versions 2.32.0 / 2.32.4 / 2.33.0). The latest release on PyPI
as of 2026-09-24 is **2.34.2** [10].

## 5. Recommended action for `requirements.txt`

1. **Bump the pin from `requests==2.31.0` to `requests==2.34.2`** (the current
   PyPI release [10]) — or, at minimum, `requests==2.33.0` to clear all
   published advisories. This also closes the three real gaps in 2.31.0
   (CVE-2024-35195, CVE-2024-47081, CVE-2026-25645).
2. **Watch the Python runtime:** `requests` 2.33.0 dropped support for
   Python 3.9 (and 3.8) [11]. If `ledger-sync` still runs on Python ≤ 3.9,
   cap the pin at `requests==2.32.5`, which fixes CVE-2024-35195 and
   CVE-2024-47081; CVE-2026-25645 would then need a risk-acceptance note
   (it only affects code calling `extract_zipped_paths()` directly).
3. No code change or workaround is needed — a version bump of the pin is
   sufficient. (Per the CVE-2023-32681 advisory, if proxy credentials were
   ever passed via URL user-info on older `requests` versions, rotate those
   credentials.) [1]
4. Keep `click==8.1.7` and `python-dateutil==2.9.0.post0` as-is: none of the
   advisories above relate to them, and no other published advisory affects
   the pinned `requests` version beyond those listed above [5].

## Sources (all accessed 2026-09-24)

1. GitHub Advisory DB — GHSA-j8r2-6x86-q33q / CVE-2023-32681:
   https://github.com/advisories/GHSA-j8r2-6x86-q33q
   (project advisory + patch notes:
   https://github.com/psf/requests/security/advisories/GHSA-j8r2-6x86-q33q;
   release: https://github.com/psf/requests/releases/tag/v2.31.0)
2. NVD — CVE-2023-32681: https://nvd.nist.gov/vuln/detail/CVE-2023-32681
3. requests 2.31.0 release notes (security section):
   https://github.com/psf/requests/blob/main/HISTORY.md
4. GitHub Advisory DB API: https://api.github.com/advisories/GHSA-j8r2-6x86-q33q
5. OSV (PyPI `requests`) — full advisory/range cross-check:
   https://api.osv.dev/v1/query (package `requests`, ecosystem PyPI);
   UI: https://osv.dev/list?package=requests
6. GitHub Advisory DB — GHSA-9wx4-h78v-vm56 / CVE-2024-35195 (fixed in 2.32.0):
   https://github.com/advisories/GHSA-9wx4-h78v-vm56
7. GitHub Advisory DB — GHSA-9hjg-9r4m-mvj7 / CVE-2024-47081 (fixed in 2.32.4):
   https://github.com/advisories/GHSA-9hjg-9r4m-mvj7
8. GitHub Advisory DB — GHSA-gc5v-m9x4-r6x2 / CVE-2026-25645 (fixed in 2.33.0):
   https://github.com/advisories/GHSA-gc5v-m9x4-r6x2
9. requests changelog, v2.32.0 / v2.32.4 / v2.33.0 security sections:
   https://github.com/psf/requests/blob/main/HISTORY.md
10. PyPI — `requests` project page (latest release 2.34.2):
    https://pypi.org/project/requests/
11. requests 2.33.0 changelog entry (dropped Python 3.9 support):
    https://github.com/psf/requests/blob/main/HISTORY.md