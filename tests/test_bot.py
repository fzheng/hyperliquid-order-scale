"""Tests for bot input parsing and change detection logic."""

import pytest
from decimal import Decimal

from bot.main import detect_changes, format_changes


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
