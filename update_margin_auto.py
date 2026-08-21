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


def extract_number_from_element(soup, keyword):
  """HTMLテーブルから指定キーワード（買残/売残）の直近数値を正確に安全抽出"""
  try:
    for tag in soup.find_all(["th", "td", "span", "li"]):
      if keyword in tag.get_text():
        # 親要素または同層要素から数値のみを持つタグを探す
        parent = tag.find_parent(["tr", "div", "dl"])
        if parent:
          # カンマ区切りの純粋な数字セル（例: 39,200）を特定
          numbers = re.findall(r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b", parent.text)
          for num_str in numbers:
            clean_num = int(num_str.replace(",", ""))
            # 一般的な株数の範囲（100万株単位など、極端な10億以上の結合バグ値を除外）
            if 0 < clean_num < 1000000000:
              return clean_num
  except Exception:
    pass
  return 0


def fetch_single_margin(row):
  """1銘柄の信用残高を取得"""
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

      buy_margin = 0
      sell_margin = 0

      # テーブルのセル指定で買残・売残の数字のみを確実に取得
      for tr in soup.find_all("tr"):
        tr_text = tr.get_text()
        if "買残" in tr_text and buy_margin == 0:
          nums = re.findall(r"\b\d{1,3}(?:,\d{3})*\b", tr_text)
          valid_nums = [
              int(n.replace(",", ""))
              for n in nums
              if n.replace(",", "").isdigit()
          ]
          if valid_nums:
            buy_margin = valid_nums[0]

        if "売残" in tr_text and sell_margin == 0:
          nums = re.findall(r"\b\d{1,3}(?:,\d{3})*\b", tr_text)
          valid_nums = [
              int(n.replace(",", ""))
              for n in nums
              if n.replace(",", "").isdigit()
          ]
          if valid_nums:
            sell_margin = valid_nums[0]

      if buy_margin > 0 or sell_margin > 0:
        updated_row = dict(row)
        updated_row["margin_buy"] = buy_margin
        updated_row["margin_sell"] = sell_margin
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

  print("2. Yahoo!ファイナンスから数字セルを直接抽出中...")
  payload_list = []

  with ThreadPoolExecutor(max_workers=6) as executor:
    futures = [executor.submit(fetch_single_margin, row) for row in rows]
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

  print("3. Supabaseへ正当な一括データを更新中...")
  chunk_size = 200
  success_count = 0
  endpoint = f"{SUPABASE_URL}/rest/v1/stocks_master"

  for i in range(0, len(payload_list), chunk_size):
    chunk = payload_list[i : i + chunk_size]
    res = requests.post(endpoint, json=chunk, headers=headers, timeout=30)
    if res.status_code in [200, 201]:
      success_count += len(chunk)

  print(
      f"🎉 完了！ 計 {success_count} 件の信用残高データを正しく更新しました！"
  )


if __name__ == "__main__":
  update_supabase_parallel()
