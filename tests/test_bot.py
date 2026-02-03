"""Tests for bot input parsing logic."""

import pytest
from decimal import Decimal


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
