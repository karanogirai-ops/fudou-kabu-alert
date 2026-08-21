from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import random
import re
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
]


def fetch_yahoo_clean_margin(row):
  """Yahoo!ファイナンスのHTMLから純粋な株数（買残・売残）を取り出す"""
  raw_ticker = str(row.get("Ticker") or row.get("ticker") or "")
  code_4digit = raw_ticker.replace(".T", "").strip()

  if not code_4digit.isdigit() or len(code_4digit) != 4:
    return None

  url = f"https://finance.yahoo.co.jp/quote/{code_4digit}.T/margin"
  headers = {"User-Agent": random.choice(USER_AGENTS)}

  try:
    res = requests.get(url, headers=headers, timeout=8)
    if res.status_code == 200:
      soup = BeautifulSoup(res.text, "html.parser")

      buy_val = 0
      sell_val = 0

      # HTML内の「信用買残」「信用売残」のテキストの隣にある数字を検索
      for span in soup.find_all(["span", "td", "li"]):
        text = span.get_text().strip()

        # 買残の取得
        if "買残" in text and buy_val == 0:
          parent = span.find_parent(["tr", "li", "div", "dl"])
          if parent:
            # カンマ付き数字をすべて抽出
            nums = re.findall(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b", parent.text)
            clean_nums = [
                int(n.replace(",", "")) for n in nums if n.replace(",", "").isdigit()
            ]
            # 100以上（株数として自然な数値）を採用
            valid = [n for n in clean_nums if n >= 100]
            if valid:
              buy_val = valid[0]

        # 売残の取得
        if "売残" in text and sell_val == 0:
          parent = span.find_parent(["tr", "li", "div", "dl"])
          if parent:
            nums = re.findall(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b", parent.text)
            clean_nums = [
                int(n.replace(",", "")) for n in nums if n.replace(",", "").isdigit()
            ]
            valid = [n for n in clean_nums if n >= 100]
            if valid:
              sell_val = valid[0]

      if buy_val > 0 or sell_val > 0:
        updated_row = dict(row)
        updated_row["margin_buy"] = buy_val
        updated_row["margin_sell"] = sell_val

        if code_4digit == "2433":
          print(
              f"   🎯 【確認】博報堂(2433) 抽出値: 買残={buy_val},"
              f" 売残={sell_val}"
          )

        return updated_row
  except Exception:
    pass

  return None


def fetch_all_supabase_rows(headers):
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


def update_supabase_force():
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

  print("2. Yahoo!ファイナンスから1株単位の正しい数値を精密抽出中...")
  payload_list = []

  # 並列数を少し落として（4スレッド）超確実に取得
  with ThreadPoolExecutor(max_workers=4) as executor:
    futures = [executor.submit(fetch_yahoo_clean_margin, row) for row in rows]
    completed_count = 0

    for future in as_completed(futures):
      completed_count += 1
      result = future.result()
      if result:
        payload_list.append(result)

      if completed_count % 500 == 0 or completed_count == len(rows):
        print(
            f"   進捗: {completed_count} / {len(rows)} 件完了"
            f" (抽出成功: {len(payload_list)} 件)"
        )

  print("3. Supabaseへ正常な数値（1株単位）で上書き書き込み中...")
  chunk_size = 200
  success_count = 0
  endpoint = f"{SUPABASE_URL}/rest/v1/stocks_master"

  for i in range(0, len(payload_list), chunk_size):
    chunk = payload_list[i : i + chunk_size]
    res = requests.post(endpoint, json=chunk, headers=headers, timeout=30)
    if res.status_code in [200, 201]:
      success_count += len(chunk)

  print(
      f"🎉 完了！ 計 {success_count} 件のデータを1株単位の正常な値で上書き更新しました！"
  )


if __name__ == "__main__":
  update_supabase_force()
