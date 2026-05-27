# Security Review, Dependency Hygiene, and Test Coverage to 85% — Design

**Date:** 2026-05-27
**Status:** Draft (awaiting review)
**Scope:** `hyperliquid-order-scale` repo at HEAD `70ca68a`

## Goal

Raise the project's defensive baseline along three axes, delivered as one branch with three reviewable commits:

1. Manual security review of the application surface, with fixes for any findings.
2. A dependency-vulnerability gate in CI, so future drift is caught automatically.
3. Test coverage from 29% → 85% on the testable code surface (`core/` + `bot/`).

## Recon (snapshot at design time)

| Check | Result |
|---|---|
| `pip-audit -r requirements.txt` | No known vulnerabilities in declared runtime deps. |
| `pip-audit` (full installed env) | 2 CVEs, both in `pip` itself (dev-only, not in shipped surface). |
| Bandit static scan (`core/`, `bot/`, `cli/`) | 0 issues at any severity. |
| Pinned versions | `requests 2.34.2`, `python-telegram-bot 22.7`, `python-dotenv 1.2.2`, `pytest 9.0.3` — all current. |
| `pytest --cov` baseline | 29% total (bot 30% / cli 0% / engine 38% / storage 30%). |

**Implication:** automated tooling found nothing. The security work is a *manual review* of trust boundaries and a CI gate to keep things clean; **no dependency upgrades are needed today**.

## Approach

**One branch, three commits, one spec.** Reject splitting into three independent PRs — the codebase is small (~970 LoC) and the work overlaps (security findings become test cases).

Sequence:
1. Security review + fixes — touches code, so first.
2. CI / dependency gate — adds infra without code churn.
3. Coverage push — informed by what security review just touched.

## Part 1 — Security review

Manual review, since static analysis is clean. Threat surfaces in scope:

### 1.1 Input validation at the Telegram boundary

- `/set SIZE ENTRY`: parsed via `Decimal(...)` with `InvalidOperation` caught. Verify no codepath bypasses.
- Free-text numeric input (quick-scale handler): same `Decimal()` + catch pattern. Verify.
- `callback_data` strings (inline buttons): currently a fixed enum (`price`, `weishen`, `me`, `edit`). No injection surface since values are server-defined, but add an explicit fall-through that ignores unknown `query.data`.

### 1.2 Output sanitization

Nine error-reply sites in `bot/main.py` interpolate `{e}` or `{result['error']}` (lines 65, 326, 364, 368, 433, 457, 461, 508, 512). All currently default-mode (plain text) so they are safe today. **However** the rest of the bot uses `parse_mode="HTML"` and the inconsistency is a future-bug magnet.

**Fix:** standardize errors as plain text (no `parse_mode`) and add a one-line comment at one representative site explaining the convention. Do not switch errors to HTML — the cost of `html.escape` on every interpolation is not worth it for paths that already work.

### 1.3 Concurrency and storage atomicity

- `core/storage.py` uses `threading.Lock` for three JSON files plus an `_atomic_write` helper (tempfile + `os.replace`).
- Bot runs in a single asyncio loop, so the lock is mostly redundant within one process but cheap. Keep it (defends against future thread-pool work).
- `os.replace` is atomic on Linux (Railway) and macOS (dev). ✓
- `_atomic_write` writes to a temp file in the same dir then replaces. Correct.

**No fix needed.**

### 1.4 Resource limits and abuse

- `registered_users.json` grows unbounded as users `/start` the bot. Not a vulnerability — Telegram rate-limits per-bot and the file is a `set` so duplicates are free.
- Broadcast loop in `poll_and_notify` already has per-user `try/except` so one blocked user can't kill the broadcast. ✓
- `format_changes` truncates at `TELEGRAM_MAX_LENGTH = 4096`. ✓

**No fix needed.**

### 1.5 Secret handling

- `TELEGRAM_BOT_TOKEN` is read once in `bot/main.py:main()` from env, never logged, never written to disk.
- `.env` is in `.gitignore`. ✓
- Confirm `logger.error(f"...: {e}")` doesn't accidentally pick up exception text that might contain tokens. `requests` exceptions don't include headers by default, but a network library upgrade could change that. Low-prob, no action.

**No fix needed.**

### 1.6 Exception-handler tightening

Two helpers in `bot/main.py:detect_changes` (`safe_price`, `normalize_val`) use bare `except:`, which catches `KeyboardInterrupt` and `SystemExit`. **Fix:** narrow to `(ValueError, TypeError, InvalidOperation)`.

`core/engine.py:fetch_user_fills` catches `requests.exceptions.RequestException` only — correct, leave as-is.

### 1.7 Deliverable for Part 1

- A `docs/security-review-2026-05-27.md` summarizing findings and the rationale for each "no fix needed" decision (so the next reviewer doesn't re-investigate).
- Inline code fixes for §1.2 (error-reply consistency) and §1.6 (narrow excepts).

## Part 2 — Dependency hygiene and CI gate

- Add `requirements-dev.txt` containing `pip-audit`, `pytest-cov`, `pytest-asyncio`, `bandit`. Keep `requirements.txt` runtime-only.
- Add Makefile targets:
  - `make audit` — runs `pip-audit -r requirements.txt --strict`
  - `make coverage` — runs `pytest --cov` with the configured fail-under gate
- Add `.github/workflows/ci.yml`: matrix on Python 3.12 (the `.python-version`). Steps: install runtime + dev deps → `make audit` → `make test` → `make coverage`.

**No version bumps in `requirements.txt`.** Runtime deps are clean; do not churn working pins.

## Part 3 — Coverage 29% → 85%

### 3.1 Tooling and configuration

- Add `pytest-cov` to `requirements-dev.txt`.
- Add `pytest-asyncio` to `requirements-dev.txt` (needed for §3.4).
- Add `pyproject.toml` with:
  ```toml
  [tool.coverage.run]
  source = ["core", "bot"]
  omit = ["cli/*", "tests/*"]

  [tool.coverage.report]
  fail_under = 85
  show_missing = true

  [tool.pytest.ini_options]
  asyncio_mode = "auto"
  ```

### 3.2 Scope decision: exclude `cli/main.py`

`cli/main.py` is 84 stmts of interactive I/O via `input()`. Reaching meaningful coverage requires either heavy stdin mocking or a refactor to inject the prompter. Either is more invasive than the value provides for a tool that is **a developer convenience around the same `process_request` we will already cover via engine tests**. Excluded from the 85% gate and from `[tool.coverage.run].source`. This is documented in the spec and in `pyproject.toml`.

### 3.3 Test additions — order of yield

| # | Target | Approach | ~Tests | ~Stmts lifted |
|---|---|---|---|---|
| 1 | `core/storage.py` | tmpdir fixture, round-trip CRUD for all three files (user state, registered users, prev state) | 15 | 70 |
| 2 | `core/engine.py` network fns | mock `requests.post`, assert request payload + response parsing + error paths | 20 | 100 |
| 3 | `bot/main.py` pure helpers (`format_*`, fixture cases for `detect_changes` edges) | table-driven | 15 | 60 |
| 4 | `bot/main.py` async handlers | `pytest-asyncio` + `AsyncMock` for `Update`/`Context`; assert reply text + storage writes | 15 | 100 |
| 5 | `bot/main.py:poll_and_notify` | async test, all deps mocked, asserts broadcast loop and `save_previous_state` call | 3 | 25 |

**Projected coverage on `core/` + `bot/` after work: ~88%**, above the 85% gate.

### 3.4 Async testing pattern

Use `pytest-asyncio` with `asyncio_mode = "auto"`. Fake `Update` and `Context` with `unittest.mock.AsyncMock`:

```python
async def test_price_command_replies_with_html(monkeypatch):
    fake_update = AsyncMock()
    fake_update.message = AsyncMock()
    fake_update.effective_user.id = 42
    monkeypatch.setattr("bot.main.fetch_btc_price",
                       lambda: {"price": Decimal("100000"),
                                "change_24h": Decimal("500"),
                                "change_pct_24h": Decimal("0.5")})
    await price_command(fake_update, AsyncMock())
    fake_update.message.reply_text.assert_awaited_once()
    args, kwargs = fake_update.message.reply_text.call_args
    assert kwargs["parse_mode"] == "HTML"
```

No real `Application` is constructed. Tests stay fast (<1s total).

### 3.5 What we will NOT do

- **No production-code refactoring** purely for testability unless a handler is genuinely untestable in its current shape. Tests adapt to code, not the other way around. Exception logged inline if it becomes necessary.
- **No `cli/main.py` tests.** Excluded per §3.2.
- **No integration tests against the real Hyperliquid API.** All network mocked.

## Deliverables checklist

- [ ] `docs/security-review-2026-05-27.md` (findings + rationale)
- [ ] Code fixes in `bot/main.py` (error-reply consistency, narrowed excepts)
- [ ] `requirements-dev.txt`
- [ ] `Makefile` targets: `audit`, `coverage`
- [ ] `.github/workflows/ci.yml`
- [ ] `pyproject.toml` with coverage + pytest-asyncio config
- [ ] New tests: ~68 across `tests/test_storage.py` (new), `tests/test_engine.py` (extend), `tests/test_bot.py` (extend), `tests/test_bot_async.py` (new)
- [ ] Coverage report ≥85% on `core/` + `bot/`
- [ ] README touch: one line on `make audit` / `make coverage`

## Open questions

1. Does the user want `pre-commit` hooks for `bandit` / `pip-audit`, or is CI-only enough? **Default: CI-only**; pre-commit adds friction for what is already gated.
2. Does the user want stricter handler-level integration coverage (real `Application` with `MockTelegram`-style fixtures)? **Default: no** — unit-level async tests with mocked `Update`/`Context` provide enough confidence at far lower complexity.

## Risks

- **`pytest-asyncio` version pinning** can be picky against `python-telegram-bot` — verify combo works on first commit.
- **85% gate** could be a future-PR bottleneck. The plan documents the rationale for the chosen `omit`; bar can be revisited.
- **Manual security review depth** is bounded by reviewer attention. The spec lists everything in scope so the next reviewer can see what was/wasn't examined.
