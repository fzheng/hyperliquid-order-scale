#!/usr/bin/env python3
"""Telegram bot interface for Hyperliquid BTC Order Scaling Tool."""

import asyncio
import os
import logging
from dotenv import load_dotenv

load_dotenv()
from decimal import Decimal, InvalidOperation

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from core import __version__
from core.engine import fetch_btc_price, get_weishen_position, process_request, scale_orders
from core.storage import (
    get_user_position, set_user_position, register_user, get_all_users,
    get_previous_state, save_previous_state
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Suppress noisy httpx polling logs
logging.getLogger("httpx").setLevel(logging.WARNING)

# Polling interval in seconds (10 minutes)
POLL_INTERVAL = 600


def get_user_id(update: Update) -> int | None:
    """Safely get user ID from update, returns None for channel posts or anonymous admins."""
    if update.effective_user is None:
        return None
    return update.effective_user.id


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


# --- Change Detection ---

def detect_changes(prev: dict | None, curr: dict) -> list[str]:
    """Detect changes between previous and current state.

    Returns list of change descriptions.
    """
    if prev is None:
        return []  # First run, no changes to report

    changes = []

    # Position direction change
    prev_dir = prev.get("direction") or "none"
    curr_dir = curr.get("direction") or "none"
    if prev_dir != curr_dir:
        changes.append(f"🔄 Direction: {prev_dir.upper()} → {curr_dir.upper()}")

    # Position size change
    prev_size = Decimal(prev.get("size", "0"))
    curr_size = Decimal(str(curr.get("size", 0)))
    if prev_size != curr_size:
        diff = curr_size - prev_size
        sign = "+" if diff > 0 else ""
        changes.append(f"📊 Size: {prev_size:.5f} → {curr_size:.5f} ({sign}{diff:.5f})")

    # Entry price change
    prev_entry = Decimal(prev.get("entry_price", "0"))
    curr_entry = Decimal(str(curr.get("entry_price", 0)))
    if prev_entry != curr_entry:
        changes.append(f"💰 Entry: ${prev_entry:,.2f} → ${curr_entry:,.2f}")

    # Order changes - normalize oid to string for consistent comparison
    prev_orders = {str(o.get("oid")): o for o in prev.get("orders", []) if o.get("oid") is not None}
    curr_orders = {str(o.get("oid")): o for o in curr.get("orders", []) if o.get("oid") is not None}

    prev_oids = set(prev_orders.keys())
    curr_oids = set(curr_orders.keys())

    def safe_price(val) -> str:
        """Safely format price, handling malformed data."""
        try:
            return f"${Decimal(str(val)):,.0f}"
        except (ValueError, TypeError, InvalidOperation):
            return str(val)

    def normalize_val(val) -> str:
        """Normalize numeric values to string for comparison."""
        try:
            return str(Decimal(str(val)))
        except (ValueError, TypeError, InvalidOperation):
            return str(val) if val is not None else ""

    # New orders
    added = curr_oids - prev_oids
    for oid in added:
        o = curr_orders[oid]
        side = "BUY" if str(o.get("side", "")).upper() == "B" else "SELL"
        changes.append(f"➕ Order added: {side} {o.get('sz')} @ {safe_price(o.get('limitPx', '0'))}")

    # Removed orders
    removed = prev_oids - curr_oids
    for oid in removed:
        o = prev_orders[oid]
        side = "BUY" if str(o.get("side", "")).upper() == "B" else "SELL"
        changes.append(f"➖ Order removed: {side} {o.get('sz')} @ {safe_price(o.get('limitPx', '0'))}")

    # Modified orders - normalize values before comparison to handle string vs number differences
    for oid in prev_oids & curr_oids:
        p, c = prev_orders[oid], curr_orders[oid]
        p_sz, c_sz = normalize_val(p.get("sz")), normalize_val(c.get("sz"))
        p_px, c_px = normalize_val(p.get("limitPx")), normalize_val(c.get("limitPx"))
        if p_sz != c_sz or p_px != c_px:
            side = "BUY" if str(c.get("side", "")).upper() == "B" else "SELL"
            changes.append(
                f"✏️ Order modified: {side} {p.get('sz')} @ {safe_price(p.get('limitPx', '0'))} → "
                f"{c.get('sz')} @ {safe_price(c.get('limitPx', '0'))}"
            )

    return changes


TELEGRAM_MAX_LENGTH = 4096


def format_changes(changes: list[str], curr: dict) -> str:
    """Format change notification message, truncating if it exceeds Telegram's limit."""
    header = "🔔 <b>Weishen Position Update</b>\n"
    direction = (curr.get("direction") or "").upper()
    size = curr.get("size", 0)
    entry_price = curr.get("entry_price", 0)
    footer = f"\n<b>Current:</b> {direction} {size:.5f} BTC @ ${entry_price:,.2f}"

    # Reserve space for header, footer, and potential truncation message
    truncation_msg = f"\n\n... and {{}} more changes"
    reserved = len(header) + len(footer) + len(truncation_msg.format(999))

    lines = []
    total_len = reserved
    truncated_count = 0

    for change in changes:
        change_len = len(change) + 1  # +1 for newline
        if total_len + change_len <= TELEGRAM_MAX_LENGTH:
            lines.append(change)
            total_len += change_len
        else:
            truncated_count += 1

    result = [header]
    result.extend(lines)
    if truncated_count > 0:
        result.append(truncation_msg.format(truncated_count))
    result.append(footer)

    return "\n".join(result)


async def poll_and_notify(context: ContextTypes.DEFAULT_TYPE):
    """Background job: poll Hyperliquid and notify users of changes."""
    try:
        curr = await asyncio.to_thread(get_weishen_position)
        if curr.get("error"):
            logger.warning(f"Poll error: {curr['error']}")
            return

        prev = get_previous_state()
        changes = detect_changes(prev, curr)

        if changes:
            msg = format_changes(changes, curr)
            users = get_all_users()
            logger.info(f"Detected {len(changes)} changes, notifying {len(users)} users")

            for user_id in users:
                try:
                    await context.bot.send_message(chat_id=user_id, text=msg, parse_mode="HTML")
                except Exception as e:
                    logger.warning(f"Failed to notify user {user_id}: {e}")

        # Save current state for next comparison
        save_previous_state(curr)

    except Exception as e:
        logger.error(f"Poll error: {e}")


# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start and /menu commands."""
    if not update.message:
        return  # Ignore edited messages or other update types
    user_id = get_user_id(update)
    if user_id:
        register_user(user_id)
    msg = (
        "<b>Hyperliquid BTC Order Scaler</b>\n\n"
        "Choose an option or use commands:\n"
        "• <code>/price</code> - BTC price\n"
        "• <code>/weishen</code> - His position\n"
        "• <code>/me</code> - Your position\n"
        "• <code>/set 0.05 92000</code> - Set your position\n"
        "• Send a number to quick scale (e.g. <code>0.05</code> or <code>-0.05</code>)\n\n"
        "📢 You'll receive automatic updates when Weishen's position changes."
    )
    await update.message.reply_text(msg, parse_mode="HTML", reply_markup=get_main_menu_keyboard())


async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /price command."""
    if not update.message:
        return
    user_id = get_user_id(update)
    if user_id:
        register_user(user_id)
    try:
        result = await asyncio.to_thread(fetch_btc_price)
        await update.message.reply_text(format_price(result), parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"Error fetching price: {e}")


async def weishen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /weishen command."""
    if not update.message:
        return
    user_id = get_user_id(update)
    if user_id:
        register_user(user_id)
    result = await asyncio.to_thread(get_weishen_position)
    await update.message.reply_text(format_weishen(result), parse_mode="HTML")


async def me_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /me command."""
    if not update.message:
        return
    user_id = get_user_id(update)
    if not user_id:
        return  # Ignore channel posts or anonymous admins
    register_user(user_id)
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
        price_data = await asyncio.to_thread(fetch_btc_price)
        weishen = await asyncio.to_thread(get_weishen_position)
    except Exception as e:
        await update.message.reply_text(f"Error fetching data: {e}")
        return

    if weishen.get("error"):
        await update.message.reply_text(f"Error fetching Weishen's data: {weishen['error']}")
        return

    response = format_my_position(user_pos, weishen, price_data["price"])
    await update.message.reply_text(response, parse_mode="HTML")


async def set_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /set command to set user's position."""
    if not update.message:
        return
    user_id = get_user_id(update)
    if not user_id:
        return  # Ignore channel posts or anonymous admins
    register_user(user_id)
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
    user_id = get_user_id(update)
    if user_id:
        register_user(user_id)
    query = update.callback_query
    await query.answer()

    if query.data == "price":
        try:
            result = await asyncio.to_thread(fetch_btc_price)
            await query.message.reply_text(format_price(result), parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"Error fetching price: {e}")

    elif query.data == "weishen":
        result = await asyncio.to_thread(get_weishen_position)
        await query.message.reply_text(format_weishen(result), parse_mode="HTML")

    elif query.data == "me":
        if not user_id:
            return  # Ignore if no user context
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
            price_data = await asyncio.to_thread(fetch_btc_price)
            weishen = await asyncio.to_thread(get_weishen_position)
        except Exception as e:
            await query.message.reply_text(f"Error fetching data: {e}")
            return

        if weishen.get("error"):
            await query.message.reply_text(f"Error fetching Weishen's data: {weishen['error']}")
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
    if not update.message or not update.message.text:
        return
    user_id = get_user_id(update)
    if user_id:
        register_user(user_id)
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
        result = await asyncio.to_thread(process_request, direction, btc_size)
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

    # Background job: poll every 10 minutes
    app.job_queue.run_repeating(poll_and_notify, interval=POLL_INTERVAL, first=10)

    print(f"Hyperliquid BTC Order Scaler v{__version__}")
    print(f"Bot is running... Polling every {POLL_INTERVAL // 60} minutes.")
    print("Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
