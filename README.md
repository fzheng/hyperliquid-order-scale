# Hyperliquid BTC Order Scaling Tool

A tool that tracks a Hyperliquid account's BTC position and pending orders, then scales them proportionally based on your position size. Available as both a Telegram bot and CLI.

## Features

- **Telegram Bot** with automatic position change notifications
- Real-time BTC price tracking
- Position monitoring (direction, size, entry price, P&L)
- Proportional order scaling based on your position size
- User position storage with comparison to tracked account
- Background polling with change detection

## Telegram Bot

### Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and get your token
2. Set environment variables:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
HYPERLIQUID_ADDRESS=0x...  # Optional, defaults to weishen's address
```

3. Run the bot:

```bash
make bot
```

### Commands

| Command | Description |
|---------|-------------|
| `/start`, `/menu` | Show main menu with options |
| `/price` | Get current BTC price |
| `/weishen` | View tracked account's position and orders |
| `/me` | View your position with scaled orders |
| `/set SIZE ENTRY` | Set your position (e.g., `/set 0.05 92000`) |

### Quick Scale

Send a number directly to get scaled orders:
- `0.05` - Scale for long 0.05 BTC
- `-0.05` - Scale for short 0.05 BTC

### Notifications

The bot automatically polls the tracked account every 10 minutes and sends notifications when:
- Position direction changes
- Position size changes
- Entry price changes
- Orders are added, removed, or modified

## CLI

```bash
make run
# or
python -m cli.main
```

The CLI prompts for:
1. Position direction (long/short)
2. Your BTC position size

## Installation

```bash
pip install -r requirements.txt
# or
make install
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Required for bot |
| `HYPERLIQUID_ADDRESS` | Account address to track | weishen's address |
| `DATA_DIR` | Directory for data files | `.` (current dir) |

## Project Structure

```
hyperliquid-order-scale/
├── bot/
│   └── main.py          # Telegram bot
├── cli/
│   └── main.py          # CLI interface
├── core/
│   ├── engine.py        # Shared business logic
│   └── storage.py       # User state persistence
├── tests/
│   ├── test_engine.py   # Core logic tests
│   └── test_bot.py      # Bot tests
├── requirements.txt
└── Makefile
```

## Running Tests

```bash
make test
```

## Deployment (Railway)

1. Set environment variables in Railway dashboard:
   - `TELEGRAM_BOT_TOKEN`
   - `DATA_DIR=/data` (for persistent storage)

2. Deploy - the bot starts automatically via `make bot`

## License

MIT License - see [LICENSE](LICENSE) file.
