"""Tests for core.engine"""

import pytest
from decimal import Decimal
from unittest.mock import patch

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine import (
    get_address,
    get_btc_position,
    get_btc_orders,
    determine_position_direction,
    get_position_size,
    scale_orders,
    compute_long_summary,
    compute_short_summary,
)


class TestGetAddress:
    def test_default_address(self):
        """Should return default address when env var not set."""
        with patch.dict(os.environ, {}, clear=True):
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
        account_state = {
            "assetPositions": [
                {"position": {"coin": "ETH", "szi": "1.5"}},
            ]
        }
        assert get_btc_position(account_state) is None

    def test_empty_positions(self):
        assert get_btc_position({"assetPositions": []}) is None


class TestGetBtcOrders:
    def test_filters_btc_orders(self):
        orders = [
            {"coin": "BTC", "sz": "0.1", "limitPx": "50000"},
            {"coin": "ETH", "sz": "1.0", "limitPx": "3000"},
            {"coin": "BTC", "sz": "0.2", "limitPx": "51000"},
        ]
        btc_orders = get_btc_orders(orders)
        assert len(btc_orders) == 2
        assert all(o["coin"] == "BTC" for o in btc_orders)

    def test_no_btc_orders(self):
        assert get_btc_orders([{"coin": "ETH", "sz": "1.0"}]) == []

    def test_empty_orders(self):
        assert get_btc_orders([]) == []


class TestDeterminePositionDirection:
    def test_long_position(self):
        assert determine_position_direction({"szi": "0.5"}) == "long"

    def test_short_position(self):
        assert determine_position_direction({"szi": "-0.5"}) == "short"

    def test_zero_position(self):
        assert determine_position_direction({"szi": "0"}) is None

    def test_missing_size(self):
        assert determine_position_direction({}) is None


class TestGetPositionSize:
    def test_positive_size(self):
        assert get_position_size({"szi": "0.5"}) == Decimal("0.5")

    def test_negative_size(self):
        assert get_position_size({"szi": "-0.5"}) == Decimal("0.5")

    def test_zero_size(self):
        assert get_position_size({"szi": "0"}) == Decimal("0")


class TestScaleOrders:
    def test_scale_orders_2x(self):
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
        orders = [{"sz": "1.0", "limitPx": "50000", "side": "B"}]
        ratio = Decimal("0.5")
        scaled = scale_orders(orders, ratio)
        assert scaled[0]["scaled_size"] == Decimal("0.500")

    def test_scale_orders_rounds_down(self):
        """Should round down to 3 decimal places (broker limitation)."""
        orders = [{"sz": "0.333333", "limitPx": "50000", "side": "B"}]
        ratio = Decimal("1")
        scaled = scale_orders(orders, ratio)
        assert scaled[0]["scaled_size"] == Decimal("0.333")

    def test_scale_orders_calculates_notional(self):
        orders = [{"sz": "0.1", "limitPx": "50000", "side": "B"}]
        ratio = Decimal("1")
        scaled = scale_orders(orders, ratio)
        assert scaled[0]["notional"] == Decimal("5000.000")

    def test_empty_orders(self):
        assert scale_orders([], Decimal("2")) == []


class TestDirectionValidation:
    def test_long_matches_long(self):
        assert determine_position_direction({"szi": "0.5"}) == "long"

    def test_short_matches_short(self):
        assert determine_position_direction({"szi": "-0.5"}) == "short"

    def test_long_does_not_match_short(self):
        assert determine_position_direction({"szi": "-0.5"}) != "long"

    def test_short_does_not_match_long(self):
        assert determine_position_direction({"szi": "0.5"}) != "short"


class TestComputeLongSummary:
    def test_long_adding_buys(self):
        """Long position + buy orders = larger long."""
        scaled_orders = [
            {"side": "B", "scaled_size": Decimal("0.1"), "price": Decimal("80000")},
            {"side": "B", "scaled_size": Decimal("0.2"), "price": Decimal("75000")},
        ]
        result = compute_long_summary(scaled_orders, Decimal("0.05"), Decimal("90000"), Decimal("1"))
        assert result is not None
        assert result["net_position"] == Decimal("0.35")
        assert result["avg_entry"] is not None

    def test_short_with_buys_flips_long(self):
        """Short position + buy orders that exceed short = net long."""
        scaled_orders = [
            {"side": "B", "scaled_size": Decimal("0.5"), "price": Decimal("80000")},
        ]
        result = compute_long_summary(scaled_orders, Decimal("-0.1"), Decimal("90000"), Decimal("1"))
        assert result is not None
        assert result["net_position"] == Decimal("0.4")
        assert result["avg_entry"] is not None

    def test_no_buy_orders(self):
        """Should return None if no buy orders."""
        scaled_orders = [{"side": "A", "scaled_size": Decimal("0.1"), "price": Decimal("95000")}]
        assert compute_long_summary(scaled_orders, Decimal("0.05"), Decimal("90000"), Decimal("1")) is None


class TestComputeShortSummary:
    def test_long_with_sells_reduces(self):
        """Long position + sell orders that are less = still net long."""
        scaled_orders = [
            {"side": "A", "scaled_size": Decimal("0.02"), "price": Decimal("95000")},
        ]
        result = compute_short_summary(scaled_orders, Decimal("0.05"), Decimal("90000"), Decimal("1"))
        assert result is not None
        assert result["net_position"] == Decimal("0.03")
        assert result["avg_entry"] is None  # still long, no short avg entry

    def test_long_with_sells_flips_short(self):
        """Long position + sell orders that exceed long = net short."""
        scaled_orders = [
            {"side": "A", "scaled_size": Decimal("0.5"), "price": Decimal("95000")},
        ]
        result = compute_short_summary(scaled_orders, Decimal("0.05"), Decimal("90000"), Decimal("1"))
        assert result is not None
        assert result["net_position"] == Decimal("-0.45")
        assert result["avg_entry"] is not None

    def test_short_adding_sells(self):
        """Short position + sell orders = larger short."""
        scaled_orders = [
            {"side": "A", "scaled_size": Decimal("0.1"), "price": Decimal("95000")},
        ]
        result = compute_short_summary(scaled_orders, Decimal("-0.05"), Decimal("90000"), Decimal("1"))
        assert result is not None
        assert result["net_position"] == Decimal("-0.15")
        assert result["avg_entry"] is not None

    def test_no_sell_orders(self):
        """Should return None if no sell orders."""
        scaled_orders = [{"side": "B", "scaled_size": Decimal("0.1"), "price": Decimal("80000")}]
        assert compute_short_summary(scaled_orders, Decimal("0.05"), Decimal("90000"), Decimal("1")) is None
