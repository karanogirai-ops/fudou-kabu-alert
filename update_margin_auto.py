from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import random
import re
import time
from bs4 import BeautifulSoup
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101"
        " Firefox/120.0"
    ),
]


def fetch_single_margin(row):
  """1銘柄分の信用残高をYahoo!ファイナンスから取得"""
  raw_ticker = str(row.get("Ticker") or row.get("ticker") or "")
  code_4digit = raw_ticker.replace(".T", "").strip()

  if not code_4digit.isdigit() or len(code_4digit) != 4:
    return None

  url = f"https://finance.yahoo.co.jp/quote/{code_4digit}.T/margin"
  headers = {"User-Agent": random.choice(USER_AGENTS)}

  for attempt in range(2):
    try:
      res = requests.get(url, headers=headers, timeout=8)
      if res.status_code == 200:
        soup = BeautifulSoup(res.text, "html.parser")
        text = soup.get_text()

        buy_margin = 0
        sell_margin = 0

        buy_match = re.search(r"買残[^\d]*([\d,]+)", text)
        if buy_match:
          buy_margin = int(buy_match.group(1).replace(",", ""))

        sell_match = re.search(r"売残[^\d]*([\d,]+)", text)
        if sell_match:
          sell_margin = int(sell_match.group(1).replace(",", ""))

        if buy_margin > 0 or sell_margin > 0:
          updated_row = dict(row)
          updated_row["margin_buy"] = buy_margin
          updated_row["margin_sell"] = sell_margin
          return updated_row
        return None
      elif res.status_code in [403, 429]:
        time.sleep(1)
    except Exception:
      pass

  return None


def fetch_all_supabase_rows(headers):
  """Supabaseから全銘柄を一括取得"""
  all_rows = []
  page_size = 1000
  start = 0

  while True:
    get_headers = dict(headers)
    get_headers["Range"] = f"{start}-{start + page_size - 1}"
    get_url = f"{SUPABASE_URL}/rest/v1/stocks_master?select=*"

    res = requests.get(get_url, headers=get_headers)
    if res.status_code in [200, 206]:
      rows = res.json()
      if not rows:
        break
      all_rows.extend(rows)
      if len(rows) < page_size:
        break
      start += page_size
    else:
      break

  return all_rows


def update_supabase_parallel():
  if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ エラー: SUPABASE設定が不足しています。")
    return

  headers = {
      "apikey": SUPABASE_KEY,
      "Authorization": f"Bearer {SUPABASE_KEY}",
      "Content-Type": "application/json",
      "Prefer": "resolution=merge-duplicates",
  }

  print("1. Supabaseから全銘柄リストを取得中...")
  rows = fetch_all_supabase_rows({
      "apikey": SUPABASE_KEY,
      "Authorization": f"Bearer {SUPABASE_KEY}",
  })
  print(f"   対象銘柄数: {len(rows)} 件")

  print("2. Yahoo!ファイナンスから高速並列通信でデータ取得中...")
  payload_list = []

  # 8スレッドで並列処理（処理速度を最速化）
  with ThreadPoolExecutor(max_workers=8) as executor:
    futures = [executor.submit(fetch_single_margin, row) for row in rows]
    completed_count = 0

    for future in as_completed(futures):
      completed_count += 1
      result = future.result()
      if result:
        payload_list.append(result)

      if completed_count % 500 == 0 or completed_count == len(rows):
        print(
            f"   取得進捗: {completed_count} / {len(rows)} 件完了"
            f" (抽出成功: {len(payload_list)} 件)"
        )

  print("3. Supabaseへ一括送信（Upsert）中...")
  chunk_size = 200
  success_count = 0
  endpoint = f"{SUPABASE_URL}/rest/v1/stocks_master"

  for i in range(0, len(payload_list), chunk_size):
    chunk = payload_list[i : i + chunk_size]
    res = requests.post(endpoint, json=chunk, headers=headers, timeout=30)
    if res.status_code in [200, 201]:
      success_count += len(chunk)

  print(
      f"🎉 完了！ 計 {success_count} 件の信用残高データを高速更新しました！"
  )


if __name__ == "__main__":
  update_supabase_parallel()
