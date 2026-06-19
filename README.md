# Polymarket BTC 5-Minute Arbitrage

A bot that trades BTC 5-minute up/down markets on Polymarket, exploiting short-term momentum deviations.

**Strategy**: When BTC moves ≥$20 within a 5-minute window and the corresponding outcome is priced ≤50¢, place a 99¢ FOK (fill-or-kill) buy order. This is a momentum-following strategy — betting that the initial move is genuine and the market hasn't fully priced it in.

## How It Works

1. Every 5 minutes, Polymarket opens a new "BTC > X at Y:00?" market
2. The bot records BTC price at window start (from Binance 1m klines)
3. It monitors BTC price continuously; if deviation ≥20¢ and best odds ≤50¢, it buys
4. Uses 99¢ FOK (fill-or-kill) orders for instant execution at maker-unfriendly pricing
5. Each window trades at most once — no re-entries

## Files

| File | Description |
|------|-------------|
| `poly_engine.py` | Continuous engine — runs 24/7, checks every second, trades live |
| `poly_5m_trader.py` | Lightweight one-shot version — run it on a cron for periodic checks |
| `requirements.txt` | Python dependencies |
| `.env.example` | Configuration template (copy to `.env` and fill in) |

## Quick Start

### 1. Prerequisites

- Python 3.8+
- A Polymarket account with deposited USDC (Polygon network)
- An API key from [clob.polymarket.com](https://clob.polymarket.com)
- Your deposit wallet address (the Polygon wallet you deposited from)

### 2. Setup

```bash
git clone https://github.com/YOUR_USER/polymarket-btc-arb.git
cd polymarket-btc-arb
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your private key and wallet
```

### 3. Run

**Dry-run (no real trades):**
```bash
python3 poly_5m_trader.py --dry-run
```

**Live trade (one-shot):**
```bash
python3 poly_5m_trader.py --live
```

**Continuous engine (runs forever):**
```bash
python3 poly_engine.py
```

Or run in background:
```bash
nohup python3 poly_engine.py > engine.log 2>&1 &
```

## Configuration

Edit the constants at the top of each script:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `PRICE_DEVIATION` | 20 | BTC price deviation threshold (cents) |
| `MIN_ODDS` | 0.50 | Maximum outcome price to enter (0.50 = 50¢) |
| `BET_AMOUNT` | 1 | Budget per trade (USDC) |
| `MIN_BALANCE_USDC` | 5 | Minimum balance to keep trading |
| `DEPOSIT_WALLET` | — | Your Polygon deposit wallet address |

## Cost Per Trade

Each trade buys **5 contracts × 99¢ = $4.95** (minimum contract size).  
If the position settles ITM, each contract pays $1 → $5.00 return ($0.05 profit per $4.95 risked).  
If OTM, the full $4.95 is lost.

## Notes

- This is a **high-frequency, low-margin** strategy. Most trades lose; winners need to outnumber losers.
- FOK orders are aggressive (99¢ on a 50¢ market) — you pay a premium for guaranteed fill.
- The bot runs on Polymarket's Polygon-based CLOB — no gas fees per trade.
- Each window checks the opening price once and compares against current BTC price continuously.
- Set `live=true` only after you're comfortable with the strategy in dry-run mode.

## License

MIT
