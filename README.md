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

## Example Output

```
======================================================================
HYPERLIQUID BTC ORDER SCALING TOOL
======================================================================

Tracking address: 0xdae4df7207feb3b350e4284c8efe5f7dac37f637

Select your BTC position:
  a) Long
  b) Short

Enter your choice (a/b): a

Enter your BTC position size: 0.05

Your selection: LONG position
Your BTC size: 0.05 BTC

Fetching account data from Hyperliquid...

Account BTC position: LONG
Position size: 0.0176 BTC
Entry price: $92,302.00

Found 17 pending BTC order(s)

Account BTC size: 0.0176 BTC
Your BTC size: 0.05 BTC
Scaling ratio: 2.840909

======================================================================
SCALED ORDERS (sorted by price descending)
======================================================================
Side          Price   Original Size     Scaled Size     Notional
----------------------------------------------------------------------
SELL   $  99,144.00         0.04044         0.11488 $ 11,389.66
SELL   $  98,415.00         0.04049         0.11502 $ 11,319.69
BUY    $  91,555.00         0.03276         0.09306 $  8,520.11
...

======================================================================
LONG POSITION SUMMARY (if all buy orders are filled)
======================================================================
Current Scaled Position:             0.05000 BTC @ $92,302.00
Additional from Orders:              6.22223 BTC
Total Potential Position:            6.27223 BTC
Average Entry Price:         $     81,748.76
Total Capital Required:      $    508,131.90

======================================================================
Done!
======================================================================
```

## License

MIT License - see [LICENSE](LICENSE) file.
