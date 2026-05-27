# Security Review — 2026-05-27

**Scope:** `hyperliquid-order-scale` at HEAD on the branch implementing the
security/coverage spec. Reviewer: agent following
`docs/superpowers/specs/2026-05-27-security-coverage-design.md`.

## Tooling

| Tool | Result |
|---|---|
| `pip-audit -r requirements.txt` | No known vulnerabilities in declared runtime deps. |
| `pip-audit` (full installed env) | 2 CVEs in `pip` itself (CVE-2026-3219, CVE-2026-6357); dev-only, not in shipped surface. Fix is `pip install -U pip`. |
| Bandit (`bandit -r core/ bot/ cli/ -ll`) | 0 issues at any severity. |

## Manual review

### Trust boundaries examined

1. **Telegram input parsing.** `/set`, free-text numeric input, and inline `callback_data`.
   `Decimal()` with `InvalidOperation` catch on all numeric paths; `callback_data` is
   server-defined enum. No injection surface.

2. **Output sanitization.** Error replies in `bot/main.py` interpolate `{e}` and
   `{result['error']}` at 9 sites. All use default plain-text rendering, so
   exception payloads cannot inject HTML/markup. Convention documented inline.

3. **Concurrency and storage.** `core/storage.py` uses `threading.Lock` per file
   plus `_atomic_write` (tempfile + `os.replace`). `os.replace` is atomic on Linux
   (Railway) and macOS (dev). Lock is mostly redundant in single-process asyncio
   but cheap and defensive — kept.

4. **Resource limits.** `registered_users.json` grows unbounded but is a set;
   duplicates free. `prev_state.json` only stores latest snapshot. Broadcast loop
   in `poll_and_notify` has per-user `try/except` so one blocked user can't kill
   the broadcast. `format_changes` truncates at TELEGRAM_MAX_LENGTH (4096).

5. **Secret handling.** `TELEGRAM_BOT_TOKEN` is read once from env in
   `bot/main.py:main()`, never logged, never persisted. `.env` is gitignored.
   `requests` exceptions don't include headers by default, so the `logger.error(f"...: {e}")`
   pattern in `poll_and_notify` is safe under the current library version.

6. **Exception handling.** Narrowed `safe_price` and `normalize_val` from
   `except Exception:` to `(ValueError, TypeError, InvalidOperation)` for
   explicit intent. `core/engine.py:fetch_user_fills` correctly catches only
   `requests.exceptions.RequestException`. No other broad excepts found.

### Decisions

| Finding | Action |
|---|---|
| `safe_price` / `normalize_val` catch `Exception` | **Fixed** (narrowed to specific types) |
| Error-reply consistency convention undocumented | **Fixed** (comment added) |
| `registered_users.json` unbounded | **No action** — set-deduped, low risk |
| `threading.Lock` partially redundant in asyncio | **No action** — defensive, cheap |
| pip CVEs in dev env | **No action in code** — `make audit` only checks `requirements.txt` (declared runtime deps), which is clean. Developers can run `pip install -U pip` locally. |
| HYPERLIQUID_ADDRESS from env is read-only consumer of an attacker-chosen account | **No action** — if env is compromised, attacker already has bigger problems. The bot only reads from this address, never signs transactions. |

### Followups (not in this plan's scope)

- If multiprocessing is ever added (or the bot runs behind multiple replicas on
  Railway), the `threading.Lock` will not coordinate across processes —
  storage will need a different scheme (single-writer or file lock).
- If error messages ever switch to `parse_mode="HTML"`, every interpolation
  site will need `html.escape` on the exception payload.

## CI/CD

`pip-audit` is now wired into CI via `.github/workflows/ci.yml` (added in the
same branch). Future dependency CVEs will fail the build before merge.
