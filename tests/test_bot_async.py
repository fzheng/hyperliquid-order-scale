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
