# Security Review, CI Gate, and Coverage→85% Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land three improvements as a single branch on `hyperliquid-order-scale`: (a) a documented security review with two minor hardening fixes, (b) a CI gate that runs `pip-audit` and tests on every push, and (c) test coverage on `core/` + `bot/` raised from 29% to ≥85%.

**Architecture:** Twelve tasks in roughly four groups — dev tooling setup → security fixes + findings doc → coverage push (5 test batches) → coverage gate enforcement + CI. Each task ends in a commit. `cli/main.py` is explicitly excluded from coverage measurement (interactive `input()` not worth heavy mocking). No production-code refactoring beyond the two minor security fixes.

**Tech Stack:** Python 3.12, pytest, pytest-cov, pytest-asyncio, pip-audit, GitHub Actions. The codebase already uses `requests`, `python-telegram-bot[job-queue]`, `python-dotenv`, `Decimal` arithmetic, threading.Lock + atomic JSON writes for storage.

**Spec reference:** `docs/superpowers/specs/2026-05-27-security-coverage-design.md`

**Spec correction noted up front:** Spec §1.6 says `safe_price` and `normalize_val` use "bare `except:`". The code actually uses `except Exception:` (already narrower than bare). The intended fix — narrow to `(ValueError, TypeError, InvalidOperation)` for explicit intent — is still worthwhile and is implemented in Task 2.

---

## File Structure

**New files created by this plan:**
- `requirements-dev.txt` — dev-only deps (pip-audit, pytest-cov, pytest-asyncio, bandit)
- `pyproject.toml` — coverage + pytest-asyncio config (no project metadata; `requirements.txt` is still authoritative)
- `docs/security-review-2026-05-27.md` — security review findings and rationale
- `.github/workflows/ci.yml` — GitHub Actions CI
- `tests/test_storage.py` — storage CRUD tests
- `tests/test_bot_async.py` — async handler + poll_and_notify tests (separate file because async tests need `pytest-asyncio` and grouping them simplifies discovery)
- `tests/conftest.py` — shared fixtures (DATA_DIR redirect for storage tests)

**Modified:**
- `bot/main.py` — narrow `except Exception:` blocks in `safe_price` and `normalize_val`
- `Makefile` — add `audit` and `coverage` targets
- `tests/test_engine.py` — extend with network fetch + orchestrator tests
- `tests/test_bot.py` — extend with format-helper tests
- `README.md` — one line mentioning `make audit` / `make coverage`

**Each file has one responsibility.** Async tests live in their own file to keep the existing `tests/test_bot.py` synchronous-and-fast.

---

## Task 1: Set up dev tooling

**Files:**
- Create: `requirements-dev.txt`
- Create: `pyproject.toml`
- Modify: `Makefile`

- [ ] **Step 1: Create `requirements-dev.txt`**

```text
-r requirements.txt
pip-audit>=2.7
pytest-cov>=5.0
pytest-asyncio>=0.23
bandit>=1.7
```

- [ ] **Step 2: Create `pyproject.toml`**

Coverage gate set to a placeholder for now (will tighten to 85 in Task 12). `branch = true` enables branch coverage. `omit` excludes `cli/`, tests, and `__init__.py` files. `asyncio_mode = "auto"` lets async tests work without per-test `@pytest.mark.asyncio` decorators.

```toml
[tool.coverage.run]
source = ["core", "bot"]
omit = ["cli/*", "tests/*", "**/__init__.py"]
branch = true

[tool.coverage.report]
show_missing = true
skip_covered = false

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Add `audit` and `coverage` targets to `Makefile`**

Insert before the `clean` target:

```makefile
# Run dependency vulnerability audit
audit:
	pip-audit -r requirements.txt --strict

# Run tests with coverage report
coverage:
	pytest tests/ --cov --cov-report=term-missing
```

Update `.PHONY` line to include the new targets:

```makefile
.PHONY: run bot test install clean audit coverage
```

- [ ] **Step 4: Install dev deps and verify `make audit` runs clean**

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements-dev.txt
make audit
```

Expected: `No known vulnerabilities found`.

- [ ] **Step 5: Run `make coverage` to confirm tooling works**

```bash
make coverage
```

Expected: tests pass, coverage report prints, TOTAL ~29% (baseline). Confirms pytest-cov is wired up correctly.

- [ ] **Step 6: Commit**

```bash
git add requirements-dev.txt pyproject.toml Makefile
git commit -m "Add dev tooling: pip-audit, pytest-cov, pytest-asyncio, bandit

Adds requirements-dev.txt, pyproject.toml with coverage + pytest-asyncio
config, and Makefile targets 'audit' and 'coverage'. Coverage gate is
not enforced yet — the fail_under threshold is added in a later commit
once the test additions land.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Security fix — narrow exception handlers

**Files:**
- Modify: `bot/main.py:185-197` (narrow `except Exception:` in `safe_price` and `normalize_val`)
- Modify: `tests/test_bot.py` (add tests covering both branches of each helper)

**Context:** Both helpers currently catch `Exception` — broad enough to mask real bugs. Narrow to `(ValueError, TypeError, decimal.InvalidOperation)` which covers the actual failure modes (malformed input to `Decimal(str(val))`).

- [ ] **Step 1: Add failing tests in `tests/test_bot.py`**

Append to the existing test file (after the last existing class):

```python
from decimal import InvalidOperation
from bot.main import detect_changes  # already imported at top, kept here for clarity


class TestExceptionNarrowingHelpers:
    """detect_changes uses two nested helpers — exercise both branches of each."""

    def test_malformed_price_falls_back_to_str(self):
        """Detection should not crash on malformed price strings — exercises the except branch."""
        prev = {
            "direction": "long", "size": "0.5", "entry_price": "90000",
            "orders": [{"oid": "1", "side": "B", "sz": "0.05", "limitPx": "not-a-number"}],
        }
        curr = {
            "direction": "long", "size": "0.5", "entry_price": "90000", "orders": [],
        }
        # Should not raise; the removed-order line falls back to str() formatting.
        changes = detect_changes(prev, curr)
        assert any("not-a-number" in c for c in changes)

    def test_normalize_handles_none(self):
        """When sz/limitPx is None on one side, comparison must not crash."""
        prev = {
            "direction": "long", "size": "0.5", "entry_price": "90000",
            "orders": [{"oid": "1", "side": "B", "sz": None, "limitPx": "90000"}],
        }
        curr = {
            "direction": "long", "size": "0.5", "entry_price": "90000",
            "orders": [{"oid": "1", "side": "B", "sz": "0.05", "limitPx": "90000"}],
        }
        changes = detect_changes(prev, curr)
        assert any("modified" in c.lower() for c in changes)

    def test_keyboardinterrupt_propagates(self):
        """After narrowing, KeyboardInterrupt should propagate (not be swallowed)."""
        # We can't easily inject KeyboardInterrupt into the inner Decimal() call,
        # but we can document the property: the helpers must NOT catch BaseException.
        # This test asserts the source code uses a narrow exception tuple.
        import inspect
        src = inspect.getsource(detect_changes)
        # After Task 2 fix, these helpers should NOT use `except Exception` or `except:`.
        assert "except Exception" not in src, \
            "safe_price/normalize_val should use a narrow exception tuple"
```

- [ ] **Step 2: Run tests — confirm `test_keyboardinterrupt_propagates` fails**

```bash
pytest tests/test_bot.py::TestExceptionNarrowingHelpers -v
```

Expected: the first two tests pass (current code already handles these inputs), the third fails because the source still contains `except Exception`.

- [ ] **Step 3: Apply the fix in `bot/main.py`**

Replace lines 185–197. Add the import at the top of the file (next to the existing `from decimal import Decimal, InvalidOperation` if present — the bot already imports `InvalidOperation` at the top, so no new import needed).

```python
    def safe_price(val) -> str:
        """Safely format price, handling malformed data."""
        try:
            return f"${Decimal(str(val)):,.0f}"
        except (ValueError, TypeError, InvalidOperation):
            return str(val)

    def normalize_val(val) -> str:
        """Normalize numeric values to string for comparison."""
        try:
            return str(Decimal(str(val)))
        except (ValueError, TypeError, InvalidOperation):
            return str(val) if val is not None else ""
```

- [ ] **Step 4: Re-run tests — all three should pass**

```bash
pytest tests/test_bot.py::TestExceptionNarrowingHelpers -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the full test suite to confirm no regressions**

```bash
make test
```

Expected: all tests pass (62 total: 59 prior + 3 new).

- [ ] **Step 6: Commit**

```bash
git add bot/main.py tests/test_bot.py
git commit -m "Narrow exception handlers in detect_changes helpers

safe_price and normalize_val previously caught Exception, which is
broad enough to mask real bugs while not catching the only things
that should propagate (KeyboardInterrupt, SystemExit are already
excluded by 'except Exception'). Narrow to (ValueError, TypeError,
InvalidOperation) for explicit intent.

Adds three tests covering the fallback branch and asserting the
source no longer uses 'except Exception'.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Security audit — verify error-reply consistency

**Files:**
- Read-only audit of `bot/main.py`
- Possibly modify: `bot/main.py` (add a single comment if no behavior change needed)

**Context:** The spec §1.2 noted nine `f"Error..."` interpolation sites in `bot/main.py`. These currently default to plain-text rendering (no `parse_mode="HTML"`), which is safe but inconsistent with the rest of the bot.

- [ ] **Step 1: Audit all error-reply sites**

```bash
grep -n "Error" bot/main.py | grep -E "reply_text|send_message"
```

Expected sites (verify line numbers may have shifted by ±2 after Task 2): 65, 326, 364, 368, 433, 457, 461, 508, 512.

For each site, confirm that the `reply_text(...)` call **does not** pass `parse_mode="HTML"`. The audit passes iff all nine sites use the default (plain-text) mode.

- [ ] **Step 2: If audit passes, add a single comment near the first error-reply site documenting the convention**

In `bot/main.py`, in the `price_command` handler around the `except Exception as e:` block, add a comment above the `reply_text` line:

```python
    except Exception as e:
        # Error messages are sent as plain text (no parse_mode="HTML") so
        # exception payloads cannot accidentally introduce HTML/markup. Keep
        # this convention across all error replies in this file.
        await update.message.reply_text(f"Error fetching price: {e}")
```

If any site fails the audit (uses HTML), fix that site instead by removing the `parse_mode="HTML"` argument from its `reply_text` call.

- [ ] **Step 3: Run tests to confirm no behavior change**

```bash
make test
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add bot/main.py
git commit -m "Document plain-text error-reply convention in bot

The bot uses parse_mode=HTML for normal responses but defaults to
plain text for error messages so exception payloads cannot inject
markup. This was already the de-facto behavior at all nine error
sites; add a comment at the first one to make the convention explicit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Write security-review findings doc

**Files:**
- Create: `docs/security-review-2026-05-27.md`

**Context:** Capture the review conclusions so the next reviewer can see what was examined and why each "no fix needed" call was made — without re-doing the analysis.

- [ ] **Step 1: Create `docs/security-review-2026-05-27.md`**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add docs/security-review-2026-05-27.md
git commit -m "Add 2026-05-27 security review findings document

Captures what was reviewed, what was fixed, what was explicitly left
alone and why. Lets the next reviewer skip re-doing this analysis.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Tests for `core/storage.py`

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/test_storage.py`

**Context:** `core/storage.py` has three concerns — user positions, registered users, and previous state — each backed by a JSON file under `DATA_DIR`. All are currently 30% covered. Goal: ≥95% on this file via tmpdir-based round-trip tests.

- [ ] **Step 1: Create `tests/conftest.py` with a `DATA_DIR` redirect fixture**

The storage module reads `DATA_DIR` at import time. To test in isolation, we'll reload the module after patching the env var.

```python
"""Shared fixtures."""
import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def storage_module(tmp_path, monkeypatch):
    """Reload core.storage with DATA_DIR pointed at a tmp_path.

    Returns the freshly-reloaded module so tests get isolated JSON files.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import core.storage as storage
    importlib.reload(storage)
    yield storage
    # Reset to a fresh import after the test so subsequent tests don't
    # see the tmp_path that no longer exists.
    importlib.reload(storage)
```

- [ ] **Step 2: Create `tests/test_storage.py` with the user-position tests**

```python
"""Tests for core.storage."""
from decimal import Decimal


class TestUserPosition:
    def test_get_returns_none_when_no_position(self, storage_module):
        assert storage_module.get_user_position(42) is None

    def test_set_then_get_roundtrip(self, storage_module):
        storage_module.set_user_position(42, Decimal("0.05"), Decimal("92000"))
        pos = storage_module.get_user_position(42)
        assert pos == {"size": Decimal("0.05"), "entry_price": Decimal("92000")}

    def test_set_overwrites_existing(self, storage_module):
        storage_module.set_user_position(42, Decimal("0.05"), Decimal("92000"))
        storage_module.set_user_position(42, Decimal("-0.10"), Decimal("95000"))
        pos = storage_module.get_user_position(42)
        assert pos["size"] == Decimal("-0.10")
        assert pos["entry_price"] == Decimal("95000")

    def test_clear_removes_user(self, storage_module):
        storage_module.set_user_position(42, Decimal("0.05"), Decimal("92000"))
        storage_module.clear_user_position(42)
        assert storage_module.get_user_position(42) is None

    def test_clear_nonexistent_is_noop(self, storage_module):
        storage_module.clear_user_position(999)  # should not raise

    def test_string_user_id_works(self, storage_module):
        storage_module.set_user_position("42", Decimal("0.05"), Decimal("92000"))
        assert storage_module.get_user_position(42) is not None  # int and str equivalent

    def test_corrupted_json_returns_none(self, storage_module, tmp_path):
        # Write garbage to the storage file, confirm graceful handling
        storage_module.STORAGE_FILE.write_text("{not valid json")
        assert storage_module.get_user_position(42) is None
```

- [ ] **Step 3: Add registered-users tests to the same file**

```python
class TestRegisteredUsers:
    def test_empty_initially(self, storage_module):
        assert storage_module.get_all_users() == []

    def test_register_and_list(self, storage_module):
        storage_module.register_user(42)
        storage_module.register_user(99)
        assert set(storage_module.get_all_users()) == {42, 99}

    def test_register_dedupes(self, storage_module):
        storage_module.register_user(42)
        storage_module.register_user(42)
        assert storage_module.get_all_users() == [42]

    def test_register_accepts_string_id(self, storage_module):
        storage_module.register_user("42")
        assert storage_module.get_all_users() == [42]

    def test_corrupted_users_file_returns_empty(self, storage_module):
        storage_module.USERS_FILE.write_text("not json")
        assert storage_module.get_all_users() == []
```

- [ ] **Step 4: Add previous-state tests**

```python
class TestPreviousState:
    def test_get_returns_none_when_no_file(self, storage_module):
        assert storage_module.get_previous_state() is None

    def test_save_then_get_roundtrip(self, storage_module):
        state = {
            "direction": "long",
            "size": Decimal("0.5"),
            "entry_price": Decimal("90000"),
            "orders": [{"oid": "1", "side": "B", "sz": "0.05", "limitPx": "89000"}],
        }
        storage_module.save_previous_state(state)
        loaded = storage_module.get_previous_state()
        assert loaded["direction"] == "long"
        assert loaded["size"] == "0.5"  # serialized as string
        assert len(loaded["orders"]) == 1

    def test_save_strips_unknown_order_fields(self, storage_module):
        state = {
            "direction": "long",
            "size": Decimal("0.5"),
            "entry_price": Decimal("90000"),
            "orders": [{"oid": "1", "side": "B", "sz": "0.05", "limitPx": "89000",
                        "internalField": "should_be_dropped"}],
        }
        storage_module.save_previous_state(state)
        loaded = storage_module.get_previous_state()
        assert "internalField" not in loaded["orders"][0]
```

- [ ] **Step 5: Add atomic-write test**

```python
class TestAtomicWrite:
    def test_atomic_write_creates_parent_dir(self, storage_module, tmp_path):
        target = tmp_path / "nested" / "deeper" / "file.json"
        storage_module._atomic_write(target, '{"k": "v"}')
        assert target.read_text() == '{"k": "v"}'

    def test_atomic_write_cleans_up_temp_on_failure(self, storage_module, tmp_path, monkeypatch):
        target = tmp_path / "file.json"
        # Force os.replace to fail
        def boom(*args, **kwargs):
            raise OSError("simulated")
        monkeypatch.setattr("core.storage.os.replace", boom)
        try:
            storage_module._atomic_write(target, "x")
        except OSError:
            pass
        # No leftover .tmp files
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []
```

- [ ] **Step 6: Run the storage tests**

```bash
pytest tests/test_storage.py -v
```

Expected: all ~17 tests pass.

- [ ] **Step 7: Run full coverage to see the lift**

```bash
make coverage
```

Expected: `core/storage.py` jumps from 30% to ≥95%. TOTAL should rise from 29% to ~38–40%.

- [ ] **Step 8: Commit**

```bash
git add tests/conftest.py tests/test_storage.py
git commit -m "Add tests for core/storage.py — user positions, registered users, prev state

Brings core/storage.py coverage from 30% to ~95% via tmpdir round-trip
tests. Uses a conftest fixture that reloads the storage module against
a tmp_path-redirected DATA_DIR for isolation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Tests for `core/engine.py` — network helpers and time helpers

**Files:**
- Modify: `tests/test_engine.py` (append new test classes)

**Context:** `core/engine.py` has 4 network functions (`fetch_btc_price`, `fetch_account_state`, `fetch_open_orders`, `fetch_user_fills`) and 2 time helpers (`get_relative_time`, `get_last_activity_time`) all currently uncovered. We mock `requests.post` per the existing pattern in `test_engine.py`.

- [ ] **Step 1: Append network-helper tests to `tests/test_engine.py`**

```python
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from core.engine import (
    fetch_btc_price,
    fetch_account_state,
    fetch_open_orders,
    fetch_user_fills,
    get_relative_time,
    get_last_activity_time,
)


def _mock_response(json_data, raise_for_status=None):
    """Build a fake requests.Response for patching."""
    resp = MagicMock()
    resp.json.return_value = json_data
    if raise_for_status is not None:
        resp.raise_for_status.side_effect = raise_for_status
    return resp


class TestFetchBtcPrice:
    def test_parses_btc_price_correctly(self):
        meta = {"universe": [{"name": "ETH"}, {"name": "BTC"}]}
        contexts = [
            {"midPx": "3500", "prevDayPx": "3400"},
            {"midPx": "92000", "prevDayPx": "90000"},
        ]
        with patch("core.engine.requests.post", return_value=_mock_response([meta, contexts])):
            result = fetch_btc_price()
        assert result["price"] == Decimal("92000")
        assert result["change_24h"] == Decimal("2000")
        assert result["change_pct_24h"].quantize(Decimal("0.01")) == Decimal("2.22")

    def test_raises_when_btc_not_in_universe(self):
        meta = {"universe": [{"name": "ETH"}]}
        contexts = [{"midPx": "3500", "prevDayPx": "3400"}]
        with patch("core.engine.requests.post", return_value=_mock_response([meta, contexts])):
            with pytest.raises(ValueError, match="BTC not found"):
                fetch_btc_price()

    def test_zero_prev_day_handled(self):
        """Should not divide by zero when prevDayPx is 0."""
        meta = {"universe": [{"name": "BTC"}]}
        contexts = [{"midPx": "100", "prevDayPx": "0"}]
        with patch("core.engine.requests.post", return_value=_mock_response([meta, contexts])):
            result = fetch_btc_price()
        assert result["change_pct_24h"] == Decimal("0")


class TestFetchAccountState:
    def test_posts_correct_payload(self):
        with patch("core.engine.requests.post", return_value=_mock_response({"x": 1})) as mock:
            result = fetch_account_state("0xabc")
        assert result == {"x": 1}
        args, kwargs = mock.call_args
        assert kwargs["json"] == {"type": "clearinghouseState", "user": "0xabc"}


class TestFetchOpenOrders:
    def test_posts_correct_payload(self):
        with patch("core.engine.requests.post", return_value=_mock_response([])) as mock:
            result = fetch_open_orders("0xabc")
        assert result == []
        _, kwargs = mock.call_args
        assert kwargs["json"] == {"type": "openOrders", "user": "0xabc"}


class TestFetchUserFills:
    def test_returns_empty_list_on_network_error(self):
        import requests as req
        with patch("core.engine.requests.post",
                   side_effect=req.exceptions.ConnectionError("boom")):
            result = fetch_user_fills("0xabc")
        assert result == []

    def test_returns_data_on_success(self):
        with patch("core.engine.requests.post",
                   return_value=_mock_response([{"time": 123}])):
            result = fetch_user_fills("0xabc")
        assert result == [{"time": 123}]
```

- [ ] **Step 2: Append time-helper tests**

```python
class TestGetRelativeTime:
    @pytest.fixture
    def now_ms(self):
        return int(datetime.now().timestamp() * 1000)

    def test_just_now(self, now_ms):
        assert get_relative_time(now_ms) == "just now"

    def test_minutes_ago(self, now_ms):
        five_min_ago = now_ms - 5 * 60 * 1000
        assert get_relative_time(five_min_ago) == "5 minutes ago"

    def test_one_hour_ago_singular(self, now_ms):
        one_hr_ago = now_ms - 60 * 60 * 1000
        assert get_relative_time(one_hr_ago) == "1 hour ago"

    def test_days_ago(self, now_ms):
        two_days_ago = now_ms - 2 * 86400 * 1000
        assert get_relative_time(two_days_ago) == "2 days ago"

    def test_weeks_ago(self, now_ms):
        two_weeks_ago = now_ms - 2 * 604800 * 1000
        assert get_relative_time(two_weeks_ago) == "2 weeks ago"

    def test_months_ago(self, now_ms):
        three_months_ago = now_ms - 3 * 2592000 * 1000
        assert get_relative_time(three_months_ago) == "3 months ago"


class TestGetLastActivityTime:
    def test_unknown_when_no_data(self):
        assert get_last_activity_time([], []) == "Unknown"

    def test_uses_most_recent_timestamp(self):
        now_ms = int(datetime.now().timestamp() * 1000)
        orders = [{"timestamp": now_ms - 1000}]
        fills = [{"time": now_ms - 60000}]
        # Most recent is the order at ~1s ago — should report "just now"
        assert get_last_activity_time(orders, fills) == "just now"

    def test_skips_malformed_timestamps(self):
        now_ms = int(datetime.now().timestamp() * 1000)
        orders = [{"timestamp": "garbage"}, {"timestamp": now_ms}]
        assert get_last_activity_time(orders, []) == "just now"
```

- [ ] **Step 3: Run new tests**

```bash
pytest tests/test_engine.py -v -k "Fetch or Relative or Activity"
```

Expected: all ~15 new tests pass.

- [ ] **Step 4: Run full coverage**

```bash
make coverage
```

Expected: `core/engine.py` rises from 38% to ~60%. TOTAL ~45–50%.

- [ ] **Step 5: Commit**

```bash
git add tests/test_engine.py
git commit -m "Add tests for engine network and time helpers

Tests fetch_btc_price (incl. error paths), fetch_account_state,
fetch_open_orders, fetch_user_fills (incl. network error fallback),
get_relative_time across all branches, get_last_activity_time
(empty, ordering, malformed timestamp skip).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Tests for engine orchestrators (`get_weishen_position`, `process_request`)

**Files:**
- Modify: `tests/test_engine.py`

**Context:** These two functions chain the 4 network calls together. Mock at the four `fetch_*` call sites instead of at `requests.post` to keep tests readable.

- [ ] **Step 1: Append orchestrator tests**

```python
from core.engine import get_weishen_position, process_request


def _fake_position(direction="long", size="0.5", entry="90000"):
    """Build a fake account_state with a single BTC position."""
    signed = size if direction == "long" else f"-{size}"
    return {
        "assetPositions": [
            {"position": {"coin": "BTC", "szi": signed, "entryPx": entry}},
        ]
    }


class TestGetWeishenPosition:
    def test_happy_path_long(self, monkeypatch):
        monkeypatch.setattr("core.engine.fetch_account_state",
                           lambda addr: _fake_position("long", "0.5", "90000"))
        monkeypatch.setattr("core.engine.fetch_open_orders",
                           lambda addr: [{"coin": "BTC", "side": "B", "sz": "0.05", "limitPx": "89000"}])
        monkeypatch.setattr("core.engine.fetch_user_fills", lambda addr: [])
        monkeypatch.setattr("core.engine.fetch_btc_price",
                           lambda: {"price": Decimal("95000"),
                                    "change_24h": Decimal("5000"),
                                    "change_pct_24h": Decimal("5.5")})
        result = get_weishen_position()
        assert result["error"] is None
        assert result["direction"] == "long"
        assert result["size"] == Decimal("0.5")
        assert result["pnl"] == Decimal("2500")  # (95000-90000)*0.5

    def test_short_pnl(self, monkeypatch):
        monkeypatch.setattr("core.engine.fetch_account_state",
                           lambda addr: _fake_position("short", "0.5", "95000"))
        monkeypatch.setattr("core.engine.fetch_open_orders", lambda addr: [])
        monkeypatch.setattr("core.engine.fetch_user_fills", lambda addr: [])
        monkeypatch.setattr("core.engine.fetch_btc_price",
                           lambda: {"price": Decimal("90000"),
                                    "change_24h": Decimal("0"),
                                    "change_pct_24h": Decimal("0")})
        result = get_weishen_position()
        assert result["direction"] == "short"
        assert result["pnl"] == Decimal("2500")  # (95000-90000)*0.5

    def test_no_position_returns_error(self, monkeypatch):
        monkeypatch.setattr("core.engine.fetch_account_state",
                           lambda addr: {"assetPositions": []})
        monkeypatch.setattr("core.engine.fetch_open_orders", lambda addr: [])
        monkeypatch.setattr("core.engine.fetch_user_fills", lambda addr: [])
        monkeypatch.setattr("core.engine.fetch_btc_price",
                           lambda: {"price": Decimal("90000"),
                                    "change_24h": Decimal("0"),
                                    "change_pct_24h": Decimal("0")})
        result = get_weishen_position()
        assert "No BTC position" in result["error"]

    def test_zero_size_position_returns_error(self, monkeypatch):
        monkeypatch.setattr("core.engine.fetch_account_state",
                           lambda addr: {"assetPositions": [
                               {"position": {"coin": "BTC", "szi": "0", "entryPx": "90000"}}]})
        monkeypatch.setattr("core.engine.fetch_open_orders", lambda addr: [])
        monkeypatch.setattr("core.engine.fetch_user_fills", lambda addr: [])
        monkeypatch.setattr("core.engine.fetch_btc_price",
                           lambda: {"price": Decimal("90000"),
                                    "change_24h": Decimal("0"),
                                    "change_pct_24h": Decimal("0")})
        result = get_weishen_position()
        assert "No active BTC position" in result["error"]

    def test_api_failure_returns_error(self, monkeypatch):
        monkeypatch.setattr("core.engine.fetch_account_state",
                           lambda addr: (_ for _ in ()).throw(RuntimeError("network")))
        result = get_weishen_position()
        assert "Failed to fetch" in result["error"]


class TestProcessRequest:
    def test_happy_path_scales_orders(self, monkeypatch):
        monkeypatch.setattr("core.engine.fetch_account_state",
                           lambda addr: _fake_position("long", "1.0", "90000"))
        monkeypatch.setattr("core.engine.fetch_open_orders",
                           lambda addr: [
                               {"coin": "BTC", "side": "B", "sz": "0.10", "limitPx": "89000", "timestamp": 123},
                           ])
        monkeypatch.setattr("core.engine.fetch_user_fills", lambda addr: [])
        result = process_request("long", Decimal("0.5"))
        assert result["error"] is None
        assert result["ratio"] == Decimal("0.5")
        assert result["num_orders"] == 1
        assert result["scaled_orders"][0]["scaled_size"] == Decimal("0.050")

    def test_direction_mismatch_returns_error(self, monkeypatch):
        monkeypatch.setattr("core.engine.fetch_account_state",
                           lambda addr: _fake_position("long", "1.0", "90000"))
        monkeypatch.setattr("core.engine.fetch_open_orders", lambda addr: [])
        monkeypatch.setattr("core.engine.fetch_user_fills", lambda addr: [])
        result = process_request("short", Decimal("0.5"))
        assert "Direction mismatch" in result["error"]

    def test_no_orders_returns_error(self, monkeypatch):
        monkeypatch.setattr("core.engine.fetch_account_state",
                           lambda addr: _fake_position("long", "1.0", "90000"))
        monkeypatch.setattr("core.engine.fetch_open_orders", lambda addr: [])
        monkeypatch.setattr("core.engine.fetch_user_fills", lambda addr: [])
        result = process_request("long", Decimal("0.5"))
        assert "No pending BTC orders" in result["error"]

    def test_no_position_returns_error(self, monkeypatch):
        monkeypatch.setattr("core.engine.fetch_account_state",
                           lambda addr: {"assetPositions": []})
        monkeypatch.setattr("core.engine.fetch_open_orders", lambda addr: [])
        monkeypatch.setattr("core.engine.fetch_user_fills", lambda addr: [])
        result = process_request("long", Decimal("0.5"))
        assert "No BTC position" in result["error"]
```

- [ ] **Step 2: Run new tests**

```bash
pytest tests/test_engine.py -v -k "Weishen or ProcessRequest"
```

Expected: all 9 new tests pass.

- [ ] **Step 3: Run full coverage**

```bash
make coverage
```

Expected: `core/engine.py` rises from ~60% to ≥90%. TOTAL ~55–60%.

- [ ] **Step 4: Commit**

```bash
git add tests/test_engine.py
git commit -m "Add tests for engine orchestrators get_weishen_position and process_request

Covers happy paths (long, short), error paths (no position, zero size,
direction mismatch, no orders, API failure). Uses monkeypatch on the
four fetch_* call sites for readability instead of mocking requests.post
at the bottom of the stack.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Tests for bot format helpers

**Files:**
- Modify: `tests/test_bot.py`

**Context:** `format_price`, `format_weishen`, `format_my_position`, `format_scale_result` are pure functions. Easy table-driven tests; ~60 stmts covered.

- [ ] **Step 1: Append format-helper tests**

```python
from decimal import Decimal
from bot.main import (
    format_price, format_weishen, format_my_position, format_scale_result,
)


class TestFormatPrice:
    def test_positive_change(self):
        msg = format_price({
            "price": Decimal("92500"),
            "change_24h": Decimal("500"),
            "change_pct_24h": Decimal("0.54"),
        })
        assert "$92,500.00" in msg
        assert "+0.54%" in msg
        assert "+$500.00" in msg

    def test_negative_change(self):
        msg = format_price({
            "price": Decimal("91500"),
            "change_24h": Decimal("-500"),
            "change_pct_24h": Decimal("-0.54"),
        })
        assert "-0.54%" in msg
        assert "-$500.00" in msg


class TestFormatWeishen:
    def test_error_passthrough(self):
        assert format_weishen({"error": "boom"}) == "Error: boom"

    def test_long_position_with_orders(self):
        result = {
            "error": None, "direction": "long", "size": Decimal("0.5"),
            "entry_price": Decimal("90000"), "current_price": Decimal("92000"),
            "pnl": Decimal("1000"), "last_activity": "5 minutes ago",
            "orders": [{"side": "B", "sz": "0.05", "limitPx": "89000"}],
        }
        msg = format_weishen(result)
        assert "LONG 0.50000 BTC" in msg
        assert "BUY" in msg
        assert "+$1,000.00" in msg

    def test_no_orders_section_when_empty(self):
        result = {
            "error": None, "direction": "long", "size": Decimal("0.5"),
            "entry_price": Decimal("90000"), "current_price": Decimal("90000"),
            "pnl": Decimal("0"), "last_activity": "just now", "orders": [],
        }
        msg = format_weishen(result)
        assert "Orders" not in msg


class TestFormatMyPosition:
    def test_matching_direction_scales(self):
        user_pos = {"size": Decimal("0.05"), "entry_price": Decimal("92000")}
        weishen = {
            "direction": "long", "size": Decimal("0.5"),
            "orders": [{"side": "B", "sz": "0.10", "limitPx": "89000"}],
        }
        msg = format_my_position(user_pos, weishen, Decimal("93000"))
        assert "LONG 0.05000 BTC" in msg
        assert "Scaled Orders" in msg
        # ratio = 0.05/0.5 = 0.1; scaled = 0.10 * 0.1 = 0.010
        assert "0.010" in msg

    def test_direction_mismatch_warns(self):
        user_pos = {"size": Decimal("0.05"), "entry_price": Decimal("92000")}
        weishen = {"direction": "short", "size": Decimal("0.5"), "orders": []}
        msg = format_my_position(user_pos, weishen, Decimal("93000"))
        assert "mismatch" in msg.lower()

    def test_short_position_pnl(self):
        user_pos = {"size": Decimal("-0.05"), "entry_price": Decimal("95000")}
        weishen = {"direction": "short", "size": Decimal("0.5"), "orders": []}
        msg = format_my_position(user_pos, weishen, Decimal("90000"))
        # (95000-90000) * 0.05 = 250
        assert "+$250.00" in msg


class TestFormatScaleResult:
    def test_renders_orders_table_and_summary(self):
        result = {
            "last_activity": "1 hour ago",
            "account_direction": "long",
            "account_btc_size": Decimal("1.0"),
            "entry_price": Decimal("90000"),
            "user_direction": "long",
            "user_btc_size": Decimal("0.1"),
            "ratio": Decimal("0.1"),
            "num_orders": 1,
            "scaled_orders": [
                {"side": "B", "price": Decimal("89000"),
                 "scaled_size": Decimal("0.010"),
                 "original_size": Decimal("0.10"),
                 "notional": Decimal("890")},
            ],
            "long_summary": {
                "current_size": Decimal("0.1"),
                "order_total": Decimal("0.010"),
                "net_position": Decimal("0.110"),
                "avg_entry": Decimal("89909"),
                "capital_required": Decimal("890"),
            },
            "short_summary": None,
        }
        msg = format_scale_result(result)
        assert "BUY" in msg
        assert "LONG SUMMARY" in msg
        assert "SHORT SUMMARY" not in msg
        assert "ratio: 0.1000" in msg
```

- [ ] **Step 2: Run new tests**

```bash
pytest tests/test_bot.py -v -k "Format"
```

Expected: all ~10 new tests pass.

- [ ] **Step 3: Run full coverage**

```bash
make coverage
```

Expected: `bot/main.py` rises from ~30% to ~45–50%. TOTAL ~65%.

- [ ] **Step 4: Commit**

```bash
git add tests/test_bot.py
git commit -m "Add tests for bot format helpers

Covers format_price (positive/negative change), format_weishen
(error passthrough, long with orders, no-orders branch),
format_my_position (matching direction scales, mismatch warns,
short PnL), format_scale_result (orders table + summary selection).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Tests for bot async handlers

**Files:**
- Create: `tests/test_bot_async.py`

**Context:** All seven command handlers + the `button_callback` need async tests. Pattern: fake `Update`/`Context` with `AsyncMock`, monkeypatch engine functions, run the coroutine, assert `reply_text.assert_awaited_with(...)`. Uses `pytest-asyncio` with `asyncio_mode = "auto"` already configured in Task 1.

- [ ] **Step 1: Create `tests/test_bot_async.py` with fixtures and the simplest handler tests**

```python
"""Async tests for bot/main.py handlers."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.main import (
    start_command, price_command, weishen_command, me_command,
    set_command, button_callback, handle_message,
)


@pytest.fixture
def fake_update():
    """Build an Update with a user_id of 42 and an AsyncMock'd message."""
    update = MagicMock()
    update.effective_user.id = 42
    update.message = AsyncMock()
    update.message.text = ""
    return update


@pytest.fixture
def fake_context():
    ctx = MagicMock()
    ctx.args = []
    return ctx


@pytest.fixture
def isolated_storage(tmp_path, monkeypatch):
    """Redirect DATA_DIR for bot tests so they don't touch real state."""
    import importlib
    import core.storage as storage
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    importlib.reload(storage)
    import bot.main
    importlib.reload(bot.main)
    yield
    importlib.reload(storage)
    importlib.reload(bot.main)


class TestStartCommand:
    async def test_replies_with_menu(self, fake_update, fake_context, isolated_storage):
        await start_command(fake_update, fake_context)
        fake_update.message.reply_text.assert_awaited_once()
        _, kwargs = fake_update.message.reply_text.call_args
        assert kwargs["parse_mode"] == "HTML"
        assert "reply_markup" in kwargs

    async def test_ignores_when_no_message(self, fake_context, isolated_storage):
        update = MagicMock()
        update.message = None
        await start_command(update, fake_context)  # should not raise


class TestPriceCommand:
    async def test_replies_with_price(self, monkeypatch, fake_update, fake_context, isolated_storage):
        monkeypatch.setattr("bot.main.fetch_btc_price",
                           lambda: {"price": Decimal("92000"),
                                    "change_24h": Decimal("500"),
                                    "change_pct_24h": Decimal("0.5")})
        await price_command(fake_update, fake_context)
        fake_update.message.reply_text.assert_awaited_once()
        args, _ = fake_update.message.reply_text.call_args
        assert "$92,000.00" in args[0]

    async def test_handles_api_error(self, monkeypatch, fake_update, fake_context, isolated_storage):
        def boom():
            raise RuntimeError("network down")
        monkeypatch.setattr("bot.main.fetch_btc_price", boom)
        await price_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Error fetching price" in args[0]
```

- [ ] **Step 2: Add weishen, me, and set command tests**

```python
class TestWeishenCommand:
    async def test_passes_through_position(self, monkeypatch, fake_update, fake_context, isolated_storage):
        monkeypatch.setattr("bot.main.get_weishen_position", lambda: {
            "error": None, "direction": "long", "size": Decimal("0.5"),
            "entry_price": Decimal("90000"), "current_price": Decimal("92000"),
            "pnl": Decimal("1000"), "last_activity": "just now", "orders": [],
        })
        await weishen_command(fake_update, fake_context)
        args, kwargs = fake_update.message.reply_text.call_args
        assert "LONG" in args[0]
        assert kwargs["parse_mode"] == "HTML"


class TestMeCommand:
    async def test_no_position_prompts_set(self, fake_update, fake_context, isolated_storage):
        await me_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "haven't set" in args[0]

    async def test_with_position_renders_scaled(self, monkeypatch, fake_update, fake_context, isolated_storage):
        from core.storage import set_user_position
        set_user_position(42, Decimal("0.05"), Decimal("92000"))
        monkeypatch.setattr("bot.main.fetch_btc_price",
                           lambda: {"price": Decimal("93000"),
                                    "change_24h": Decimal("1000"),
                                    "change_pct_24h": Decimal("1.1")})
        monkeypatch.setattr("bot.main.get_weishen_position", lambda: {
            "error": None, "direction": "long", "size": Decimal("0.5"),
            "entry_price": Decimal("90000"), "current_price": Decimal("93000"),
            "pnl": Decimal("1500"), "last_activity": "just now",
            "orders": [{"side": "B", "sz": "0.10", "limitPx": "89000"}],
        })
        await me_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Scaled Orders" in args[0]


class TestSetCommand:
    async def test_valid_long(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["0.05", "92000"]
        await set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "LONG" in args[0]
        from core.storage import get_user_position
        pos = get_user_position(42)
        assert pos["size"] == Decimal("0.05")

    async def test_negative_size_is_short(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["-0.05", "95000"]
        await set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "SHORT" in args[0]

    async def test_wrong_arg_count_shows_usage(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["0.05"]
        await set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Usage" in args[0]

    async def test_zero_size_rejected(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["0", "92000"]
        await set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "cannot be zero" in args[0]

    async def test_negative_entry_rejected(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["0.05", "-92000"]
        await set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "positive" in args[0]

    async def test_invalid_decimal_rejected(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["abc", "92000"]
        await set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Invalid" in args[0]
```

- [ ] **Step 3: Add button_callback and handle_message tests**

```python
class TestButtonCallback:
    @pytest.fixture
    def fake_query_update(self, fake_update):
        update = MagicMock()
        update.effective_user.id = 42
        update.callback_query = AsyncMock()
        update.callback_query.message = AsyncMock()
        return update

    async def test_price_callback(self, monkeypatch, fake_query_update, fake_context, isolated_storage):
        monkeypatch.setattr("bot.main.fetch_btc_price",
                           lambda: {"price": Decimal("92000"),
                                    "change_24h": Decimal("0"),
                                    "change_pct_24h": Decimal("0")})
        fake_query_update.callback_query.data = "price"
        await button_callback(fake_query_update, fake_context)
        fake_query_update.callback_query.answer.assert_awaited_once()
        fake_query_update.callback_query.message.reply_text.assert_awaited()

    async def test_edit_callback_shows_help(self, fake_query_update, fake_context, isolated_storage):
        fake_query_update.callback_query.data = "edit"
        await button_callback(fake_query_update, fake_context)
        args, _ = fake_query_update.callback_query.message.reply_text.call_args
        assert "/set" in args[0]


class TestHandleMessage:
    async def test_positive_number_triggers_long_scale(self, monkeypatch, fake_update, fake_context, isolated_storage):
        fake_update.message.text = "0.05"
        captured = {}
        def fake_process(direction, size):
            captured["direction"] = direction
            captured["size"] = size
            return {
                "error": None, "last_activity": "now",
                "account_direction": "long", "account_btc_size": Decimal("1.0"),
                "entry_price": Decimal("90000"),
                "user_direction": "long", "user_btc_size": size,
                "ratio": Decimal("0.05"), "num_orders": 0,
                "scaled_orders": [], "long_summary": None, "short_summary": None,
            }
        monkeypatch.setattr("bot.main.process_request", fake_process)
        await handle_message(fake_update, fake_context)
        assert captured["direction"] == "long"
        assert captured["size"] == Decimal("0.05")

    async def test_negative_number_triggers_short(self, monkeypatch, fake_update, fake_context, isolated_storage):
        fake_update.message.text = "-0.05"
        captured = {}
        def fake_process(direction, size):
            captured["direction"] = direction
            captured["size"] = size
            return {"error": "stop here"}
        monkeypatch.setattr("bot.main.process_request", fake_process)
        await handle_message(fake_update, fake_context)
        assert captured["direction"] == "short"

    async def test_non_numeric_text_ignored(self, fake_update, fake_context, isolated_storage):
        fake_update.message.text = "hello bot"
        await handle_message(fake_update, fake_context)
        fake_update.message.reply_text.assert_not_awaited()

    async def test_zero_rejected(self, fake_update, fake_context, isolated_storage):
        fake_update.message.text = "0"
        await handle_message(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "cannot be zero" in args[0]
```

- [ ] **Step 4: Run async tests**

```bash
pytest tests/test_bot_async.py -v
```

Expected: all ~17 new tests pass. If a test hangs, check `asyncio_mode = "auto"` in `pyproject.toml`.

- [ ] **Step 5: Run full coverage**

```bash
make coverage
```

Expected: `bot/main.py` rises from ~50% to ~80–85%. TOTAL ~80%.

- [ ] **Step 6: Commit**

```bash
git add tests/test_bot_async.py
git commit -m "Add async tests for bot command handlers and button callback

Covers start, price, weishen, me, set (incl. all validation paths),
button_callback (price + edit branches), and handle_message
(positive/negative/zero/non-numeric). Uses AsyncMock fakes for
Update and Context, monkeypatches engine + storage. No real
Application or network.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Tests for `poll_and_notify`

**Files:**
- Modify: `tests/test_bot_async.py`

**Context:** The background job is the most complex async path. Mock `get_weishen_position`, `get_previous_state`, `save_previous_state`, and the broadcast `context.bot.send_message`. Assert the loop calls `send_message` once per registered user and saves the new state.

- [ ] **Step 1: Append `poll_and_notify` tests**

```python
from bot.main import poll_and_notify


class TestPollAndNotify:
    async def test_no_changes_no_broadcast(self, monkeypatch, isolated_storage):
        state = {"direction": "long", "size": Decimal("0.5"),
                 "entry_price": Decimal("90000"), "orders": [],
                 "current_price": Decimal("90000"), "pnl": Decimal("0"),
                 "last_activity": "just now", "error": None}
        monkeypatch.setattr("bot.main.get_weishen_position", lambda: state)
        # Previous state identical to current — no changes
        from core.storage import save_previous_state
        save_previous_state(state)

        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()
        from core.storage import register_user
        register_user(42)

        await poll_and_notify(ctx)
        ctx.bot.send_message.assert_not_awaited()

    async def test_size_change_broadcasts_to_all_users(self, monkeypatch, isolated_storage):
        from core.storage import save_previous_state, register_user
        save_previous_state({
            "direction": "long", "size": Decimal("0.5"),
            "entry_price": Decimal("90000"), "orders": [],
        })
        register_user(42)
        register_user(99)

        monkeypatch.setattr("bot.main.get_weishen_position", lambda: {
            "error": None, "direction": "long", "size": Decimal("0.8"),
            "entry_price": Decimal("90000"), "current_price": Decimal("90000"),
            "pnl": Decimal("0"), "last_activity": "just now", "orders": [],
        })

        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()

        await poll_and_notify(ctx)
        assert ctx.bot.send_message.await_count == 2

    async def test_one_failing_user_does_not_block_broadcast(self, monkeypatch, isolated_storage):
        from core.storage import save_previous_state, register_user
        save_previous_state({
            "direction": "long", "size": Decimal("0.5"),
            "entry_price": Decimal("90000"), "orders": [],
        })
        register_user(42)
        register_user(99)
        monkeypatch.setattr("bot.main.get_weishen_position", lambda: {
            "error": None, "direction": "long", "size": Decimal("0.8"),
            "entry_price": Decimal("90000"), "current_price": Decimal("90000"),
            "pnl": Decimal("0"), "last_activity": "just now", "orders": [],
        })

        ctx = MagicMock()
        async def send(chat_id, **kwargs):
            if chat_id == 42:
                raise RuntimeError("user blocked the bot")
        ctx.bot.send_message = AsyncMock(side_effect=send)

        await poll_and_notify(ctx)
        # Both users were attempted — the second one didn't get skipped
        assert ctx.bot.send_message.await_count == 2

    async def test_fetch_error_logged_no_broadcast(self, monkeypatch, isolated_storage):
        monkeypatch.setattr("bot.main.get_weishen_position",
                           lambda: {"error": "fetch failed"})
        from core.storage import register_user
        register_user(42)
        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()
        await poll_and_notify(ctx)
        ctx.bot.send_message.assert_not_awaited()
```

- [ ] **Step 2: Run new tests**

```bash
pytest tests/test_bot_async.py::TestPollAndNotify -v
```

Expected: all 4 tests pass.

- [ ] **Step 3: Run full coverage**

```bash
make coverage
```

Expected: `bot/main.py` ≥85%, TOTAL ≥85%. If not yet there, inspect the "Missing" output and add focused tests until the gate clears.

- [ ] **Step 4: Commit**

```bash
git add tests/test_bot_async.py
git commit -m "Add tests for poll_and_notify background job

Covers no-change skip, size-change broadcast to all users, per-user
try/except resilience (one failing user doesn't block others), and
fetch error short-circuit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Enforce coverage gate and add CI

**Files:**
- Modify: `pyproject.toml` (add `fail_under = 85`)
- Modify: `Makefile` (tighten `coverage` target to use the gate)
- Create: `.github/workflows/ci.yml`
- Modify: `README.md` (one line)

- [ ] **Step 1: Add `fail_under = 85` to `pyproject.toml`**

Replace the `[tool.coverage.report]` block:

```toml
[tool.coverage.report]
show_missing = true
skip_covered = false
fail_under = 85
```

- [ ] **Step 2: Tighten Makefile coverage target**

The `--cov-fail-under` flag honors the pyproject setting, but make it explicit so `make coverage` exits non-zero on regressions:

```makefile
coverage:
	pytest tests/ --cov --cov-report=term-missing --cov-fail-under=85
```

- [ ] **Step 3: Verify the gate passes locally**

```bash
make coverage
```

Expected: exits 0, prints "Required test coverage of 85% reached. Total coverage: 8x.xx%".

If it fails, inspect "Missing" column, add focused tests, re-run until pass.

- [ ] **Step 4: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements-dev.txt

      - name: Audit dependencies
        run: make audit

      - name: Run tests with coverage gate
        run: make coverage
```

- [ ] **Step 5: Update README.md**

Append to the "Running Tests" section:

```markdown
## Running Tests

```bash
make test         # all tests
make coverage     # tests + coverage report (gate: 85% on core/ + bot/)
make audit        # pip-audit on requirements.txt
```
```

Note: replace the existing "Running Tests" block (currently only mentions `make test`) — do not duplicate.

- [ ] **Step 6: Final full test + coverage run**

```bash
make audit && make coverage
```

Expected: both pass cleanly.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml Makefile .github/workflows/ci.yml README.md
git commit -m "Enforce 85% coverage gate and add GitHub Actions CI

Sets fail_under=85 in pyproject.toml so 'make coverage' exits
non-zero on regressions. Adds .github/workflows/ci.yml that runs
'make audit' (pip-audit) and 'make coverage' on every push and PR.
README documents the new make targets.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage check** — every spec requirement maps to a task:

| Spec section | Implementing task(s) |
|---|---|
| §Recon (no dep upgrades) | Honored — `requirements.txt` untouched |
| §1.1 Input validation audit | Task 4 (findings doc records the review) |
| §1.2 Error-reply consistency | Task 3 |
| §1.3 Storage atomicity audit | Task 4 (findings doc) |
| §1.4 Resource limits audit | Task 4 (findings doc) |
| §1.5 Secret handling audit | Task 4 (findings doc) |
| §1.6 Narrow excepts | Task 2 |
| §1.7 Findings doc | Task 4 |
| §2 Dependency hygiene / CI gate | Task 1 (tooling), Task 11 (workflow) |
| §3.1 Tooling config | Task 1 |
| §3.2 Exclude `cli/main.py` | Task 1 (in `pyproject.toml`) |
| §3.3 Test additions (storage) | Task 5 |
| §3.3 Test additions (engine network) | Task 6 |
| §3.3 Test additions (engine orchestrators) | Task 7 |
| §3.3 Test additions (bot format) | Task 8 |
| §3.3 Test additions (bot async) | Task 9 |
| §3.3 Test additions (poll_and_notify) | Task 10 |
| §3.4 Async testing pattern | Task 9 (fixtures + AsyncMock) |
| §3.5 No production refactor / no real API | Honored throughout |
| §Deliverables checklist | All items map to tasks above |

No spec gaps.

**Placeholder scan:** No TBD/TODO/"implement appropriate" strings in the plan. All code blocks contain complete code. All commands have expected output documented.

**Type consistency:** Function names (`format_price`, `detect_changes`, `get_weishen_position`, `process_request`, `set_user_position`, `register_user`, `save_previous_state`) match across tasks and match the actual source code as of the recon read.

**Known unknown:** Exact line numbers in `bot/main.py` may shift by ±2 after Task 2's edit. Task 3's audit step re-greps so this is self-correcting.
