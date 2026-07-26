#!/usr/bin/env python3
"""
fetch_history.py  —  一次性歷史資料抓取
逐日查詢每支股票，同時抓籌碼與當日收盤價。
用法：FINAPI_USERNAME=xxx FINAPI_PASSWORD=yyy python fetch_history.py
"""
import json, os, sys, time, requests
from datetime import date, timedelta

API_BASE  = "https://finapi.scopefin.club"
USERNAME  = os.environ.get("FINAPI_USERNAME", "")
PASSWORD  = os.environ.get("FINAPI_PASSWORD", "")
BDATE     = "2026-06-30"
EDATE     = "2026-07-25"
TOP_N     = 20
DELAY     = 0.3
DATA_JSON = "data.json"
OUT_JSON  = "daily_chips.json"


def login():
    r = requests.post(f"{API_BASE}/brkapi/user/login",
                      json={"username": USERNAME, "password": PASSWORD}, timeout=15)
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 200:
        raise RuntimeError(f"Login failed: {d}")
    return d["data"]["token"]


def trading_days(bdate_str, edate_str):
    """產生區間內所有交易日（週一至週五）"""
    days = []
    d = date.fromisoformat(bdate_str)
    end = date.fromisoformat(edate_str)
    while d <= end:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days


def fetch_day(token, code, date_str):
    """查單日籌碼，回傳 (price, brokers_list)"""
    r = requests.get(f"{API_BASE}/brkapi/stock-query/list",
                     params={"symbol": code, "bdate": date_str, "edate": date_str},
                     headers={"Authorization": f"Bearer {token}"}, timeout=20)
    r.raise_for_status()
    brokers = r.json().get("data", [])
    return brokers


def process_day(brokers, date_str):
    """從 broker 列表萃取當日籌碼與收盤價"""
    if not brokers:
        return None

    price = brokers[0].get("price") or None

    agg = {}
    for broker in brokers:
        name = broker.get("branchName", "").strip()
        if not name:
            continue
        cost = float(broker.get("cost") or 0)
        try:
            trades = json.loads(broker.get("dailyTradesJson", "[]"))
        except Exception:
            continue
        date_nodash = date_str.replace("-", "")
        for t in trades:
            if str(t.get("date", "")).replace("-", "") != date_nodash:
                continue
            net = int(t.get("netSheets") or 0)
            if not net:
                continue
            e = agg.setdefault(name, {"net": 0, "wsum": 0.0, "vsum": 0})
            e["net"]  += net
            e["wsum"] += cost * abs(net)
            e["vsum"] += abs(net)

    rows = [[n, d["net"], round(d["wsum"] / d["vsum"], 1) if d["vsum"] else 0]
            for n, d in agg.items()]
    buyers  = sorted([r for r in rows if r[1] > 0], key=lambda x: -x[1])[:TOP_N]
    sellers = sorted([r for r in rows if r[1] < 0], key=lambda x:  x[1])[:TOP_N]

    if not buyers and not sellers:
        return None

    result = {"b": buyers, "s": sellers}
    if price is not None:
        result["price"] = float(price)
    return result


def main():
    if not USERNAME or not PASSWORD:
        print("請設定 FINAPI_USERNAME / FINAPI_PASSWORD")
        sys.exit(1)

    with open(DATA_JSON, encoding="utf-8") as f:
        stocks = [s for s in json.load(f).get("stocks", [])
                  if s.get("code") and s.get("group") != "index"]

    days = trading_days(BDATE, EDATE)
    print(f"股票數：{len(stocks)}，交易日：{len(days)} 天（{BDATE} ~ {EDATE}）")

    daily = {}
    if os.path.exists(OUT_JSON):
        with open(OUT_JSON, encoding="utf-8") as f:
            daily = json.load(f)

    print("登入 API...")
    token = login()
    print("登入成功\n")

    ok = err = skip = 0
    total = len(stocks) * len(days)
    idx = 0

    for s in stocks:
        code = s["code"]
        for day in days:
            idx += 1
            print(f"[{idx:04d}/{total}] {code} {day}", end="  ", flush=True)
            try:
                brokers  = fetch_day(token, code, day)
                day_data = process_day(brokers, day)
                if day_data:
                    daily.setdefault(code, {})[day] = day_data
                    price_str = f"price={day_data.get('price', '-')}"
                    print(f"買{len(day_data['b'])} 賣{len(day_data['s'])} {price_str}")
                    ok += 1
                else:
                    print("無資料")
                    skip += 1
            except Exception as e:
                print(f"ERROR: {e}", file=sys.stderr)
                err += 1
            time.sleep(DELAY)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(daily, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\n完成：有資料 {ok} / 無資料 {skip} / 錯誤 {err}，已存至 {OUT_JSON}")


if __name__ == "__main__":
    main()
