#!/usr/bin/env python3
"""
Hyperliquid BTC Order Scaling Tool

This tool retrieves BTC position and pending orders from a Hyperliquid account,
then scales the orders proportionally based on user's account size.
"""

import os
import sys
import requests
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

# Configuration
DEFAULT_ADDRESS = "0xdae4df7207feb3b350e4284c8efe5f7dac37f637"
HYPERLIQUID_API_URL = "https://api.hyperliquid.xyz/info"


def get_address() -> str:
    """Get the Hyperliquid address from environment variable or use default."""
    return os.environ.get("HYPERLIQUID_ADDRESS", DEFAULT_ADDRESS)


def get_user_position_choice() -> str:
    """Prompt user to select their BTC position direction."""
    print("\nSelect your BTC position:")
    print("  0) Long")
    print("  1) Short")

    while True:
        choice = input("\nEnter your choice (0/1): ").strip()
        if choice == '0':
            return 'long'
        elif choice == '1':
            return 'short'
        else:
            print("Invalid choice. Please enter '0' for long or '1' for short.")


def get_user_btc_size() -> Decimal:
    """Prompt user to input their BTC position size."""
    while True:
        try:
            size_input = input("\nEnter your BTC position size: ").strip()
            size = Decimal(size_input)
            if size <= 0:
                print("BTC size must be a positive number.")
                continue
            return size
        except Exception:
            print("Invalid input. Please enter a valid number.")


def fetch_account_state(address: str) -> dict:
    """Fetch the account state from Hyperliquid API."""
    payload = {
        "type": "clearinghouseState",
        "user": address
    }

    try:
        response = requests.post(HYPERLIQUID_API_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching account state: {e}")
        sys.exit(1)


def fetch_open_orders(address: str) -> list:
    """Fetch open orders from Hyperliquid API."""
    payload = {
        "type": "openOrders",
        "user": address
    }

    try:
        response = requests.post(HYPERLIQUID_API_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching open orders: {e}")
        sys.exit(1)


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
    except requests.exceptions.RequestException as e:
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

    # Get timestamps from orders
    for order in orders:
        if "timestamp" in order:
            timestamps.append(order["timestamp"])

    # Get timestamps from fills
    for fill in fills:
        if "time" in fill:
            timestamps.append(fill["time"])

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


class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"


def print_scaled_orders(scaled_orders: list):
    """Print scaled orders sorted by price descending."""
    sorted_orders = sorted(scaled_orders, key=lambda x: x["price"], reverse=True)

    print("\n" + "-" * 70)
    print(f"{'Side':<6} {'Price':>12} {'Scaled Size':>12} {'Original Size':>15} {'Notional':>12}")
    print("-" * 70)

    for i, order in enumerate(sorted_orders):
        side_display = "BUY" if order["side"].upper() == "B" else "SELL"
        side_color = Colors.GREEN if order["side"].upper() == "B" else Colors.RED
        row_color = Colors.CYAN if i % 2 == 1 else Colors.YELLOW

        print(f"{side_color}{side_display:<6}{Colors.RESET}{row_color} ${order['price']:>11,.2f} {order['scaled_size']:>12.3f} {order['original_size']:>15.5f} ${order['notional']:>10,.2f}{Colors.RESET}")


def print_long_summary(scaled_orders: list, current_position_size: Decimal, current_entry_price: Decimal, ratio: Decimal):
    """Print summary for long position if all buy orders are filled.

    If current position is short, buy orders first close the short before opening long.
    """
    buy_orders = [o for o in scaled_orders if o["side"].upper() == "B"]

    if not buy_orders:
        print("\nNo pending buy orders to summarize.")
        return

    total_buy_size = sum(o["scaled_size"] for o in buy_orders)
    total_buy_cost = sum(o["scaled_size"] * o["price"] for o in buy_orders)

    # Current scaled position (positive = long, negative = short)
    scaled_current_size = current_position_size * ratio

    # Net position after all buy orders fill
    # If long: adds to position
    # If short: first closes short, then opens long
    net_position = scaled_current_size + total_buy_size

    print("\n" + "=" * 70)
    print("LONG SUMMARY (if all buy orders are filled)")
    print("=" * 70)
    print(f"Current Position:        {scaled_current_size:>12.3f} BTC")
    print(f"Buy Orders Total:        {total_buy_size:>12.3f} BTC")
    print(f"Net Position:            {net_position:>12.3f} BTC")

    if net_position > 0:
        # Calculate average entry for the long position
        if scaled_current_size > 0:
            # Was long, adding more long
            current_cost = scaled_current_size * current_entry_price
            avg_entry = (current_cost + total_buy_cost) / net_position
        else:
            # Was short or flat, now long from buys only
            # Only the portion that creates the long matters
            avg_entry = total_buy_cost / total_buy_size if total_buy_size > 0 else Decimal("0")
        print(f"Average Entry Price:     ${avg_entry:>14,.2f}")

    print(f"Capital Required:        ${total_buy_cost:>14,.2f}")


def print_short_summary(scaled_orders: list, current_position_size: Decimal, current_entry_price: Decimal, ratio: Decimal):
    """Print summary for short position if all sell orders are filled.

    If current position is long, sell orders first close the long before opening short.
    """
    sell_orders = [o for o in scaled_orders if o["side"].upper() == "A"]

    if not sell_orders:
        print("\nNo pending sell orders to summarize.")
        return

    total_sell_size = sum(o["scaled_size"] for o in sell_orders)
    total_sell_value = sum(o["scaled_size"] * o["price"] for o in sell_orders)

    # Current scaled position (positive = long, negative = short)
    scaled_current_size = current_position_size * ratio

    # Net position after all sell orders fill
    # If short: adds to short position
    # If long: first closes long, then opens short
    net_position = scaled_current_size - total_sell_size

    print("\n" + "=" * 70)
    print("SHORT SUMMARY (if all sell orders are filled)")
    print("=" * 70)
    print(f"Current Position:        {scaled_current_size:>12.3f} BTC")
    print(f"Sell Orders Total:       {total_sell_size:>12.3f} BTC")
    print(f"Net Position:            {net_position:>12.3f} BTC")

    if net_position < 0:
        # Calculate average entry for the short position
        if scaled_current_size < 0:
            # Was short, adding more short
            current_value = abs(scaled_current_size) * current_entry_price
            avg_entry = (current_value + total_sell_value) / abs(net_position)
        else:
            # Was long or flat, now short from sells only
            # Only the portion that creates the short matters
            avg_entry = total_sell_value / total_sell_size if total_sell_size > 0 else Decimal("0")
        print(f"Average Entry Price:     ${avg_entry:>14,.2f}")

    print(f"Capital Required:        ${total_sell_value:>14,.2f}")


def main():
    print("=" * 70)
    print("HYPERLIQUID BTC ORDER SCALING TOOL")
    print("=" * 70)

    # Get configuration
    address = get_address()
    print(f"\nTracking address: {address}")

    # Get user inputs
    user_direction = get_user_position_choice()
    user_btc_size = get_user_btc_size()

    print(f"\nYour selection: {user_direction.upper()} position")
    print(f"Your BTC size: {user_btc_size} BTC")

    # Fetch data from Hyperliquid
    print("\nFetching account data from Hyperliquid...")
    account_state = fetch_account_state(address)
    orders = fetch_open_orders(address)
    fills = fetch_user_fills(address)

    # Show last activity time
    last_activity = get_last_activity_time(orders, fills)
    print(f"Last account activity: {last_activity}")

    # Get BTC position
    btc_position = get_btc_position(account_state)

    if not btc_position:
        print("\nError: No BTC position found for this account.")
        sys.exit(1)

    # Determine account direction
    account_direction = determine_position_direction(btc_position)

    if not account_direction:
        print("\nError: Account has no active BTC position (size is 0).")
        sys.exit(1)

    # Validate direction
    if account_direction != user_direction:
        print(f"\n{'=' * 70}")
        print("ERROR: Direction mismatch!")
        print(f"{'=' * 70}")
        print(f"Your selected direction: {user_direction.upper()}")
        print(f"Account position direction: {account_direction.upper()}")
        print("\nCannot scale orders when directions do not match.")
        sys.exit(1)

    # Get BTC orders
    btc_orders = get_btc_orders(orders)

    if not btc_orders:
        print("\nNo pending BTC orders found for this account.")
        sys.exit(0)

    # Calculate scaling ratio based on BTC position size
    account_btc_size = get_position_size(btc_position)

    if account_btc_size == 0:
        print("\nError: Account BTC position size is 0, cannot calculate ratio.")
        sys.exit(1)

    ratio = user_btc_size / account_btc_size

    print(f"\nAccount: {account_direction.upper()} {account_btc_size} BTC @ ${Decimal(btc_position.get('entryPx', '0')):,.2f}")
    print(f"You:     {user_direction.upper()} {user_btc_size} BTC (scaling ratio: {ratio:.4f})")
    print(f"Pending orders: {len(btc_orders)}")

    # Scale orders
    scaled_orders = scale_orders(btc_orders, ratio)

    # Print scaled orders
    print_scaled_orders(scaled_orders)

    # Print both summaries
    current_size = Decimal(btc_position.get("szi", "0"))
    current_entry = Decimal(btc_position.get("entryPx", "0"))

    print_long_summary(scaled_orders, current_size, current_entry, ratio)
    print_short_summary(scaled_orders, current_size, current_entry, ratio)

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
