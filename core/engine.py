"""
Core business logic for Hyperliquid BTC Order Scaling.

Shared by both CLI and Telegram bot interfaces.
"""

import os
import requests
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

# Configuration
DEFAULT_ADDRESS = "0xdae4df7207feb3b350e4284c8efe5f7dac37f637"
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz/info"


def get_address() -> str:
    """Get the Hyperliquid address from environment variable or use default."""
    return os.environ.get("HYPERLIQUID_ADDRESS", DEFAULT_ADDRESS)


def fetch_btc_price() -> dict:
    """Fetch BTC price from Hyperliquid.

    Returns dict with keys: price, change_24h, change_pct_24h
    """
    payload = {"type": "metaAndAssetCtxs"}
    response = requests.post(HYPERLIQUID_API_URL, json=payload, timeout=10)
    response.raise_for_status()
    data = response.json()

    # Find BTC by symbol in metadata, then get matching context
    meta = data[0]["universe"]
    contexts = data[1]

    btc_index = None
    for i, asset in enumerate(meta):
        if asset.get("name") == "BTC":
            btc_index = i
            break

    if btc_index is None:
        raise ValueError("BTC not found in Hyperliquid asset list")

    btc_data = contexts[btc_index]
    price = Decimal(btc_data["midPx"])
    price_24h_ago = Decimal(btc_data["prevDayPx"])
    change_24h = price - price_24h_ago
    change_pct = (change_24h / price_24h_ago * 100) if price_24h_ago else Decimal("0")

    return {
        "price": price,
        "change_24h": change_24h,
        "change_pct_24h": change_pct,
    }


def fetch_account_state(address: str) -> dict:
    """Fetch the account state from Hyperliquid API."""
    payload = {
        "type": "clearinghouseState",
        "user": address
    }
    response = requests.post(HYPERLIQUID_API_URL, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_open_orders(address: str) -> list:
    """Fetch open orders from Hyperliquid API."""
    payload = {
        "type": "openOrders",
        "user": address
    }
    response = requests.post(HYPERLIQUID_API_URL, json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_user_fills(address: str) -> list:
    """Fetch recent fills from Hyperliquid API."""
    payload = {
        "type": "userFills",
        "user": address
    }
    try:
        response = requests.post(HYPERLIQUID_API_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return []


def get_relative_time(timestamp_ms: int) -> str:
    """Convert timestamp to relative time string."""
    now = datetime.now()
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    diff = now - dt

    seconds = diff.total_seconds()

    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    elif seconds < 2592000:
        weeks = int(seconds / 604800)
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    else:
        months = int(seconds / 2592000)
        return f"{months} month{'s' if months != 1 else ''} ago"


def get_last_activity_time(orders: list, fills: list) -> str:
    """Get the most recent activity time from orders or fills."""
    timestamps = []

    for order in orders:
        if "timestamp" in order:
            try:
                timestamps.append(int(order["timestamp"]))
            except (ValueError, TypeError):
                pass

    for fill in fills:
        if "time" in fill:
            try:
                timestamps.append(int(fill["time"]))
            except (ValueError, TypeError):
                pass

    if not timestamps:
        return "Unknown"

    latest = max(timestamps)
    return get_relative_time(latest)


def get_btc_position(account_state: dict) -> dict | None:
    """Extract BTC position from account state."""
    asset_positions = account_state.get("assetPositions", [])

    for pos in asset_positions:
        position = pos.get("position", {})
        if position.get("coin") == "BTC":
            return position

    return None


def get_btc_orders(orders: list) -> list:
    """Filter orders for BTC only."""
    return [order for order in orders if order.get("coin") == "BTC"]


def determine_position_direction(position: dict) -> str | None:
    """Determine if position is long or short based on size."""
    size_str = position.get("szi", "0")
    size = Decimal(size_str)

    if size > 0:
        return "long"
    elif size < 0:
        return "short"
    else:
        return None


def get_position_size(position: dict) -> Decimal:
    """Get the absolute BTC position size."""
    return abs(Decimal(position.get("szi", "0")))


def scale_orders(orders: list, ratio: Decimal) -> list:
    """Scale order sizes by the given ratio."""
    scaled = []

    for order in orders:
        original_size = abs(Decimal(order.get("sz", "0")))
        price = Decimal(order.get("limitPx", "0"))
        side = order.get("side", "")

        scaled_size = (original_size * ratio).quantize(Decimal("0.001"), rounding=ROUND_DOWN)

        scaled.append({
            "side": side,
            "price": price,
            "original_size": original_size,
            "scaled_size": scaled_size,
            "notional": scaled_size * price
        })

    return scaled


def compute_long_summary(scaled_orders: list, current_position_size: Decimal, current_entry_price: Decimal, ratio: Decimal) -> dict | None:
    """Compute long position summary if all buy orders are filled.

    Returns dict with keys: current_size, buy_total, net_position, avg_entry (or None), capital_required.
    Returns None if no buy orders.
    """
    buy_orders = [o for o in scaled_orders if o["side"].upper() == "B"]

    if not buy_orders:
        return None

    total_buy_size = sum(o["scaled_size"] for o in buy_orders)
    total_buy_cost = sum(o["scaled_size"] * o["price"] for o in buy_orders)

    scaled_current_size = current_position_size * ratio
    net_position = scaled_current_size + total_buy_size

    avg_entry = None
    if net_position > 0:
        if scaled_current_size > 0:
            current_cost = scaled_current_size * current_entry_price
            avg_entry = (current_cost + total_buy_cost) / net_position
        else:
            avg_entry = total_buy_cost / total_buy_size if total_buy_size > 0 else Decimal("0")

    return {
        "current_size": scaled_current_size,
        "order_total": total_buy_size,
        "net_position": net_position,
        "avg_entry": avg_entry,
        "capital_required": total_buy_cost,
    }


def compute_short_summary(scaled_orders: list, current_position_size: Decimal, current_entry_price: Decimal, ratio: Decimal) -> dict | None:
    """Compute short position summary if all sell orders are filled.

    Returns dict with keys: current_size, sell_total, net_position, avg_entry (or None), capital_required.
    Returns None if no sell orders.
    """
    sell_orders = [o for o in scaled_orders if o["side"].upper() == "A"]

    if not sell_orders:
        return None

    total_sell_size = sum(o["scaled_size"] for o in sell_orders)
    total_sell_value = sum(o["scaled_size"] * o["price"] for o in sell_orders)

    scaled_current_size = current_position_size * ratio
    net_position = scaled_current_size - total_sell_size

    avg_entry = None
    if net_position < 0:
        if scaled_current_size < 0:
            current_value = abs(scaled_current_size) * current_entry_price
            avg_entry = (current_value + total_sell_value) / abs(net_position)
        else:
            avg_entry = total_sell_value / total_sell_size if total_sell_size > 0 else Decimal("0")

    return {
        "current_size": scaled_current_size,
        "order_total": total_sell_size,
        "net_position": net_position,
        "avg_entry": avg_entry,
        "capital_required": total_sell_value,
    }


def get_weishen_position() -> dict:
    """Get weishen's current BTC position and orders.

    Returns dict with keys:
        - error: str or None
        - direction, size, entry_price, current_price, pnl
        - last_activity, orders (raw BTC orders)
    """
    address = get_address()

    try:
        account_state = fetch_account_state(address)
        orders = fetch_open_orders(address)
        fills = fetch_user_fills(address)
        price_data = fetch_btc_price()
    except Exception as e:
        return {"error": f"Failed to fetch data: {e}"}

    btc_position = get_btc_position(account_state)
    if not btc_position:
        return {"error": "No BTC position found."}

    direction = determine_position_direction(btc_position)
    if not direction:
        return {"error": "No active BTC position."}

    size = Decimal(btc_position.get("szi", "0"))
    entry_price = Decimal(btc_position.get("entryPx", "0"))
    current_price = price_data["price"]

    # P&L calculation: (current - entry) * size for long, (entry - current) * |size| for short
    if size > 0:  # long
        pnl = (current_price - entry_price) * size
    else:  # short
        pnl = (entry_price - current_price) * abs(size)

    btc_orders = get_btc_orders(orders)
    last_activity = get_last_activity_time(orders, fills)

    return {
        "error": None,
        "direction": direction,
        "size": abs(size),
        "entry_price": entry_price,
        "current_price": current_price,
        "pnl": pnl,
        "last_activity": last_activity,
        "orders": btc_orders,
    }


def process_request(user_direction: str, user_btc_size: Decimal) -> dict:
    """Main processing logic shared by CLI and bot.

    Args:
        user_direction: 'long' or 'short'
        user_btc_size: Absolute BTC position size (positive Decimal)

    Returns dict with keys:
        - error: str or None
        - address, last_activity, account_direction, account_btc_size, entry_price
        - ratio, num_orders, scaled_orders
        - long_summary, short_summary

    Raises requests.exceptions.RequestException on API failure.
    """
    address = get_address()

    account_state = fetch_account_state(address)
    orders = fetch_open_orders(address)
    fills = fetch_user_fills(address)

    last_activity = get_last_activity_time(orders, fills)

    btc_position = get_btc_position(account_state)
    if not btc_position:
        return {"error": "No BTC position found for this account."}

    account_direction = determine_position_direction(btc_position)
    if not account_direction:
        return {"error": "Account has no active BTC position (size is 0)."}

    if account_direction != user_direction:
        return {"error": f"Direction mismatch! You selected {user_direction.upper()} but account is {account_direction.upper()}."}

    btc_orders = get_btc_orders(orders)
    if not btc_orders:
        return {"error": "No pending BTC orders found for this account."}

    account_btc_size = get_position_size(btc_position)
    if account_btc_size == 0:
        return {"error": "Account BTC position size is 0, cannot calculate ratio."}

    ratio = user_btc_size / account_btc_size
    entry_price = Decimal(btc_position.get("entryPx", "0"))
    current_size = Decimal(btc_position.get("szi", "0"))

    scaled = scale_orders(btc_orders, ratio)

    long_summary = compute_long_summary(scaled, current_size, entry_price, ratio)
    short_summary = compute_short_summary(scaled, current_size, entry_price, ratio)

    return {
        "error": None,
        "address": address,
        "last_activity": last_activity,
        "account_direction": account_direction,
        "account_btc_size": account_btc_size,
        "entry_price": entry_price,
        "user_direction": user_direction,
        "user_btc_size": user_btc_size,
        "ratio": ratio,
        "num_orders": len(btc_orders),
        "scaled_orders": scaled,
        "long_summary": long_summary,
        "short_summary": short_summary,
    }
