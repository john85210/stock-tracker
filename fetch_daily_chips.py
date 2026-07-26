#!/usr/bin/env python3
"""
fetch_daily_chips.py
每日自動抓取分點籌碼，更新 daily_chips.json

daily_chips.json 結構：
{
  "2330": {
    "2026-07-25": {
      "b": [["分點名", 淨張, 均成本], ...],  # 前20大買超，淨張降冪
      "s": [["分點名", 淨張, 均成本], ...]   # 前20大賣超，淨張升冪（負值）
    }
  }
}

使用方式（本機測試）：
  FINAPI_USERNAME=ChiChu01 FINAPI_PASSWORD=111111 python fetch_daily_chips.py

GitHub Actions 透過 secrets 注入 FINAPI_USERNAME / FINAPI_PASSWORD。
"""

import json
import os
import sys
import time
from datetime import date, timedelta

try:
    import requests
except ImportError:
    print("請先安裝 requests：pip install requests")
    sys.exit(1)

# ── 設定 ──────────────────────────────────────────────────────────────
API_BASE       = "https://finapi.scopefin.club"
USERNAME       = os.environ.get("FINAPI_USERNAME", "")
PASSWORD       = os.environ.get("FINAPI_PASSWORD", "")
DATA_JSON      = "data.json"
DAILY_JSON     = "daily_chips.json"
KEEP_DAYS      = 35   # 保留近 35 天，超過自動清除
REQUEST_DELAY  = 0.3  # 每次請求間隔（秒），避免觸發限流
TOP_N          = 20   # 每日買/賣超各取前 N 大分點
# ─────────────────────────────────────────────────────────────────────


def login() -> str:
    """登入 API，回傳 token。"""
    resp = requests.post(
        f"{API_BASE}/brkapi/user/login",
        json={"username": USERNAME, "password": PASSWORD},
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 200:
        raise RuntimeError(f"登入失敗：{body}")
    return body["data"]["token"]


def fetch_brokers(token: str, code: str, date_str: str) -> list:
    """
    取得指定股票、指定日期的所有分點資料列表。
    date_str 格式：YYYY-MM-DD
    """
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(
        f"{API_BASE}/brkapi/stock-query/list",
        params={"symbol": code, "bdate": date_str, "edate": date_str},
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 200:
        return []
    return body.get("data", [])


def process_day(brokers: list, target_date: str) -> dict:
    """
    從 broker 列表中提取 target_date 當天的買超/賣超資料。
    回傳 {"b": [[name, net, cost], ...], "s": [[name, net, cost], ...]}
    """
    date_nodash = target_date.replace("-", "")   # "20260725"
    aggregated: dict[str, dict] = {}

    for broker in brokers:
        name = broker.get("branchName", "").strip()
        if not name:
            continue

        raw = broker.get("dailyTradesJson", "[]")
        try:
            trades = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            continue

        for t in trades:
            # API 日期可能是 "20260725" 或 "2026-07-25"
            t_date = str(t.get("date", "")).replace("-", "")
            if t_date != date_nodash:
                continue

            net = t.get("netSheets", 0)
            # 嘗試多種成本欄位名稱
            cost = (
                t.get("avgCost")
                or t.get("costPrice")
                or t.get("cost")
                or broker.get("avgCost")
                or 0
            )
            try:
                net  = int(net)
                cost = float(cost)
            except (TypeError, ValueError):
                net  = 0
                cost = 0.0

            if net == 0:
                continue

            if name not in aggregated:
                aggregated[name] = {"net": 0, "wsum": 0.0, "vsum": 0}
            aggregated[name]["net"]  += net
            aggregated[name]["wsum"] += cost * abs(net)
            aggregated[name]["vsum"] += abs(net)

    rows = []
    for name, d in aggregated.items():
        avg_cost = round(d["wsum"] / d["vsum"], 2) if d["vsum"] > 0 else 0.0
        rows.append([name, d["net"], avg_cost])

    buyers  = sorted([r for r in rows if r[1] > 0], key=lambda x: -x[1])[:TOP_N]
    sellers = sorted([r for r in rows if r[1] < 0], key=lambda x:  x[1])[:TOP_N]

    return {"b": buyers, "s": sellers}


def prune_old(daily: dict, keep_days: int = KEEP_DAYS) -> dict:
    """移除超過 keep_days 天的舊資料。"""
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    for code in daily:
        daily[code] = {d: v for d, v in daily[code].items() if d >= cutoff}
    return daily


def main():
    today = date.today()

    # 週末跳過（0=週一 … 6=週日）
    if today.weekday() >= 5:
        print(f"今日 {today.isoformat()} 為週末，跳過。")
        return

    today_str = today.isoformat()

    if not USERNAME or not PASSWORD:
        print("請設定環境變數 FINAPI_USERNAME 和 FINAPI_PASSWORD")
        sys.exit(1)

    # ── 讀取股票清單 ──
    with open(DATA_JSON, "r", encoding="utf-8") as f:
        app_data = json.load(f)
    stocks = [s for s in app_data.get("stocks", []) if s.get("code")]
    print(f"共 {len(stocks)} 檔股票，目標日期：{today_str}")

    # ── 讀取現有 daily_chips.json ──
    if os.path.exists(DAILY_JSON):
        with open(DAILY_JSON, "r", encoding="utf-8") as f:
            daily = json.load(f)
    else:
        daily = {}

    # ── 登入 ──
    print("登入 API...", flush=True)
    token = login()
    print("登入成功。\n")

    # ── 逐檔抓取 ──
    success, empty, errors = 0, 0, 0
    for i, stock in enumerate(stocks, 1):
        code = stock["code"]
        name = stock.get("name", "")
        print(f"[{i:02d}/{len(stocks)}] {code} {name}", end="  ", flush=True)
        try:
            brokers  = fetch_brokers(token, code, today_str)
            day_data = process_day(brokers, today_str)

            if day_data["b"] or day_data["s"]:
                daily.setdefault(code, {})[today_str] = day_data
                print(f"買超 {len(day_data['b'])} 家 / 賣超 {len(day_data['s'])} 家")
                success += 1
            else:
                print("無交易資料")
                empty += 1
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            errors += 1

        time.sleep(REQUEST_DELAY)

    # ── 清理舊資料 ──
    daily = prune_old(daily)

    # ── 寫回檔案 ──
    with open(DAILY_JSON, "w", encoding="utf-8") as f:
        json.dump(daily, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\n完成：成功 {success} / 無資料 {empty} / 錯誤 {errors}")
    print(f"已儲存至 {DAILY_JSON}")

    if errors > 0:
        sys.exit(1)  # 讓 Actions 標記為失敗


if __name__ == "__main__":
    main()
