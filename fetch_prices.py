#!/usr/bin/env python3
"""
fetch_prices.py
用 yfinance 在伺服器端（GitHub Actions）抓取加權指數 + 追蹤股票的每日開盤/收盤價，
存成 price_history.json，前端直接讀取這個檔案回填週報價格，不再透過瀏覽器打 Yahoo Finance
（也就不需要任何 CORS proxy）。

建議排程：每個交易日收盤後跑一次（例如台灣時間 16:40，daily_chips 之後）。
也可以用 workflow_dispatch 手動觸發做初次填充或修補資料。

用法（本機測試）：
  pip install yfinance pandas
  python fetch_prices.py

輸出格式（price_history.json）：
  {
    "TAIEX": {"2026-08-24": {"open": 24567.1, "close": 24601.3}, ...},
    "2330":  {"2026-08-24": {"open": 1105.0,  "close": 1110.0}, ...},
    ...
    "__meta": {"market": {"2330": "tse", "6147": "tse", ...}, "updated": "2026-08-30"}
  }

"__meta.market" 記錄實際抓到資料的市場別（tse/otc），前端可用來偵測/修正
data.json 裡股票的 market 欄位設錯的情況（跟舊版 backfillStockPrices 的
「自動修正市場類型」邏輯相同）。
"""

import json
import sys
from datetime import date

try:
    import yfinance as yf
    import pandas as pd
except ImportError:
    print("請先安裝套件：pip install yfinance pandas")
    sys.exit(1)

# ── 設定 ──────────────────────────────────────────────────────────────
DATA_JSON = "data.json"
OUT_JSON = "price_history.json"
LOOKBACK = "70d"  # 涵蓋前 4~5 週報酬計算所需的區間（含假日緩衝）
TAIEX_SYMBOL = "^TWII"
# ─────────────────────────────────────────────────────────────────────


def load_stocks():
    with open(DATA_JSON, encoding="utf-8") as f:
        d = json.load(f)
    return [
        s
        for s in d.get("stocks", [])
        if s.get("code") and s.get("code") != "TAIEX"
    ]


def ticker_pair(code: str, market: str):
    """回傳 (優先嘗試的 ticker, 備援 ticker)。"""
    primary = f"{code}.TWO" if market == "otc" else f"{code}.TW"
    fallback = f"{code}.TW" if market == "otc" else f"{code}.TWO"
    return primary, fallback


def extract_series(df: pd.DataFrame, ticker: str, multi: bool) -> dict:
    """從 yf.download 回傳的 DataFrame 萃取某個 ticker 的 {日期: {open, close}}。"""
    try:
        sub = df[ticker] if multi else df
    except (KeyError, Exception):
        return {}
    if sub is None or sub.empty:
        return {}
    out = {}
    for idx, row in sub.iterrows():
        o = row.get("Open")
        c = row.get("Close")
        if (o is None or pd.isna(o)) and (c is None or pd.isna(c)):
            continue
        out[idx.strftime("%Y-%m-%d")] = {
            "open": round(float(o), 2) if o is not None and not pd.isna(o) else None,
            "close": round(float(c), 2) if c is not None and not pd.isna(c) else None,
        }
    return out


def main():
    stocks = load_stocks()
    pairs = {s["code"]: ticker_pair(s["code"], s.get("market", "tse")) for s in stocks}

    all_tickers = [TAIEX_SYMBOL]
    for primary, fallback in pairs.values():
        all_tickers += [primary, fallback]
    # 去重，保持順序
    all_tickers = list(dict.fromkeys(all_tickers))

    print(f"下載 {len(all_tickers)} 個 ticker，近 {LOOKBACK}...")
    df = yf.download(
        all_tickers,
        period=LOOKBACK,
        group_by="ticker",
        auto_adjust=False,
        threads=True,
        progress=False,
    )

    multi = len(all_tickers) > 1

    result = {}
    meta_market = {}

    taiex = extract_series(df, TAIEX_SYMBOL, multi)
    if taiex:
        result["TAIEX"] = taiex
        print(f"TAIEX：{len(taiex)} 天")
    else:
        print("TAIEX 抓取失敗（無資料）", file=sys.stderr)

    ok, fail = 0, 0
    for code, (primary, fallback) in pairs.items():
        data = extract_series(df, primary, multi)
        used_market = "otc" if primary.endswith(".TWO") else "tse"
        if not data:
            data = extract_series(df, fallback, multi)
            used_market = "otc" if fallback.endswith(".TWO") else "tse"
        if data:
            result[code] = data
            meta_market[code] = used_market
            ok += 1
        else:
            print(f"{code}（{primary} / {fallback}）抓取失敗，皆無資料", file=sys.stderr)
            fail += 1

    if ok == 0:
        print("所有股票都抓取失敗，判定為異常，不寫入檔案（避免用空資料覆蓋舊檔）。", file=sys.stderr)
        sys.exit(1)

    result["__meta"] = {"market": meta_market, "updated": date.today().isoformat()}

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\n完成：成功 {ok} / 失敗 {fail}，已存至 {OUT_JSON}")


if __name__ == "__main__":
    main()
