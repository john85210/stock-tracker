#!/usr/bin/env python3
"""印出 API 回傳的欄位名稱，用來找成本欄位。"""
import json, os, requests

API_BASE = "https://finapi.scopefin.club"
USERNAME = os.environ.get("FINAPI_USERNAME", "")
PASSWORD = os.environ.get("FINAPI_PASSWORD", "")

r = requests.post(f"{API_BASE}/brkapi/user/login",
                  json={"username": USERNAME, "password": PASSWORD}, timeout=15)
token = r.json()["data"]["token"]
print("登入成功")

r2 = requests.get(f"{API_BASE}/brkapi/stock-query/list",
                  params={"symbol": "2330", "bdate": "2026-07-25", "edate": "2026-07-25"},
                  headers={"Authorization": f"Bearer {token}"}, timeout=20)
data = r2.json().get("data", [])
if not data:
    print("無資料")
    exit()

b0 = data[0]
print("\n=== broker 欄位（第一筆）===")
for k, v in b0.items():
    if k != "dailyTradesJson":
        print(f"  {k}: {v}")

trades = json.loads(b0.get("dailyTradesJson", "[]"))
if trades:
    print("\n=== dailyTradesJson 第一筆 trade 所有欄位 ===")
    for k, v in trades[0].items():
        print(f"  {k}: {v}")
else:
    print("dailyTradesJson 為空")
