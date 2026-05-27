# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A tool that tracks a Hyperliquid account's BTC perp position and pending orders, then scales those orders proportionally to a user-supplied position size. Ships as both a CLI and a Telegram bot. Python 3.12.

## Common commands

```bash
make install                          # pip install -r requirements.txt
make run                              # run CLI (python -m cli.main)
make bot                              # run Telegram bot (python -m bot.main)
make test                             # pytest tests/ -v
python -m pytest tests/test_engine.py::TestScaleOrders -v   # run a single class
python -m pytest tests/test_engine.py::TestScaleOrders::test_long_scale_basic   # run a single test
make clean                            # remove __pycache__ and .pytest_cache
```

Required env vars (via `.env` or environment):
- `TELEGRAM_BOT_TOKEN` — required for `make bot`
- `HYPERLIQUID_ADDRESS` — optional, defaults to weishen's hard-coded address in `core/engine.py`
- `DATA_DIR` — directory for JSON state files; defaults to `.`. Set to `/data` on Railway for persistent storage.

## Architecture

Three-layer separation with `core/` as the only place that knows about Hyperliquid:

- **`core/engine.py`** — all business logic and the only module that calls the Hyperliquid API (`https://api.hyperliquid.xyz/info`). All money math uses `Decimal`, never `float`. Key entry points:
  - `process_request(direction, size)` — the main CLI/quick-scale flow: fetches account state, validates direction matches, computes ratio, scales orders, returns dict with `long_summary`/`short_summary`.
  - `get_weishen_position()` — read-only snapshot of the tracked account's position + orders + price; used by the bot's `/weishen`, `/me`, and the background poller.
  - `scale_orders(orders, ratio)` — pure function, no I/O; sizes rounded down to 0.001 BTC via `ROUND_DOWN`.

- **`core/storage.py`** — JSON-file persistence with a `threading.Lock` per file and `_atomic_write` (tempfile + `os.replace`). Three files under `DATA_DIR`:
  - `user_state.json` — each Telegram user's stored position (signed size + entry price).
  - `registered_users.json` — set of user IDs to notify on poll changes.
  - `prev_state.json` — last observed weishen snapshot, used by the bot's change detector.
  Decimals are serialized as strings (`str(Decimal)`) and re-parsed on load to avoid float drift.

- **`bot/main.py`** — Telegram bot built on `python-telegram-bot[job-queue]`. All blocking `requests` calls are wrapped in `asyncio.to_thread(...)` — never call engine functions directly from async handlers. A repeating `JobQueue` job (`poll_and_notify`, every 600s) diffs the current weishen snapshot against `prev_state.json` via `detect_changes`, formats with `format_changes` (respecting the 4096-char Telegram limit), and broadcasts to all registered users. Every command handler also calls `register_user(user_id)` so opening any command opts you into notifications.

- **`cli/main.py`** — thin interactive prompt around `process_request`; ANSI colors for terminal output. No state, no storage.

### Conventions worth knowing
- **Hyperliquid order side encoding:** API uses `"B"` for buy and `"A"` for sell (ask). The code converts to `BUY`/`SELL` only at the display layer.
- **Signed vs. absolute sizes:** the API's `szi` field is signed (negative = short). User-facing `size` is usually absolute, with `direction` carried separately. `set_user_position` stores the signed size. Be deliberate about which convention a function takes.
- **Change detection** in `bot/main.py:detect_changes` normalizes order `oid` and numeric fields to strings before comparing, because the API sometimes returns the same value as `"0.05"` vs `0.05`. Preserve that normalization when adding new comparison fields.
- **Tests mock the network.** `tests/test_engine.py` uses `unittest.mock.patch` against `requests.post`; no test should hit the real Hyperliquid API.

## Deployment

Railway via `railway.toml` + `Procfile`. The worker process is `python -m bot.main`. `DATA_DIR=/data` must be set so the JSON state files survive restarts.
