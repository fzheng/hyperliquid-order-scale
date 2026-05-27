---
name: modifying-telegram-bot
description: Use when adding, removing, or editing handlers, commands, inline buttons, background jobs, or notification logic in this repo's Telegram bot at bot/main.py — including changes to message formatting, change detection, or the JobQueue poller.
---

# Modifying the Telegram Bot

## Overview

The bot is one file: `bot/main.py`. It uses `python-telegram-bot[job-queue]` and shares all Hyperliquid logic with the CLI via `core/engine.py`. Storage is JSON files in `core/storage.py`. Tests live in `tests/test_bot.py` and mock the network.

## Non-negotiables

| Rule | Why |
|---|---|
| Wrap blocking calls in `await asyncio.to_thread(...)` | `requests` is sync; calling it in an async handler blocks the event loop. |
| Use `Decimal`, never `float`, for prices/sizes/P&L | Float drift corrupts position math. The whole codebase is Decimal-clean. |
| Guard with `if not update.message: return` | Edited messages, channel posts, and reactions arrive as updates with no `message`. |
| Get user IDs via `get_user_id(update)` (returns `int \| None`) | Channel posts and anonymous group admins have no `effective_user`. |
| Call `register_user(user_id)` in every handler that has a user_id | Users opt into the broadcast list by interacting with anything. |
| Send with `parse_mode="HTML"` | The whole bot uses HTML, never Markdown. Don't mix. |
| Hyperliquid side codes: `"B"` = buy, `"A"` = sell (ask) | Convert to `BUY`/`SELL` only at the display layer. |

## Adding a command

```python
async def pnl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_id = get_user_id(update)
    if user_id:
        register_user(user_id)
    try:
        result = await asyncio.to_thread(get_weishen_position)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return
    if result.get("error"):
        await update.message.reply_text(f"Error: {result['error']}")
        return
    sign = "+" if result["pnl"] >= 0 else ""
    await update.message.reply_text(
        f"<b>P&L:</b> {sign}${result['pnl']:,.2f}", parse_mode="HTML"
    )
```

Register in `main()` next to the other commands:

```python
app.add_handler(CommandHandler("pnl", pnl_command))
```

If the command also needs a menu button, add a row to `get_main_menu_keyboard()` with `callback_data="pnl"` and a branch in `button_callback()` that runs the same logic via `query.message.reply_text(...)`. The callback path has no `update.message` — use `query.message` and skip the `update.message` guard.

## Adding a background job

```python
async def my_job(context: ContextTypes.DEFAULT_TYPE):
    try:
        data = await asyncio.to_thread(some_blocking_fetch)
        for user_id in get_all_users():
            try:
                await context.bot.send_message(
                    chat_id=user_id, text="...", parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Failed to notify {user_id}: {e}")
    except Exception as e:
        logger.error(f"my_job error: {e}")
```

Register in `main()`:

```python
app.job_queue.run_repeating(my_job, interval=300, first=10)
```

Per-user `try/except` inside the broadcast loop is mandatory — one blocked or banned user must not abort the rest of the broadcast.

## Editing notification format / change detection

`detect_changes` compares `prev_state.json` against the current weishen snapshot. Two non-obvious gotchas when editing it:

1. **Normalize numeric fields before comparing.** The API sometimes returns the same value as `"0.05"` vs `0.05`. Use the existing `normalize_val` helper (or `Decimal(str(...))`), otherwise you'll fire spurious "modified" events on every poll.
2. **Normalize `oid` to string** before set-diffing prev vs curr orders.

`format_changes` enforces Telegram's `TELEGRAM_MAX_LENGTH = 4096` by dropping overflow into a `"... and N more changes"` line. If you add long per-change strings, account for them in the `reserved` calculation.

`save_previous_state` controls the on-disk shape of `prev_state.json`. If you change which fields are persisted, old snapshots become unreadable on the next poll — either bump the format and parse defensively, or accept one missed comparison after deploy.

## Testing

`tests/test_bot.py` imports functions directly and tests them as pure logic. Don't spin up a real `Application`.

```python
from bot.main import detect_changes

def test_size_change_detected():
    prev = {"direction": "long", "size": "0.5", "entry_price": "90000", "orders": []}
    curr = {"direction": "long", "size": Decimal("0.6"),
            "entry_price": Decimal("90000"), "orders": []}
    changes = detect_changes(prev, curr)
    assert any("Size" in c for c in changes)
```

For tests that touch engine calls, mock `requests.post` with `unittest.mock.patch` — same pattern as `tests/test_engine.py`. Never let a test hit the live API.

Run a single test:

```bash
python -m pytest tests/test_bot.py::TestChangeDetection::test_size_change_detected -v
```

## Local run/debug

1. Create a throwaway bot with [@BotFather](https://t.me/BotFather) and copy the token. Don't use a production token for development.
2. `.env`:
   ```
   TELEGRAM_BOT_TOKEN=<your-test-token>
   HYPERLIQUID_ADDRESS=0x...     # optional, defaults to weishen
   DATA_DIR=.dev-data            # keeps test JSON state out of the repo root
   ```
3. `make bot` — logs print to stdout. The poller runs every `POLL_INTERVAL = 600`s; shrink it to ~30s while iterating on change-detection, then restore before committing.

## Common mistakes

| Mistake | Fix |
|---|---|
| Calling `requests.post` directly in an async handler | Wrap in `await asyncio.to_thread(...)`. |
| Using `float` on prices or sizes | `Decimal(str(value))`. |
| Forgetting `register_user(user_id)` | The user silently misses all future notifications. |
| Mixing HTML and Markdown in one message | Pick HTML; escape `<`, `>`, `&` if interpolating user input. |
| Comparing API numeric fields raw | Normalize via `Decimal(str(...))` or `normalize_val`. |
| Crashing the broadcast on one failing user | Per-user `try/except` inside the loop. |
| Changing `prev_state.json` shape without thought | Old snapshot fails to parse next poll — version it or parse defensively. |
