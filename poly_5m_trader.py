#!/usr/bin/env python3
"""
Polymarket BTC 5分钟套利 — 轻量版
规则: BTC偏离≥20c + 最优赔率≤50c → 99c FOK买入
用法: python3 poly_5m_trader.py --dry-run  (预览)
      python3 poly_5m_trader.py --live     (实盘)
"""
import urllib.request, json, time, sys, os, argparse
from datetime import datetime, timezone, timedelta

# ============ 配置（按需调整） ============
PRICE_DEVIATION = 20   # BTC偏离阈值(c)
MIN_ODDS = 0.50        # 赔率上限
BET_AMOUNT = 1         # 每笔预算(USDC)
MIN_BALANCE_USDC = 5   # 最小余额门槛
DEPOSIT_WALLET = "YOUR_DEPOSIT_WALLET_ADDRESS"  # ← 替换为你的Polygon充值钱包

_clob_client = None

def get_clob(pk):
    global _clob_client
    if _clob_client is None:
        from py_clob_client_v2 import ClobClient, SignatureTypeV2
        temp = ClobClient(host="https://clob.polymarket.com", chain_id=137, key=pk)
        creds = temp.create_or_derive_api_key()
        _clob_client = ClobClient(
            "https://clob.polymarket.com", chain_id=137, key=pk, creds=creds,
            signature_type=SignatureTypeV2.POLY_1271, funder=DEPOSIT_WALLET,
        )
    return _clob_client

def get_balance(pk):
    from py_clob_client_v2 import BalanceAllowanceParams, AssetType
    bal = get_clob(pk).get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
    return float(bal['balance']) / 1_000_000

def get_current_btc():
    r = urllib.request.urlopen("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
    return float(json.loads(r.read())['price'])

def get_current_window():
    now_utc = int(time.time())
    ts = (now_utc // 300) * 300
    slug = f"btc-updown-5m-{ts}"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    r = urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=5)
    events = json.loads(r.read())
    if events and events[0].get('markets'):
        m = events[0]['markets'][0]
        if m.get('active'):
            prices = json.loads(m.get('outcomePrices', '[0,0]'))
            clob_ids = json.loads(m.get('clobTokenIds', '[]'))
            return {
                'question': m['question'],
                'conditionId': m.get('conditionId', ''),
                'endDate': m.get('endDate', ''),
                'outcomePrices': [float(p) for p in prices],
                'clobTokenIds': clob_ids,
                'ts': ts,
            }
    return None

def get_window_start_price(ts):
    start_ms = (ts - 300) * 1000
    r = urllib.request.urlopen(f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={start_ms}&limit=1", timeout=5)
    klines = json.loads(r.read())
    return float(klines[0][1]) if klines else None

def execute_buy(token_id, amount, price, condition_id, pk):
    from py_clob_client_v2 import OrderArgsV2, Side, CreateOrderOptions, OrderType
    client = get_clob(pk)
    try:
        info = client.get_clob_market_info(condition_id)
        tick_size = str(info.get('minimum_tick_size', '0.01'))
        neg_risk = bool(info.get('neg_risk', False))
    except:
        tick_size, neg_risk = "0.01", False

    use_price = 0.99
    size = max(5.0, round(amount / use_price, 2))
    order = OrderArgsV2(token_id=token_id, price=use_price, size=size, side=Side.BUY)
    opt = CreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk)
    resp = client.create_and_post_order(order, opt, OrderType.FOK, post_only=False)
    oid = resp.get('orderID', '?')[:24]
    print(f"  状态: {resp.get('status','?')} order={oid}")
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    is_live = args.live

    now_str = datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M')
    mode = "🔴 LIVE" if is_live else "🔍 DRY"
    print(f"[{now_str}] [策略A] BTC 5m套利 {mode} | 偏离≥{PRICE_DEVIATION}c 赔率≤{MIN_ODDS*100:.0f}c")

    # 读密钥
    pk = ""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("POLY_PRIVATE_KEY="):
                    pk = line.split("=", 1)[1]

    if not pk:
        print(" ⚠️ 未找到POLY_PRIVATE_KEY，请在.env中配置")
        return

    balance = get_balance(pk)
    print(f" 余额: ${balance:.2f}")
    if balance < MIN_BALANCE_USDC and is_live:
        print(" 余额不足，跳过")
        return

    btc = get_current_btc()
    print(f" BTC: ${btc:,.0f}")

    m = get_current_window()
    if not m:
        print(" 当前无活跃窗口")
        return

    up, down = m['outcomePrices']
    print(f" {m['question']}")
    print(f" Up {up*100:.0f}c | Down {down*100:.0f}c")

    elapsed = int(time.time()) - m['ts']
    if elapsed < 60:
        print(f" 窗口前60秒不交易 (已过{elapsed}s)")
        return

    start = get_window_start_price(m['ts'])
    if not start:
        print(" 无法获取起始价")
        return

    diff = btc - start
    print(f" 起始 ${start:,.0f} → 偏离 {diff:+.0f}")

    action, token_id, direction = None, None, ""
    if diff >= PRICE_DEVIATION and up <= MIN_ODDS:
        action, token_id, direction = "BUY_UP", m['clobTokenIds'][0], "Up"
    elif diff <= -PRICE_DEVIATION and down <= MIN_ODDS:
        action, token_id, direction = "BUY_DOWN", m['clobTokenIds'][1], "Down"

    if not action:
        print(" 无机会")
        return

    print(f" ✅ {direction}@{up if direction=='Up' else down:.0%} ${BET_AMOUNT}")
    if is_live:
        execute_buy(token_id, BET_AMOUNT, up if direction=='Up' else down, m['conditionId'], pk)

if __name__ == '__main__':
    main()
