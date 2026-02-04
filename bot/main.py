#!/usr/bin/env python3
"""Telegram bot interface for Hyperliquid BTC Order Scaling Tool."""

import os
import logging
from dotenv import load_dotenv

load_dotenv()
from decimal import Decimal, InvalidOperation

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from core.engine import fetch_btc_price, get_weishen_position, process_request, scale_orders, get_address
from core.storage import get_user_position, set_user_position

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def get_main_menu_keyboard():
    """Create the main menu inline keyboard."""
    keyboard = [
        [InlineKeyboardButton("📊 BTC Price", callback_data="price")],
        [InlineKeyboardButton("👤 Weishen's Position", callback_data="weishen")],
        [InlineKeyboardButton("💼 My Position", callback_data="me")],
        [InlineKeyboardButton("✏️ Edit My Position", callback_data="edit")],
    ]
    return InlineKeyboardMarkup(keyboard)


def format_price(result: dict) -> str:
    """Format BTC price response."""
    sign = "+" if result["change_24h"] >= 0 else ""
    return (
        f"<b>BTC/USDT:</b> ${result['price']:,.2f}\n"
        f"<b>24h:</b> {sign}{result['change_pct_24h']:.2f}% ({sign}${result['change_24h']:,.2f})"
    )


def format_weishen(result: dict) -> str:
    """Format weishen's position response."""
    if result.get("error"):
        return f"Error: {result['error']}"

    sign = "+" if result["pnl"] >= 0 else ""
    direction = result["direction"].upper()

    lines = [
        f"<b>Position:</b> {direction} {result['size']:.5f} BTC",
        f"<b>Entry:</b> ${result['entry_price']:,.2f}",
        f"<b>Current:</b> ${result['current_price']:,.2f}",
        f"<b>P&L:</b> {sign}${result['pnl']:,.2f}",
        f"<b>Last activity:</b> {result['last_activity']}",
    ]

    # Add orders
    orders = result.get("orders", [])
    if orders:
        lines.append(f"\n<b>Orders ({len(orders)}):</b>")
        lines.append("<pre>")
        lines.append(f"{'Side':<5}{'Price':>10}{'Size':>10}")
        lines.append("-" * 25)

        # Sort by price descending
        sorted_orders = sorted(orders, key=lambda x: Decimal(x.get("limitPx", "0")), reverse=True)
        for order in sorted_orders:
            side = "BUY" if order.get("side", "").upper() == "B" else "SELL"
            price = Decimal(order.get("limitPx", "0"))
            size = Decimal(order.get("sz", "0"))
            lines.append(f"{side:<5}${price:>9,.0f}{size:>10.5f}")
        lines.append("</pre>")

    return "\n".join(lines)


def format_my_position(user_pos: dict, weishen: dict, current_price: Decimal) -> str:
    """Format user's position with scaled orders."""
    size = user_pos["size"]
    entry = user_pos["entry_price"]
    direction = "LONG" if size > 0 else "SHORT"
    abs_size = abs(size)

    # Calculate P&L
    if size > 0:  # long
        pnl = (current_price - entry) * abs_size
    else:  # short
        pnl = (entry - current_price) * abs_size

    sign = "+" if pnl >= 0 else ""

    lines = [
        f"<b>Position:</b> {direction} {abs_size:.5f} BTC",
        f"<b>Entry:</b> ${entry:,.2f}",
        f"<b>Current:</b> ${current_price:,.2f}",
        f"<b>P&L:</b> {sign}${pnl:,.2f}",
    ]

    # Scale weishen's orders if directions match
    weishen_direction = weishen.get("direction")
    my_direction = "long" if size > 0 else "short"

    if weishen_direction and weishen_direction == my_direction:
        weishen_size = weishen.get("size", Decimal("0"))
        if weishen_size > 0:
            ratio = abs_size / weishen_size
            scaled = scale_orders(weishen.get("orders", []), ratio)

            lines.append(f"\n<b>Scaled Orders (ratio: {ratio:.4f}):</b>")
            lines.append("<pre>")
            lines.append(f"{'Side':<5}{'Price':>10}{'Size':>10}")
            lines.append("-" * 25)

            sorted_orders = sorted(scaled, key=lambda x: x["price"], reverse=True)
            for order in sorted_orders:
                side = "BUY" if order["side"].upper() == "B" else "SELL"
                lines.append(f"{side:<5}${order['price']:>9,.0f}{order['scaled_size']:>10.3f}")
            lines.append("</pre>")
    elif weishen_direction:
        lines.append(f"\n⚠️ Direction mismatch: You are {my_direction.upper()}, Weishen is {weishen_direction.upper()}")

    return "\n".join(lines)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start and /menu commands."""
    msg = (
        "<b>Hyperliquid BTC Order Scaler</b>\n\n"
        "Choose an option or use commands:\n"
        "• <code>/price</code> - BTC price\n"
        "• <code>/weishen</code> - His position\n"
        "• <code>/me</code> - Your position\n"
        "• <code>/set 0.05 92000</code> - Set your position\n"
        "• Send a number to quick scale (e.g. <code>0.05</code> or <code>-0.05</code>)"
    )
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_menu_keyboard())


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /price command."""
    try:
        result = fetch_btc_price()
        await update.message.reply_text(format_price(result), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Error fetching price: {e}")


async def weishen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /weishen command."""
    result = get_weishen_position()
    await update.message.reply_text(format_weishen(result), parse_mode="HTML")


async def me_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /me command."""
    user_id = update.effective_user.id
    user_pos = get_user_position(user_id)

    if not user_pos:
        await update.message.reply_text(
            "You haven't set your position yet.\n"
            "Use <code>/set SIZE ENTRY</code> to set it.\n"
            "Example: <code>/set 0.05 92000</code> for long 0.05 BTC @ $92,000",
            parse_mode="HTML"
        )
        return

    # Get current price and weishen's data
    try:
        price_data = fetch_btc_price()
        weishen = get_weishen_position()
    except Exception as e:
        await update.message.reply_text(f"Error fetching data: {e}")
        return

    response = format_my_position(user_pos, weishen, price_data["price"])
    await update.message.reply_text(response, parse_mode="HTML")


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /set command to set user's position."""
    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: <code>/set SIZE ENTRY</code>\n"
            "• Positive size = long, negative = short\n"
            "Examples:\n"
            "• <code>/set 0.05 92000</code> - Long 0.05 BTC @ $92,000\n"
            "• <code>/set -0.05 95000</code> - Short 0.05 BTC @ $95,000",
            parse_mode="HTML"
        )
        return

    try:
        size = Decimal(context.args[0])
        entry = Decimal(context.args[1])
    except InvalidOperation:
        await update.message.reply_text("Invalid numbers. Use: <code>/set SIZE ENTRY</code>", parse_mode="HTML")
        return

    if size == 0:
        await update.message.reply_text("Size cannot be zero.")
        return

    if entry <= 0:
        await update.message.reply_text("Entry price must be positive.")
        return

    user_id = update.effective_user.id
    set_user_position(user_id, size, entry)

    direction = "LONG" if size > 0 else "SHORT"
    await update.message.reply_text(
        f"✅ Position saved!\n"
        f"<b>{direction}</b> {abs(size):.5f} BTC @ ${entry:,.2f}\n\n"
        f"Use /me to view your position with scaled orders.",
        parse_mode="HTML"
    )


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks."""
    query = update.callback_query
    await query.answer()

    if query.data == "price":
        try:
            result = fetch_btc_price()
            await query.message.reply_text(format_price(result), parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"Error fetching price: {e}")

    elif query.data == "weishen":
        result = get_weishen_position()
        await query.message.reply_text(format_weishen(result), parse_mode="HTML")

    elif query.data == "me":
        user_id = update.effective_user.id
        user_pos = get_user_position(user_id)

        if not user_pos:
            await query.message.reply_text(
                "You haven't set your position yet.\n"
                "Use <code>/set SIZE ENTRY</code> to set it.\n"
                "Example: <code>/set 0.05 92000</code>",
                parse_mode="HTML"
            )
            return

        try:
            price_data = fetch_btc_price()
            weishen = get_weishen_position()
        except Exception as e:
            await query.message.reply_text(f"Error fetching data: {e}")
            return

        response = format_my_position(user_pos, weishen, price_data["price"])
        await query.message.reply_text(response, parse_mode="HTML")

    elif query.data == "edit":
        await query.message.reply_text(
            "To edit your position, use:\n"
            "<code>/set SIZE ENTRY</code>\n\n"
            "Examples:\n"
            "• <code>/set 0.05 92000</code> - Long 0.05 BTC @ $92,000\n"
            "• <code>/set -0.05 95000</code> - Short 0.05 BTC @ $95,000",
            parse_mode="HTML"
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user message with BTC size input (quick scale)."""
    text = update.message.text.strip()

    try:
        value = Decimal(text)
    except InvalidOperation:
        # Not a number, ignore
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

    response = format_scale_result(result)
    await update.message.reply_text(response, parse_mode="HTML")


def format_scale_result(result: dict) -> str:
    """Format the quick scale result as a Telegram message."""
    lines = []

    lines.append(f"<b>Last activity:</b> {result['last_activity']}")
    lines.append(f"<b>Account:</b> {result['account_direction'].upper()} {result['account_btc_size']} BTC @ ${result['entry_price']:,.2f}")
    lines.append(f"<b>You:</b> {result['user_direction'].upper()} {result['user_btc_size']} BTC (ratio: {result['ratio']:.4f})")
    lines.append(f"<b>Pending orders:</b> {result['num_orders']}")

    # Scaled orders table
    sorted_orders = sorted(result["scaled_orders"], key=lambda x: x["price"], reverse=True)

    lines.append("\n<pre>")
    lines.append(f"{'Side':<5}{'Price':>10}{'Size':>8}{'Notional':>11}")
    lines.append("-" * 34)

    for order in sorted_orders:
        side = "BUY" if order["side"].upper() == "B" else "SELL"
        lines.append(f"{side:<5}${order['price']:>9,.0f}{order['scaled_size']:>8.3f}${order['notional']:>9,.0f}")
    lines.append("</pre>")

    # Summaries
    for label, summary, order_label in [
        ("LONG SUMMARY", result["long_summary"], "Buy"),
        ("SHORT SUMMARY", result["short_summary"], "Sell"),
    ]:
        if not summary:
            continue

        lines.append(f"\n<b>{label}</b>")
        lines.append(f"Current: {summary['current_size']:.3f} BTC")
        lines.append(f"{order_label} total: {summary['order_total']:.3f} BTC")
        lines.append(f"Net: {summary['net_position']:.3f} BTC")

        if summary["avg_entry"] is not None:
            lines.append(f"Avg entry: ${summary['avg_entry']:,.2f}")

        lines.append(f"Capital: ${summary['capital_required']:,.2f}")

    return "\n".join(lines)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is not set.")
        print("Set it in .env file or environment.")
        return

    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("menu", start_command))
    app.add_handler(CommandHandler("price", price_command))
    app.add_handler(CommandHandler("weishen", weishen_command))
    app.add_handler(CommandHandler("me", me_command))
    app.add_handler(CommandHandler("set", set_command))

    # Callback for inline buttons
    app.add_handler(CallbackQueryHandler(button_callback))

    # Text messages (for quick scale with numbers)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is running... Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
