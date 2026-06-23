# Polymarket Cross-Currency Spread Arbitrage — Strategy D

When BTC or ETH hits ≥95¢ on a 5-minute window, buy the cheapest correlated
coin that's still >60¢ on the same side.

## How It Works

1. Every second, fetches orderbook ask1 prices for 5 coins:
   BTC, ETH, SOL, XRP, BNB
2. **Trigger**: BTC or ETH ask ≥ 95¢ (Up or Down)
   - BTC checked first, then ETH
3. **Direction conflict guard**: if both BTC and ETH have data, check whether the
   non-trigger coin's opposite-direction ask > 50¢ — if so, skip (market disagrees)
4. **Selection**: among all 5 coins, pick the cheapest same-direction ask > 60¢
5. **Entry**: FOK buy at 99¢
   - ETH target: $10 (10 lots)
   - Others (BTC/SOL/XRP/BNB): $5 (5 lots)
6. **Dedup**: one trade per 5-minute UTC window (persisted to JSON)
7. No auto-sell, no take-profit — pure entry

## Key Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| Trigger threshold | 95¢ | BTC or ETH ask1 |
| Conflict threshold | 50¢ | Opposite direction on non-trigger |
| Minimum candidate price | 60¢ | Same direction |
| Entry price | 99¢ | FOK, aggressive fill |
| ETH bet size | $10 | 10 lots |
| Other bet size | $5 | 5 lots |

## Files

| File | Description |
|------|-------------|
| `poly_strat_d.py` | Strategy D runner — continuous loop, 1s refresh |
| `poly_strat_d_traded.json` | Traded window dedup (auto-created) |

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install py-clob-client-v2
cp .env.example .env
# Edit .env with your Polymarket private key
# Edit poly_strat_d.py: set DEPOSIT_WALLET to your Polygon address
python3 poly_strat_d.py
```

## Prerequisites

- Python 3.8+
- A Polymarket account with deposited USDC (Polygon network)
- An API key from [clob.polymarket.com](https://clob.polymarket.com)
- Your deposit wallet address (the Polygon wallet you deposited from)

## Configuration

Edit `.env`:

```
POLY_PRIVATE_KEY=your_private_key_here
```

## License

MIT
