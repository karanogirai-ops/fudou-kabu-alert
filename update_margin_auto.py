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
]


def fetch_margin_carefully(code_4digit):
  """Yahoo!ファイナンスから1銘柄ずつ確実に買残・売残の株数を解析・抽出"""
  url = f"https://finance.yahoo.co.jp/quote/{code_4digit}.T/margin"
  headers = {"User-Agent": random.choice(USER_AGENTS)}

  try:
    res = requests.get(url, headers=headers, timeout=10)
    if res.status_code != 200:
      return None

    soup = BeautifulSoup(res.text, "html.parser")

    buy_val = 0
    sell_val = 0

    # Yahoo!ファイナンスのテーブル行(tr)または定義リスト(dl/dt/dd)を巡回
    # 「買残」「売残」のラベルを見つけたら、その対になる数値を抽出
    for element in soup.find_all(["tr", "dl", "div"]):
      text = element.get_text()

      if "買残" in text and buy_val == 0:
        # 数字とカンマのみを取り出す
        matches = re.findall(r"[\d,]+", text)
        for m in matches:
          clean_m = m.replace(",", "")
          if clean_m.isdigit() and len(clean_m) >= 2:  # 数値として成立するもの
            val = int(clean_m)
            # 銘柄コード自体(例:2433)を誤抽出しないよう配慮
            if val != int(code_4digit):
              buy_val = val
              break

      if "売残" in text and sell_val == 0:
        matches = re.findall(r"[\d,]+", text)
        for m in matches:
          clean_m = m.replace(",", "")
          if clean_m.isdigit() and len(clean_m) >= 2:
            val = int(clean_m)
            if val != int(code_4digit):
              sell_val = val
              break

    if buy_val > 0 or sell_val > 0:
      return {"buy": buy_val, "sell": sell_val}

  except Exception:
    pass

  return None


def fetch_all_supabase_rows(headers):
  """Supabaseから全銘柄リストを取得"""
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


def update_supabase_one_by_one():
  if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ エラー: SUPABASE設定が不足しています。")
    return

  headers = {
      "apikey": SUPABASE_KEY,
      "Authorization": f"Bearer {SUPABASE_KEY}",
      "Content-Type": "application/json",
  }

  print("1. Supabaseから全銘柄リストを取得中...")
  rows = fetch_all_supabase_rows({
      "apikey": SUPABASE_KEY,
      "Authorization": f"Bearer {SUPABASE_KEY}",
  })
  print(f"   対象銘柄数: {len(rows)} 件")

  print("2. 1銘柄ずつ丁寧にデータを取得・書き込み中...")
  updated_count = 0

  for idx, row in enumerate(rows):
    raw_ticker = str(row.get("Ticker") or row.get("ticker") or "")
    code_4digit = raw_ticker.replace(".T", "").strip()

    if not code_4digit.isdigit() or len(code_4digit) != 4:
      continue

    # 丁寧に1銘柄ずつ取得
    margin_data = fetch_margin_carefully(code_4digit)

    if margin_data:
      patch_url = (
          f"{SUPABASE_URL}/rest/v1/stocks_master?Ticker=eq.{raw_ticker}"
          if "Ticker" in row
          else f"{SUPABASE_URL}/rest/v1/stocks_master?ticker=eq.{raw_ticker}"
      )

      payload = {
          "margin_buy": margin_data["buy"],
          "margin_sell": margin_data["sell"],
      }

      patch_res = requests.patch(patch_url, json=payload, headers=headers)
      if patch_res.status_code in [200, 204]:
        updated_count += 1
        if code_4digit == "2433":
          print(f"   🎯 【更新成功】博報堂(2433): {margin_data}")

    # サーバー負荷防止のため少し間隔を空ける (0.2秒)
    time.sleep(0.2)

    if (idx + 1) % 100 == 0 or (idx + 1) == len(rows):
      print(
          f"   進捗: {idx + 1} / {len(rows)} 件完了 (更新成功: {updated_count} 件)"
      )

  print(
      f"🎉 完了！ 計 {updated_count} 件のデータを1株単位の正しい数値で更新しました！"
  )


if __name__ == "__main__":
  update_supabase_one_by_one()
