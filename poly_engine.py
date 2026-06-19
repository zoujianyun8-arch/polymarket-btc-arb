#!/usr/bin/env python3
"""
Polymarket BTC 5分钟偏离套利 — 持续运行引擎
规则: BTC偏离 ≥20c + 最优赔率 ≤50c → 99c FOK买入
策略: 单向押注偏离方向，窗口前60s不交易，每窗口只交易一次
"""
import urllib.request, json, time, sys, os
from datetime import datetime, timezone, timedelta

# ============ 配置 ============
PRICE_DEVIATION = 20          # BTC偏离阈值 (c)
MIN_ODDS = 0.50              # 最优赔率上限 (0~1)
BET_AMOUNT = 1               # 每笔预算 (USDC)
MIN_BALANCE_USDC = 5         # 最小余额门槛
DEPOSIT_WALLET = "YOUR_DEPOSIT_WALLET_ADDRESS"  # 替换为你的Polygon存款钱包
MARKET_CACHE_TTL = 10        # 市场数据缓存(秒)
TRADED_FILE = os.path.expanduser("~/.hermes/data/poly_strat_a_traded.json")

# ============ 状态 ============
_clob_client = None
_window_start_price = {}
_cached_market = {}

# ============ 持久化 ============
def load_traded():
    if os.path.exists(TRADED_FILE):
        try:
            with open(TRADED_FILE) as f:
                return set(json.load(f))
        except: pass
    return set()

def save_traded(traded_set):
    os.makedirs(os.path.dirname(TRADED_FILE), exist_ok=True)
    with open(TRADED_FILE, 'w') as f:
        json.dump(sorted(traded_set), f)

# ============ CLOB客户端 ============
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
    client = get_clob(pk)
    bal = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
    return float(bal['balance']) / 1_000_000

# ============ 行情 ============
def get_current_btc():
    try:
        r = urllib.request.urlopen("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5)
        return float(json.loads(r.read())['price'])
    except: return None

def get_cached_market(ts):
    """带缓存的获取市场数据"""
    global _cached_market
    now = time.time()
    if _cached_market.get('ts') == ts and now - _cached_market.get('time', 0) < MARKET_CACHE_TTL:
        return _cached_market.get('data')
    m = fetch_market(ts)
    if m:
        _cached_market = {'ts': ts, 'time': now, 'data': m}
    return m

def fetch_market(ts):
    """获取BTC 5分钟窗口"""
    slug = f"btc-updown-5m-{ts}"
    try:
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
                    'up': float(prices[0]),
                    'down': float(prices[1]),
                    'clobTokenIds': clob_ids,
                }
    except: pass
    return None

def fetch_window_start_price(ts):
    """窗口开始的BTC价格（缓存）"""
    if ts in _window_start_price:
        return _window_start_price[ts]
    start_ms = (ts - 300) * 1000
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={start_ms}&limit=1"
        r = urllib.request.urlopen(url, timeout=5)
        klines = json.loads(r.read())
        if klines:
            price = float(klines[0][1])
            _window_start_price[ts] = price
            return price
    except: pass
    return None

# ============ 下单 ============
def execute_buy(token_id, amount, condition_id, pk, coin, direction):
    """99c FOK抢单"""
    from py_clob_client_v2 import OrderArgsV2, Side, CreateOrderOptions, OrderType
    client = get_clob(pk)

    try:
        info = client.get_clob_market_info(condition_id)
        tick_size = str(info.get('minimum_tick_size', info.get('mts', '0.01')))
        neg_risk = bool(info.get('neg_risk', info.get('nr', False)))
    except:
        tick_size = "0.01"
        neg_risk = False

    use_price = 0.99
    size = round(amount / use_price, 2)
    if size < 5:
        size = 5.0

    order = OrderArgsV2(token_id=token_id, price=use_price, size=size, side=Side.BUY)
    opt = CreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk)

    try:
        resp = client.create_and_post_order(order, opt, OrderType.FOK, post_only=False)
        oid = resp.get('orderID', '')[:24] if isinstance(resp, dict) else str(resp)[:24]
        status = resp.get('status', '?')
        matched = resp.get('matchedAmount', '0')
        if status == 'MATCHED' or (isinstance(matched, str) and float(matched) > 0):
            print(f"  ✅ {coin}{direction}成交 {matched} 张 @{use_price*100:.0f}c (order={oid})")
            return True
        elif 'filledAmount' in resp and float(resp.get('filledAmount', 0)) > 0:
            print(f"  ✅ {coin}{direction}部分成交 {resp['filledAmount']} 张 (order={oid})")
            return True
        else:
            print(f"  ✅ {coin}{direction}FOK已处理 (order={oid})")
            return True
    except Exception as e:
        print(f"  ❌ {coin}{direction} [{str(e)[:200]}]")
        return False

# ============ 主循环 ============
def main():
    # 从.env加载私钥
    pk = ""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("POLY_PRIVATE_KEY="):
                    pk = line.split("=", 1)[1]
                    break

    if not pk:
        print(" ⚠️ 未找到POLY_PRIVATE_KEY，请在.env中配置")
        return

    traded = load_traded()
    cst = datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M')
    print(f"[{cst}] 🚀 策略A引擎启动 — BTC偏离套利")
    print(f"[{cst}] 条件: 偏离≥{PRICE_DEVIATION}c + 赔率≤{MIN_ODDS*100:.0f}c → 99c FOK ${BET_AMOUNT}")

    balance = get_balance(pk)
    print(f"[{cst}] 余额: ${balance:.2f}")

    last_ts = 0
    while True:
        loop_start = time.time()
        now_utc = int(time.time())
        now_cst = datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')

        ts = (now_utc // 300) * 300
        window_key = str(ts)

        if ts != last_ts:
            _window_start_price.pop(last_ts, None)
            print(f"[{now_cst}] 新窗口 {window_key} | 剩余{(ts+300)-now_utc}s")
            last_ts = ts

        if window_key not in traded:
            elapsed = now_utc - ts
            if elapsed >= 60:
                try:
                    btc = get_current_btc()
                    if not btc:
                        time.sleep(5)
                        continue

                    market = get_cached_market(ts)
                    if not market:
                        time.sleep(5)
                        continue

                    up, down = market['up'], market['down']
                    start = fetch_window_start_price(ts)
                    if not start:
                        time.sleep(5)
                        continue

                    diff = btc - start
                    action = None
                    token_id = None
                    direction = ""

                    if diff >= PRICE_DEVIATION and up <= MIN_ODDS:
                        action = "BUY_UP"
                        token_id = market['clobTokenIds'][0]
                        direction = "Up"
                    elif diff <= -PRICE_DEVIATION and down <= MIN_ODDS:
                        action = "BUY_DOWN"
                        token_id = market['clobTokenIds'][1]
                        direction = "Down"

                    if action:
                        print(f"[{now_cst}] ⚡ BTC ${btc:,.0f} | 起始${start:,.0f} | 偏离{diff:+.0f}c | Up{up*100:.0f}c/Down{down*100:.0f}c")
                        print(f"     触发: {direction}@{up if direction=='Up' else down:.0%} | 预算${BET_AMOUNT}")

                        ok = execute_buy(token_id, BET_AMOUNT, market['conditionId'], pk, "BTC", direction)
                        if ok:
                            print(f"[{now_cst}] ✅ 窗口{window_key} 交易完成")
                        else:
                            print(f"[{now_cst}] ❌ 窗口{window_key} 下单失败")

                        traded.add(window_key)
                        save_traded(traded)
                except Exception as e:
                    print(f"[{now_cst}] ⚠️ 异常: {str(e)[:100]}")

        sleep_time = max(0, 1.0 - (time.time() - loop_start))
        if sleep_time > 0:
            time.sleep(sleep_time)

if __name__ == '__main__':
    main()
