#!/usr/bin/env python3
"""Telegram bot interface for Hyperliquid BTC Order Scaling Tool."""

import os
import logging
from dotenv import load_dotenv

load_dotenv()
from decimal import Decimal, InvalidOperation

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from core.engine import process_request

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def format_result(result: dict) -> str:
    """Format the processing result as a monospace Telegram message."""
    lines = []

    lines.append(f"Last activity: {result['last_activity']}")
    lines.append(f"Account: {result['account_direction'].upper()} {result['account_btc_size']} BTC @ ${result['entry_price']:,.2f}")
    lines.append(f"You:     {result['user_direction'].upper()} {result['user_btc_size']} BTC (ratio: {result['ratio']:.4f})")
    lines.append(f"Pending orders: {result['num_orders']}")

    # Scaled orders table
    sorted_orders = sorted(result["scaled_orders"], key=lambda x: x["price"], reverse=True)

    lines.append("")
    lines.append(f"{'Side':<5}{'Price':>11}{'Size':>8}{'Notional':>11}")
    lines.append("-" * 35)

    for order in sorted_orders:
        side = "BUY" if order["side"].upper() == "B" else "SELL"
        lines.append(f"{side:<5}${order['price']:>9,.0f}{order['scaled_size']:>8.3f}${order['notional']:>9,.0f}")

    # Summaries
    for label, summary, order_label in [
        ("LONG SUMMARY (all buys filled)", result["long_summary"], "Buy"),
        ("SHORT SUMMARY (all sells filled)", result["short_summary"], "Sell"),
    ]:
        if not summary:
            continue

        lines.append("")
        lines.append(f"--- {label} ---")
        lines.append(f"Current:  {summary['current_size']:>10.3f} BTC")
        lines.append(f"{order_label} total: {summary['order_total']:>10.3f} BTC")
        lines.append(f"Net:      {summary['net_position']:>10.3f} BTC")

        if summary["avg_entry"] is not None:
            lines.append(f"Avg entry: ${summary['avg_entry']:>12,.2f}")

        lines.append(f"Capital:   ${summary['capital_required']:>12,.2f}")

    return "<pre>" + "\n".join(lines) + "</pre>"


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    msg = (
        "<b>Hyperliquid BTC Order Scaler</b>\n\n"
        "Send a number to scale orders:\n"
        "  <code>0.05</code>  → Long 0.05 BTC\n"
        "  <code>-0.05</code> → Short 0.05 BTC\n\n"
        "The bot will fetch the tracked account's BTC position "
        "and pending orders, then scale them to your size."
    )
    await update.message.reply_text(msg, parse_mode="HTML")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user message with BTC size input."""
    text = update.message.text.strip()

    try:
        value = Decimal(text)
    except InvalidOperation:
        await update.message.reply_text("Send a number. Positive = long, negative = short.")
        return

    if value == 0:
        await update.message.reply_text("Size cannot be zero.")
        return

    if value > 0:
        direction = "long"
        btc_size = value
    else:
        direction = "short"
        btc_size = abs(value)

    try:
        result = process_request(direction, btc_size)
    except Exception as e:
        logger.error(f"API error: {e}")
        await update.message.reply_text(f"Error fetching data: {e}")
        return

    if result["error"]:
        await update.message.reply_text(f"Error: {result['error']}")
        return

    response = format_result(result)
    await update.message.reply_text(response, parse_mode="HTML")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is not set.")
        print("Set it with: set TELEGRAM_BOT_TOKEN=your_token_here")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
