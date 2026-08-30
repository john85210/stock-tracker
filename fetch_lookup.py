#!/usr/bin/env python3
"""
fetch_lookup.py
從證交所 (TWSE) / 櫃買中心 (TPEx) OpenAPI 抓取「公司名稱 → 代號/市場」對照表，
存成 stock_lookup.json，供前端 Excel 匯入時查代號使用。

這支 script 在 GitHub Actions（伺服器端）執行，不會有瀏覽器 CORS 的問題，
不需要任何 CORS proxy。建議排程每週跑一次（代號變動不快），
也可以用 workflow_dispatch 手動觸發。

用法（本機測試）：
  python fetch_lookup.py

輸出格式：
  {
    "ts": 1735600000000,
    "map": {
      "台積電": {"code": "2330", "market": "tse"},
      "頎邦":   {"code": "6147", "market": "tse"},
      ...
    }
  }
"""

import json
import sys
import time

try:
    import requests
except ImportError:
    print("請先安裝 requests：pip install requests")
    sys.exit(1)

# ── 設定 ──────────────────────────────────────────────────────────────
# 上市：公司基本資料（含公司代號/名稱/簡稱）
TSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
# 上櫃：公司基本資料（結構與 TSE 相同），失敗則退回每日收盤行情端點
OTC_URLS = [
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
    "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
]
OUT_JSON = "stock_lookup.json"
MIN_EXPECTED = 100  # 少於這個數字視為抓取失敗，避免用壞資料覆蓋舊檔
# ─────────────────────────────────────────────────────────────────────

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-tracker-bot/1.0)"}


def fetch_json(url: str):
    resp = requests.get(url, timeout=20, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def is_code(s: str) -> bool:
    return bool(s) and s.isdigit() and 4 <= len(s) <= 6


def load_tse(m: dict):
    try:
        data = fetch_json(TSE_URL)
    except Exception as e:
        print(f"[TSE] 抓取失敗：{e}", file=sys.stderr)
        return
    if not isinstance(data, list):
        print("[TSE] 回傳格式不是陣列，略過", file=sys.stderr)
        return
    for item in data:
        code = str(item.get("公司代號") or item.get("Code") or "").strip()
        name = str(item.get("公司簡稱") or item.get("公司名稱") or item.get("Name") or "").strip()
        if is_code(code) and name:
            m[name] = {"code": code, "market": "tse"}
    print(f"[TSE] 累積 {len(m)} 檔")


def load_otc(m: dict):
    before = len(m)
    for url in OTC_URLS:
        try:
            data = fetch_json(url)
        except Exception as e:
            print(f"[OTC] {url} 抓取失敗：{e}", file=sys.stderr)
            continue
        if not isinstance(data, list) or len(data) == 0:
            print(f"[OTC] {url} 回傳空資料，略過", file=sys.stderr)
            continue
        added = 0
        for item in data:
            code = str(
                item.get("公司代號")
                or item.get("SecuritiesCompanyCode")
                or item.get("Code")
                or ""
            ).strip()
            name = str(
                item.get("公司簡稱")
                or item.get("公司名稱")
                or item.get("CompanyName")
                or item.get("Name")
                or ""
            ).strip()
            if is_code(code) and name and name not in m:
                m[name] = {"code": code, "market": "otc"}
                added += 1
        if added > 0:
            print(f"[OTC] {url} 新增 {added} 檔")
            break  # 成功一個來源就好，不用再試下一個
    print(f"[OTC] 本次新增 {len(m) - before} 檔")


def main():
    m: dict = {}
    load_tse(m)
    load_otc(m)

    total = len(m)
    if total < MIN_EXPECTED:
        print(f"總數只有 {total} 檔，低於門檻 {MIN_EXPECTED}，判定為抓取異常，不寫入檔案。", file=sys.stderr)
        sys.exit(1)

    payload = {"ts": int(time.time() * 1000), "map": m}
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    print(f"完成，共 {total} 檔，已存至 {OUT_JSON}")


if __name__ == "__main__":
    main()
