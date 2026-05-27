"""Async tests for bot/main.py handlers."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.main


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
    importlib.reload(bot.main)
    yield
    importlib.reload(storage)
    importlib.reload(bot.main)


class TestStartCommand:
    async def test_replies_with_menu(self, fake_update, fake_context, isolated_storage):
        await bot.main.start_command(fake_update, fake_context)
        fake_update.message.reply_text.assert_awaited_once()
        _, kwargs = fake_update.message.reply_text.call_args
        assert kwargs["parse_mode"] == "HTML"
        assert "reply_markup" in kwargs

    async def test_ignores_when_no_message(self, fake_context, isolated_storage):
        update = MagicMock()
        update.message = None
        await bot.main.start_command(update, fake_context)  # should not raise


class TestPriceCommand:
    async def test_replies_with_price(self, monkeypatch, fake_update, fake_context, isolated_storage):
        monkeypatch.setattr("bot.main.fetch_btc_price",
                           lambda: {"price": Decimal("92000"),
                                    "change_24h": Decimal("500"),
                                    "change_pct_24h": Decimal("0.5")})
        await bot.main.price_command(fake_update, fake_context)
        fake_update.message.reply_text.assert_awaited_once()
        args, _ = fake_update.message.reply_text.call_args
        assert "$92,000.00" in args[0]

    async def test_handles_api_error(self, monkeypatch, fake_update, fake_context, isolated_storage):
        def boom():
            raise RuntimeError("network down")
        monkeypatch.setattr("bot.main.fetch_btc_price", boom)
        await bot.main.price_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Error fetching price" in args[0]


class TestWeishenCommand:
    async def test_passes_through_position(self, monkeypatch, fake_update, fake_context, isolated_storage):
        monkeypatch.setattr("bot.main.get_weishen_position", lambda: {
            "error": None, "direction": "long", "size": Decimal("0.5"),
            "entry_price": Decimal("90000"), "current_price": Decimal("92000"),
            "pnl": Decimal("1000"), "last_activity": "just now", "orders": [],
        })
        await bot.main.weishen_command(fake_update, fake_context)
        args, kwargs = fake_update.message.reply_text.call_args
        assert "LONG" in args[0]
        assert kwargs["parse_mode"] == "HTML"


class TestMeCommand:
    async def test_no_position_prompts_set(self, fake_update, fake_context, isolated_storage):
        await bot.main.me_command(fake_update, fake_context)
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
        await bot.main.me_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Scaled Orders" in args[0]


class TestSetCommand:
    async def test_valid_long(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["0.05", "92000"]
        await bot.main.set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "LONG" in args[0]
        from core.storage import get_user_position
        pos = get_user_position(42)
        assert pos["size"] == Decimal("0.05")

    async def test_negative_size_is_short(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["-0.05", "95000"]
        await bot.main.set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "SHORT" in args[0]

    async def test_wrong_arg_count_shows_usage(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["0.05"]
        await bot.main.set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Usage" in args[0]

    async def test_zero_size_rejected(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["0", "92000"]
        await bot.main.set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "cannot be zero" in args[0]

    async def test_negative_entry_rejected(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["0.05", "-92000"]
        await bot.main.set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "positive" in args[0]

    async def test_invalid_decimal_rejected(self, fake_update, fake_context, isolated_storage):
        fake_context.args = ["abc", "92000"]
        await bot.main.set_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Invalid" in args[0]


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
        await bot.main.button_callback(fake_query_update, fake_context)
        fake_query_update.callback_query.answer.assert_awaited_once()
        fake_query_update.callback_query.message.reply_text.assert_awaited()

    async def test_edit_callback_shows_help(self, fake_query_update, fake_context, isolated_storage):
        fake_query_update.callback_query.data = "edit"
        await bot.main.button_callback(fake_query_update, fake_context)
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
        await bot.main.handle_message(fake_update, fake_context)
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
        await bot.main.handle_message(fake_update, fake_context)
        assert captured["direction"] == "short"

    async def test_non_numeric_text_ignored(self, fake_update, fake_context, isolated_storage):
        fake_update.message.text = "hello bot"
        await bot.main.handle_message(fake_update, fake_context)
        fake_update.message.reply_text.assert_not_awaited()

    async def test_zero_rejected(self, fake_update, fake_context, isolated_storage):
        fake_update.message.text = "0"
        await bot.main.handle_message(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "cannot be zero" in args[0]


class TestCoverageEdgeCases:
    """Extra tests to push bot/main.py coverage over 85%."""

    async def test_price_command_no_message(self, fake_context, isolated_storage):
        update = MagicMock()
        update.message = None
        await bot.main.price_command(update, fake_context)  # should not raise

    async def test_weishen_command_no_message(self, fake_context, isolated_storage):
        update = MagicMock()
        update.message = None
        await bot.main.weishen_command(update, fake_context)  # should not raise

    async def test_me_command_no_message(self, fake_context, isolated_storage):
        update = MagicMock()
        update.message = None
        await bot.main.me_command(update, fake_context)  # should not raise

    async def test_me_command_no_user_id(self, fake_update, fake_context, isolated_storage):
        fake_update.effective_user = None
        await bot.main.me_command(fake_update, fake_context)  # should not raise

    async def test_me_command_fetch_error(self, monkeypatch, fake_update, fake_context, isolated_storage):
        from core.storage import set_user_position
        set_user_position(42, Decimal("0.05"), Decimal("90000"))
        def boom():
            raise RuntimeError("network down")
        monkeypatch.setattr("bot.main.fetch_btc_price", boom)
        monkeypatch.setattr("bot.main.get_weishen_position", lambda: {})
        await bot.main.me_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Error fetching data" in args[0]

    async def test_me_command_weishen_error(self, monkeypatch, fake_update, fake_context, isolated_storage):
        from core.storage import set_user_position
        set_user_position(42, Decimal("0.05"), Decimal("90000"))
        monkeypatch.setattr("bot.main.fetch_btc_price",
                           lambda: {"price": Decimal("92000"), "change_24h": Decimal("0"),
                                    "change_pct_24h": Decimal("0")})
        monkeypatch.setattr("bot.main.get_weishen_position",
                           lambda: {"error": "API down"})
        await bot.main.me_command(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Error fetching Weishen" in args[0]

    async def test_handle_message_no_message(self, fake_update, fake_context, isolated_storage):
        fake_update.message = None
        await bot.main.handle_message(fake_update, fake_context)  # should not raise

    async def test_handle_message_no_text(self, fake_update, fake_context, isolated_storage):
        fake_update.message.text = None
        await bot.main.handle_message(fake_update, fake_context)  # should not raise

    async def test_handle_message_process_exception(self, monkeypatch, fake_update, fake_context, isolated_storage):
        fake_update.message.text = "0.05"
        def boom(direction, size):
            raise RuntimeError("API error")
        monkeypatch.setattr("bot.main.process_request", boom)
        await bot.main.handle_message(fake_update, fake_context)
        args, _ = fake_update.message.reply_text.call_args
        assert "Error fetching data" in args[0]

    async def test_poll_and_notify_outer_exception(self, monkeypatch, isolated_storage):
        """Cover the outer except in poll_and_notify."""
        def boom():
            raise RuntimeError("unexpected crash")
        monkeypatch.setattr("bot.main.get_weishen_position", boom)
        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()
        await bot.main.poll_and_notify(ctx)  # should not raise; exception is logged


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

        await bot.main.poll_and_notify(ctx)
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

        await bot.main.poll_and_notify(ctx)
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

        await bot.main.poll_and_notify(ctx)
        # Both users were attempted — the second one didn't get skipped
        assert ctx.bot.send_message.await_count == 2

    async def test_fetch_error_logged_no_broadcast(self, monkeypatch, isolated_storage):
        monkeypatch.setattr("bot.main.get_weishen_position",
                           lambda: {"error": "fetch failed"})
        from core.storage import register_user
        register_user(42)
        ctx = MagicMock()
        ctx.bot.send_message = AsyncMock()
        await bot.main.poll_and_notify(ctx)
        ctx.bot.send_message.assert_not_awaited()
