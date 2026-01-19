"""Tests for scale_orders.py"""

import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scale_orders import (
    get_address,
    get_btc_position,
    get_btc_orders,
    determine_position_direction,
    get_position_size,
    scale_orders,
)


class TestGetAddress:
    def test_default_address(self):
        """Should return default address when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove HYPERLIQUID_ADDRESS if it exists
            os.environ.pop("HYPERLIQUID_ADDRESS", None)
            address = get_address()
            assert address == "0xdae4df7207feb3b350e4284c8efe5f7dac37f637"

    def test_custom_address_from_env(self):
        """Should return address from environment variable."""
        custom_addr = "0x1234567890abcdef1234567890abcdef12345678"
        with patch.dict(os.environ, {"HYPERLIQUID_ADDRESS": custom_addr}):
            address = get_address()
            assert address == custom_addr


class TestGetBtcPosition:
    def test_finds_btc_position(self):
        """Should find BTC position in account state."""
        account_state = {
            "assetPositions": [
                {"position": {"coin": "ETH", "szi": "1.5"}},
                {"position": {"coin": "BTC", "szi": "0.5", "entryPx": "50000"}},
            ]
        }
        position = get_btc_position(account_state)
        assert position is not None
        assert position["coin"] == "BTC"
        assert position["szi"] == "0.5"

    def test_no_btc_position(self):
        """Should return None when no BTC position exists."""
        account_state = {
            "assetPositions": [
                {"position": {"coin": "ETH", "szi": "1.5"}},
            ]
        }
        position = get_btc_position(account_state)
        assert position is None

    def test_empty_positions(self):
        """Should return None for empty positions."""
        account_state = {"assetPositions": []}
        position = get_btc_position(account_state)
        assert position is None


class TestGetBtcOrders:
    def test_filters_btc_orders(self):
        """Should filter only BTC orders."""
        orders = [
            {"coin": "BTC", "sz": "0.1", "limitPx": "50000"},
            {"coin": "ETH", "sz": "1.0", "limitPx": "3000"},
            {"coin": "BTC", "sz": "0.2", "limitPx": "51000"},
        ]
        btc_orders = get_btc_orders(orders)
        assert len(btc_orders) == 2
        assert all(o["coin"] == "BTC" for o in btc_orders)

    def test_no_btc_orders(self):
        """Should return empty list when no BTC orders."""
        orders = [
            {"coin": "ETH", "sz": "1.0", "limitPx": "3000"},
        ]
        btc_orders = get_btc_orders(orders)
        assert btc_orders == []

    def test_empty_orders(self):
        """Should handle empty order list."""
        btc_orders = get_btc_orders([])
        assert btc_orders == []


class TestDeterminePositionDirection:
    def test_long_position(self):
        """Positive size should be long."""
        position = {"szi": "0.5"}
        assert determine_position_direction(position) == "long"

    def test_short_position(self):
        """Negative size should be short."""
        position = {"szi": "-0.5"}
        assert determine_position_direction(position) == "short"

    def test_zero_position(self):
        """Zero size should return None."""
        position = {"szi": "0"}
        assert determine_position_direction(position) is None

    def test_missing_size(self):
        """Missing size should default to zero and return None."""
        position = {}
        assert determine_position_direction(position) is None


class TestGetPositionSize:
    def test_positive_size(self):
        """Should return absolute value of positive size."""
        position = {"szi": "0.5"}
        assert get_position_size(position) == Decimal("0.5")

    def test_negative_size(self):
        """Should return absolute value of negative size."""
        position = {"szi": "-0.5"}
        assert get_position_size(position) == Decimal("0.5")

    def test_zero_size(self):
        """Should return zero for zero size."""
        position = {"szi": "0"}
        assert get_position_size(position) == Decimal("0")


class TestScaleOrders:
    def test_scale_orders_2x(self):
        """Should scale orders by 2x ratio."""
        orders = [
            {"sz": "0.1", "limitPx": "50000", "side": "B"},
            {"sz": "0.2", "limitPx": "51000", "side": "A"},
        ]
        ratio = Decimal("2")
        scaled = scale_orders(orders, ratio)

        assert len(scaled) == 2
        assert scaled[0]["scaled_size"] == Decimal("0.200")
        assert scaled[0]["original_size"] == Decimal("0.1")
        assert scaled[0]["price"] == Decimal("50000")
        assert scaled[1]["scaled_size"] == Decimal("0.400")

    def test_scale_orders_fractional_ratio(self):
        """Should scale orders with fractional ratio."""
        orders = [
            {"sz": "1.0", "limitPx": "50000", "side": "B"},
        ]
        ratio = Decimal("0.5")
        scaled = scale_orders(orders, ratio)

        assert scaled[0]["scaled_size"] == Decimal("0.500")

    def test_scale_orders_rounds_down(self):
        """Should round down to 3 decimal places (broker limitation)."""
        orders = [
            {"sz": "0.333333", "limitPx": "50000", "side": "B"},
        ]
        ratio = Decimal("1")
        scaled = scale_orders(orders, ratio)

        # 0.333333 rounded down to 3 decimals = 0.333
        assert scaled[0]["scaled_size"] == Decimal("0.333")

    def test_scale_orders_calculates_notional(self):
        """Should calculate notional value correctly."""
        orders = [
            {"sz": "0.1", "limitPx": "50000", "side": "B"},
        ]
        ratio = Decimal("1")
        scaled = scale_orders(orders, ratio)

        # 0.1 * 50000 = 5000
        assert scaled[0]["notional"] == Decimal("5000.000")

    def test_empty_orders(self):
        """Should handle empty order list."""
        scaled = scale_orders([], Decimal("2"))
        assert scaled == []


class TestDirectionValidation:
    """Test the direction matching logic."""

    def test_long_matches_long(self):
        """Long user direction should match long account position."""
        position = {"szi": "0.5"}
        account_direction = determine_position_direction(position)
        user_direction = "long"
        assert account_direction == user_direction

    def test_short_matches_short(self):
        """Short user direction should match short account position."""
        position = {"szi": "-0.5"}
        account_direction = determine_position_direction(position)
        user_direction = "short"
        assert account_direction == user_direction

    def test_long_does_not_match_short(self):
        """Long user direction should not match short account position."""
        position = {"szi": "-0.5"}
        account_direction = determine_position_direction(position)
        user_direction = "long"
        assert account_direction != user_direction

    def test_short_does_not_match_long(self):
        """Short user direction should not match long account position."""
        position = {"szi": "0.5"}
        account_direction = determine_position_direction(position)
        user_direction = "short"
        assert account_direction != user_direction
