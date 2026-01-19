# Hyperliquid BTC Order Scaling Tool

A CLI tool that retrieves BTC position and pending orders from a Hyperliquid account, then scales the orders proportionally based on your BTC position size.

## Features

- Fetches real-time BTC position data from Hyperliquid
- Retrieves all pending BTC orders
- Validates position direction (long/short) matches
- Scales orders proportionally based on your position size
- Displays scaled orders sorted by price
- Shows position summary with average entry price and capital required

## Installation

```bash
pip install -r requirements.txt
```

Or using make:

```bash
make install
```

## Usage

```bash
make run
```

Or directly:

```bash
python scale_orders.py
```

The tool will prompt you for:
1. Your position direction (long or short)
2. Your BTC position size

## Configuration

Set a custom Hyperliquid address via environment variable:

```bash
# Windows
set HYPERLIQUID_ADDRESS=0x... && python scale_orders.py

# Linux/Mac
HYPERLIQUID_ADDRESS=0x... python scale_orders.py
```

Default address: `0xdae4df7207feb3b350e4284c8efe5f7dac37f637`

## Running Tests

```bash
make test
```

## License

MIT License - see [LICENSE](LICENSE) file.
