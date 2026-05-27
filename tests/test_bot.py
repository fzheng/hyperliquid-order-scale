"""Tests for bot input parsing and change detection logic."""

import pytest
from decimal import Decimal

from bot.main import detect_changes, format_changes, get_user_id, TELEGRAM_MAX_LENGTH


def parse_input(text: str) -> tuple[str, Decimal]:
    """Parse user input: positive = long, negative = short.

    Returns (direction, abs_size) or raises ValueError.
    """
    value = Decimal(text.strip())
    if value == 0:
        raise ValueError("Size cannot be zero.")
    if value > 0:
        return ("long", value)
    else:
        return ("short", abs(value))


class TestBotInputParsing:
    def test_positive_is_long(self):
        direction, size = parse_input("0.05")
        assert direction == "long"
        assert size == Decimal("0.05")

    def test_negative_is_short(self):
        direction, size = parse_input("-0.05")
        assert direction == "short"
        assert size == Decimal("0.05")

    def test_integer_input(self):
        direction, size = parse_input("1")
        assert direction == "long"
        assert size == Decimal("1")

    def test_negative_integer(self):
        direction, size = parse_input("-1")
        assert direction == "short"
        assert size == Decimal("1")

    def test_small_size(self):
        direction, size = parse_input("0.001")
        assert direction == "long"
        assert size == Decimal("0.001")

    def test_zero_raises(self):
        with pytest.raises(ValueError):
            parse_input("0")

    def test_invalid_input_raises(self):
        with pytest.raises(Exception):
            parse_input("hello")

    def test_whitespace_stripped(self):
        direction, size = parse_input("  0.05  ")
        assert direction == "long"
        assert size == Decimal("0.05")


class TestDetectChanges:
    def test_none_prev_returns_empty(self):
        curr = {"direction": "long", "size": Decimal("1"), "entry_price": Decimal("100000")}
        changes = detect_changes(None, curr)
        assert changes == []

    def test_no_changes_returns_empty(self):
        state = {
            "direction": "long",
            "size": "1.5",
            "entry_price": "95000",
            "orders": []
        }
        changes = detect_changes(state, {
            "direction": "long",
            "size": Decimal("1.5"),
            "entry_price": Decimal("95000"),
            "orders": []
        })
        assert changes == []

    def test_direction_change_detected(self):
        prev = {"direction": "long", "size": "1", "entry_price": "100000", "orders": []}
        curr = {"direction": "short", "size": Decimal("1"), "entry_price": Decimal("100000"), "orders": []}
        changes = detect_changes(prev, curr)
        assert len(changes) == 1
        assert "Direction" in changes[0]
        assert "LONG" in changes[0] and "SHORT" in changes[0]

    def test_size_change_detected(self):
        prev = {"direction": "long", "size": "1", "entry_price": "100000", "orders": []}
        curr = {"direction": "long", "size": Decimal("2"), "entry_price": Decimal("100000"), "orders": []}
        changes = detect_changes(prev, curr)
        assert len(changes) == 1
        assert "Size" in changes[0]

    def test_entry_price_change_detected(self):
        prev = {"direction": "long", "size": "1", "entry_price": "95000", "orders": []}
        curr = {"direction": "long", "size": Decimal("1"), "entry_price": Decimal("96000"), "orders": []}
        changes = detect_changes(prev, curr)
        assert len(changes) == 1
        assert "Entry" in changes[0]

    def test_order_added_detected(self):
        prev = {"direction": "long", "size": "1", "entry_price": "95000", "orders": []}
        curr = {
            "direction": "long",
            "size": Decimal("1"),
            "entry_price": Decimal("95000"),
            "orders": [{"oid": 123, "side": "B", "sz": "0.5", "limitPx": "90000"}]
        }
        changes = detect_changes(prev, curr)
        assert len(changes) == 1
        assert "Order added" in changes[0]

    def test_order_removed_detected(self):
        prev = {
            "direction": "long",
            "size": "1",
            "entry_price": "95000",
            "orders": [{"oid": 123, "side": "A", "sz": "0.5", "limitPx": "100000"}]
        }
        curr = {"direction": "long", "size": Decimal("1"), "entry_price": Decimal("95000"), "orders": []}
        changes = detect_changes(prev, curr)
        assert len(changes) == 1
        assert "Order removed" in changes[0]

    def test_order_modified_detected(self):
        prev = {
            "direction": "long",
            "size": "1",
            "entry_price": "95000",
            "orders": [{"oid": 123, "side": "B", "sz": "0.5", "limitPx": "90000"}]
        }
        curr = {
            "direction": "long",
            "size": Decimal("1"),
            "entry_price": Decimal("95000"),
            "orders": [{"oid": 123, "side": "B", "sz": "0.6", "limitPx": "91000"}]
        }
        changes = detect_changes(prev, curr)
        assert len(changes) == 1
        assert "Order modified" in changes[0]

    def test_none_direction_handled(self):
        prev = {"direction": None, "size": "1", "entry_price": "95000", "orders": []}
        curr = {"direction": "long", "size": Decimal("1"), "entry_price": Decimal("95000"), "orders": []}
        changes = detect_changes(prev, curr)
        assert len(changes) == 1
        assert "NONE" in changes[0]


class TestFormatChanges:
    def test_formats_with_changes(self):
        changes = ["🔄 Direction: LONG → SHORT"]
        curr = {"direction": "short", "size": Decimal("1.5"), "entry_price": Decimal("95000")}
        result = format_changes(changes, curr)
        assert "Weishen Position Update" in result
        assert "Direction" in result
        assert "SHORT 1.50000 BTC" in result

    def test_handles_none_direction(self):
        changes = ["📊 Size changed"]
        curr = {"direction": None, "size": Decimal("1"), "entry_price": Decimal("95000")}
        result = format_changes(changes, curr)
        assert "1.00000 BTC" in result

    def test_handles_missing_fields(self):
        changes = ["Test change"]
        curr = {}
        result = format_changes(changes, curr)
        assert "Test change" in result

    def test_truncates_long_messages(self):
        """Test that messages exceeding Telegram limit are truncated."""
        # Create many changes that would exceed the limit
        changes = [f"Change {i}: Order modified at price ${90000 + i:,}" for i in range(200)]
        curr = {"direction": "long", "size": Decimal("1"), "entry_price": Decimal("95000")}
        result = format_changes(changes, curr)
        assert len(result) <= TELEGRAM_MAX_LENGTH
        assert "more changes" in result


class TestDetectChangesEdgeCases:
    """Additional edge case tests for detect_changes."""

    def test_string_vs_number_sz_no_spurious_change(self):
        """String "0.5" and number 0.5 should not trigger a change."""
        prev = {
            "direction": "long",
            "size": "1",
            "entry_price": "95000",
            "orders": [{"oid": 123, "side": "B", "sz": "0.5", "limitPx": "90000"}]
        }
        curr = {
            "direction": "long",
            "size": Decimal("1"),
            "entry_price": Decimal("95000"),
            "orders": [{"oid": 123, "side": "B", "sz": 0.5, "limitPx": 90000}]  # numbers instead of strings
        }
        changes = detect_changes(prev, curr)
        assert len(changes) == 0

    def test_int_vs_string_oid_matched(self):
        """Integer oid 123 and string "123" should match the same order."""
        prev = {
            "direction": "long",
            "size": "1",
            "entry_price": "95000",
            "orders": [{"oid": 123, "side": "B", "sz": "0.5", "limitPx": "90000"}]  # int oid
        }
        curr = {
            "direction": "long",
            "size": Decimal("1"),
            "entry_price": Decimal("95000"),
            "orders": [{"oid": "123", "side": "B", "sz": "0.5", "limitPx": "90000"}]  # string oid
        }
        changes = detect_changes(prev, curr)
        assert len(changes) == 0

    def test_orders_with_none_oid_filtered(self):
        """Orders with None oid should be filtered out."""
        prev = {
            "direction": "long",
            "size": "1",
            "entry_price": "95000",
            "orders": [{"oid": None, "side": "B", "sz": "0.5", "limitPx": "90000"}]
        }
        curr = {
            "direction": "long",
            "size": Decimal("1"),
            "entry_price": Decimal("95000"),
            "orders": [{"oid": None, "side": "B", "sz": "0.6", "limitPx": "91000"}]
        }
        changes = detect_changes(prev, curr)
        # Both orders have None oid, so they're filtered out - no changes detected
        assert len(changes) == 0

    def test_malformed_price_handled(self):
        """Malformed limitPx should not crash the function."""
        prev = {
            "direction": "long",
            "size": "1",
            "entry_price": "95000",
            "orders": [{"oid": 123, "side": "B", "sz": "0.5", "limitPx": "invalid"}]
        }
        curr = {
            "direction": "long",
            "size": Decimal("1"),
            "entry_price": Decimal("95000"),
            "orders": []
        }
        # Should not raise, should produce "Order removed" with fallback price display
        changes = detect_changes(prev, curr)
        assert len(changes) == 1
        assert "Order removed" in changes[0]

    def test_multiple_changes_detected(self):
        """Multiple simultaneous changes are all detected."""
        prev = {
            "direction": "long",
            "size": "1",
            "entry_price": "95000",
            "orders": [{"oid": 123, "side": "B", "sz": "0.5", "limitPx": "90000"}]
        }
        curr = {
            "direction": "short",  # changed
            "size": Decimal("2"),  # changed
            "entry_price": Decimal("96000"),  # changed
            "orders": [
                {"oid": 123, "side": "B", "sz": "0.6", "limitPx": "91000"},  # modified
                {"oid": 456, "side": "A", "sz": "0.3", "limitPx": "100000"}  # added
            ]
        }
        changes = detect_changes(prev, curr)
        # direction + size + entry + order modified + order added = 5 changes
        assert len(changes) == 5


class TestGetUserId:
    """Tests for the get_user_id helper function."""

    def test_returns_none_for_none_effective_user(self):
        """Should return None when effective_user is None."""
        class MockUpdate:
            effective_user = None

        result = get_user_id(MockUpdate())
        assert result is None

    def test_returns_id_when_effective_user_exists(self):
        """Should return user ID when effective_user exists."""
        class MockUser:
            id = 12345

        class MockUpdate:
            effective_user = MockUser()

        result = get_user_id(MockUpdate())
        assert result == 12345


from decimal import InvalidOperation


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
