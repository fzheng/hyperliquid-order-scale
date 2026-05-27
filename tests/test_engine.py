"""Tests for core.engine"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch
from datetime import datetime

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
    fetch_btc_price,
    fetch_account_state,
    fetch_open_orders,
    fetch_user_fills,
    get_relative_time,
    get_last_activity_time,
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
