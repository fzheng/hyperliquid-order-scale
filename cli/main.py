#!/usr/bin/env python3
"""CLI interface for Hyperliquid BTC Order Scaling Tool."""

import sys
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

from core.engine import process_request


class Colors:
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"


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


def print_summary(title: str, summary: dict, order_label: str):
    """Print a position summary."""
    if not summary:
        return

    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    print(f"Current Position:        {summary['current_size']:>12.3f} BTC")
    print(f"{order_label} Orders Total:  {summary['order_total']:>12.3f} BTC")
    print(f"Net Position:            {summary['net_position']:>12.3f} BTC")

    if summary["avg_entry"] is not None:
        print(f"Average Entry Price:     ${summary['avg_entry']:>14,.2f}")

    print(f"Capital Required:        ${summary['capital_required']:>14,.2f}")


def main():
    print("=" * 70)
    print("HYPERLIQUID BTC ORDER SCALING TOOL")
    print("=" * 70)

    user_direction = get_user_position_choice()
    user_btc_size = get_user_btc_size()

    print(f"\nYour selection: {user_direction.upper()} position")
    print(f"Your BTC size: {user_btc_size} BTC")

    print("\nFetching account data from Hyperliquid...")

    try:
        result = process_request(user_direction, user_btc_size)
    except Exception as e:
        print(f"Error fetching data: {e}")
        sys.exit(1)

    if result["error"]:
        print(f"\nError: {result['error']}")
        sys.exit(1)

    print(f"Last account activity: {result['last_activity']}")
    print(f"\nAccount: {result['account_direction'].upper()} {result['account_btc_size']} BTC @ ${result['entry_price']:,.2f}")
    print(f"You:     {result['user_direction'].upper()} {result['user_btc_size']} BTC (scaling ratio: {result['ratio']:.4f})")
    print(f"Pending orders: {result['num_orders']}")

    print_scaled_orders(result["scaled_orders"])
    print_summary("LONG SUMMARY (if all buy orders are filled)", result["long_summary"], "Buy")
    print_summary("SHORT SUMMARY (if all sell orders are filled)", result["short_summary"], "Sell")

    print("\n" + "=" * 70)
    print("Done!")
    print("=" * 70)


if __name__ == "__main__":
    main()
