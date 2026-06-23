#!/usr/bin/env python3
"""
策略D — 跨币种价差套利（实盘版 v9）
下单size用整数张数（int），避免精度问题。
"""
import sys, json, urllib.request, time, os, logging

BET_AMOUNT = 5
DEPOSIT_WALLET = "0x..."  # 你的Polygon存款钱包地址
LOG_FILE = "poly_strat_d.log"
TRADED_FILE = "poly_strat_d_traded.json"
COINS = [
    ("BTC",  "btc-updown-5m"),
    ("ETH",  "eth-updown-5m"),
    ("SOL",  "sol-updown-5m"),
    ("XRP",  "xrp-updown-5m"),
    ("BNB",  "bnb-updown-5m"),
]

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
open(LOG_FILE, 'w').close()

pk = ""
env_path = '.env'
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith("POLY_PRIVATE_KEY="):
                pk = line.split("=", 1)[1]
                break
if not pk:
    logging.error("无密钥")
    sys.exit(1)

sys.path.insert(0, 'venv/lib/python3.11/site-packages')
from py_clob_client_v2 import ClobClient, SignatureTypeV2, OrderArgsV2, Side, CreateOrderOptions, OrderType, BalanceAllowanceParams, AssetType

temp = ClobClient(host="https://clob.polymarket.com", chain_id=137, key=pk)
creds = temp.create_or_derive_api_key()
logging.info(f"API Key: {creds.api_key[:16]}...")
client = ClobClient(
    "https://clob.polymarket.com", chain_id=137, key=pk, creds=creds,
    signature_type=SignatureTypeV2.POLY_1271, funder=DEPOSIT_WALLET,
)

bal = client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL))
balance = float(bal['balance']) / 1_000_000
logging.info(f"余额: ${balance:.2f}")
if balance < BET_AMOUNT:
    logging.error(f"余额不足")
    sys.exit(1)

def load_traded():
    if os.path.exists(TRADED_FILE):
        try:
            with open(TRADED_FILE) as f:
                return set(json.load(f))
        except: pass
    return set()

def save_traded(traded):
    with open(TRADED_FILE, 'w') as f:
        json.dump(list(traded), f)

def urlopen_with_timeout(url, timeout=5):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0'}), timeout=timeout)
        return json.loads(r.read())
    except:
        return None

def fetch_market_data(ts):
    data = {}
    for name, slug_base in COINS:
        slug = f"{slug_base}-{ts}"
        raw = urlopen_with_timeout(f"https://gamma-api.polymarket.com/markets?slug={slug}")
        items = raw if isinstance(raw, list) else []
        if len(items) == 0:
            continue
        m = items[0]
        tok_str = m.get('clobTokenIds', '[]')
        toks = json.loads(tok_str) if isinstance(tok_str, str) else tok_str
        if len(toks) < 2:
            continue

        up_book = urlopen_with_timeout(f"https://clob.polymarket.com/book?token_id={toks[0]}")
        down_book = urlopen_with_timeout(f"https://clob.polymarket.com/book?token_id={toks[1]}")

        up_ask = 0
        down_ask = 0
        if up_book:
            asks = sorted(up_book.get('asks', []), key=lambda x: float(x['price']))
            up_ask = float(asks[0]['price']) if asks else 0
        if down_book:
            asks = sorted(down_book.get('asks', []), key=lambda x: float(x['price']))
            down_ask = float(asks[0]['price']) if asks else 0

        data[name] = {
            'slug': slug, 'conditionId': m.get('conditionId', ''),
            'up_token': toks[0], 'down_token': toks[1],
            'up_ask': up_ask, 'down_ask': down_ask,
        }
    return data

def trade(token_id, condition_id, bet_amount=None):
    if bet_amount is None:
        bet_amount = BET_AMOUNT
    try:
        info = client.get_clob_market_info(condition_id)
        tick_size = str(info.get('minimum_tick_size', info.get('mts', '0.01')))
        neg_risk = bool(info.get('neg_risk', info.get('nr', False)))
    except:
        tick_size = "0.01"
        neg_risk = False

    use_price = 0.99
    # 用整数张数，完全避免精度问题
    num_tickets = int(bet_amount / use_price)
    if num_tickets < 5:
        num_tickets = 5

    order = OrderArgsV2(token_id=token_id, price=use_price, size=float(num_tickets), side=Side.BUY)
    opt = CreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk)

    try:
        resp = client.create_and_post_order(order, opt, OrderType.FOK, post_only=False)
        msg = f"成交! {num_tickets}张 price=0.99"
        logging.info(msg)
        print(msg)
    except Exception as e:
        msg = f"下单失败: {str(e)[:200]}"
        logging.error(msg)
        print(msg)

def run():
    traded = load_traded()
    logging.info("策略D启动")
    logging.info(f"已有traded记录: {len(traded)}个: {traded}")

    while True:
        try:
            now_utc = int(time.time())
            ts = (now_utc // 300) * 300
            window_key = f"btc-updown-5m-{ts}"

            if window_key in traded:
                time.sleep(1)
                continue

            markets = fetch_market_data(ts)
            if not markets:
                time.sleep(1)
                continue

            # 触发检测
            trigger_coin = None
            trigger_dir = None
            for coin_name in ['BTC', 'ETH']:
                m = markets.get(coin_name)
                if not m: continue
                if m['up_ask'] > 0.95:
                    trigger_coin = coin_name; trigger_dir = 'up'; break
                if m['down_ask'] > 0.95:
                    trigger_coin = coin_name; trigger_dir = 'down'; break

            if not trigger_coin:
                time.sleep(1)
                continue

            # 方向相反跳过：触发币≥95c时，另一币反方向>50c就跳过
            btc = markets.get('BTC')
            eth = markets.get('ETH')
            if btc and eth:
                other = eth if trigger_coin == 'BTC' else btc
                other_rev_ask = other['down_ask'] if trigger_dir == 'up' else other['up_ask']
                if other_rev_ask > 0.50:
                    conflicts = f"{trigger_coin} {trigger_dir} → {btc['up_ask']*100:.0f}c/{btc['down_ask']*100:.0f}c, ETH {eth['up_ask']*100:.0f}c/{eth['down_ask']*100:.0f}c"
                    logging.info(f"方向相反跳过: {conflicts}")
                    time.sleep(1)
                    continue

            # 选币：所有币种同向>60c最低价
            df = f"{trigger_dir}_ask"
            dl = "Up" if trigger_dir == 'up' else "Down"
            candidates = [(m[df], n, m) for n, m in markets.items() if m[df] > 0.60]
            candidates.sort(key=lambda x: x[0])

            if not candidates:
                logging.info(f"{trigger_coin} {dl}=>{markets[trigger_coin][df]*100:.0f}c >95c，但无>60c候选")
                for n, m in markets.items():
                    logging.info(f"  {n} {dl}={m[df]*100:.0f}c")
                time.sleep(1)
                continue

            price, name, m = candidates[0]
            token_id = m[f'{trigger_dir}_token']
            condition_id = m['conditionId']

            msg = f"触发 {trigger_coin} {dl}={markets[trigger_coin][df]*100:.0f}c → 买入 {name} {dl} @{price*100:.0f}c"
            logging.info(msg)
            print(msg)

            traded.add(window_key)
            save_traded(traded)
            # 选中ETH时下$10，其他币$5
            if name == 'ETH':
                trade(token_id, condition_id, 10)
            else:
                trade(token_id, condition_id)
            time.sleep(1)
        except KeyboardInterrupt:
            logging.info("策略D停止")
            break
        except Exception as e:
            import traceback
            tb = traceback.format_exc()[:200]
            logging.error(f"主循环错误: {type(e).__name__}: {str(e)[:100]} | {tb}")
            time.sleep(1)

if __name__ == "__main__":
    run()
