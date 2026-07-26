#!/usr/bin/env python3
"""
fetch_history.py  —  一次性歷史資料抓取
用法：FINAPI_USERNAME=xxx FINAPI_PASSWORD=yyy python fetch_history.py
"""
import json, os, sys, time, requests

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

def fetch_brokers(token, code):
    r = requests.get(f"{API_BASE}/brkapi/stock-query/list",
                     params={"symbol": code, "bdate": BDATE, "edate": EDATE},
                     headers={"Authorization": f"Bearer {token}"}, timeout=20)
    r.raise_for_status()
    return r.json().get("data", [])

def process(brokers):
    date_map = {}
    for broker in brokers:
        name = broker.get("branchName", "").strip()
        try:
            trades = json.loads(broker.get("dailyTradesJson", "[]"))
        except Exception:
            continue
        for t in trades:
            ds = str(t.get("date", "")).replace("-", "")
            if len(ds) != 8:
                continue
            date = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
            if date < BDATE or date > EDATE:
                continue
            net  = int(t.get("netSheets") or 0)
            cost = float(t.get("avgCost") or t.get("costPrice") or t.get("cost")
                         or broker.get("avgCost") or 0)
            if not net:
                continue
            dm = date_map.setdefault(date, {})
            e  = dm.setdefault(name, {"net": 0, "wsum": 0.0, "vsum": 0})
            e["net"]  += net
            e["wsum"] += cost * abs(net)
            e["vsum"] += abs(net)

    result = {}
    for date, bmap in date_map.items():
        rows = [[n, d["net"], round(d["wsum"]/d["vsum"], 1) if d["vsum"] else 0]
                for n, d in bmap.items()]
        buyers  = sorted([r for r in rows if r[1] > 0], key=lambda x: -x[1])[:TOP_N]
        sellers = sorted([r for r in rows if r[1] < 0], key=lambda x:  x[1])[:TOP_N]
        if buyers or sellers:
            result[date] = {"b": buyers, "s": sellers}
    return result

def main():
    if not USERNAME or not PASSWORD:
        print("請設定 FINAPI_USERNAME / FINAPI_PASSWORD")
        sys.exit(1)

    with open(DATA_JSON, encoding="utf-8") as f:
        stocks = [s for s in json.load(f).get("stocks", [])
                  if s.get("code") and s.get("group") != "index"]
    print(f"股票數：{len(stocks)}，區間：{BDATE} ~ {EDATE}")

    # 讀現有資料（若有）
    daily = {}
    if os.path.exists(OUT_JSON):
        with open(OUT_JSON, encoding="utf-8") as f:
            daily = json.load(f)

    print("登入 API...")
    token = login()
    print("登入成功\n")

    ok = err = 0
    for i, s in enumerate(stocks, 1):
        code = s["code"]
        print(f"[{i:03d}/{len(stocks)}] {code}", end="  ", flush=True)
        try:
            brokers = fetch_brokers(token, code)
            days    = process(brokers)
            if days:
                if code not in daily:
                    daily[code] = {}
                daily[code].update(days)
                print(f"{len(days)} 天有資料")
                ok += 1
            else:
                print("無資料")
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            err += 1
        time.sleep(DELAY)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(daily, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\n完成：成功 {ok} / 錯誤 {err}，已存至 {OUT_JSON}")

if __name__ == "__main__":
    main()
