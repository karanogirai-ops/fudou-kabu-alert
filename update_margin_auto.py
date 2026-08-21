import os
import re
import time
from bs4 import BeautifulSoup
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()


def get_margin_from_yahoo(code_4digit):
  """Yahoo!ファイナンスから個別の信用残高（買残・売残）を取得"""
  url = f"https://finance.yahoo.co.jp/quote/{code_4digit}.T/margin"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
          " like Gecko) Chrome/115.0.0.0 Safari/537.36"
      )
  }

  try:
    res = requests.get(url, headers=headers, timeout=10)
    if res.status_code != 200:
      return None

    soup = BeautifulSoup(res.text, "html.parser")
    text = soup.get_text()

    # ページ内の数字パターンから買残・売残を抽出
    # 通常 Yahoo!ファイナンスでは「信用買残」「信用売残」のラベルの直後に数字が入る
    buy_margin = 0
    sell_margin = 0

    # 1. 買残の抽出
    buy_match = re.search(r"買残[^\d]*([\d,]+)", text)
    if buy_match:
      buy_margin = int(buy_match.group(1).replace(",", ""))

    # 2. 売残の抽出
    sell_match = re.search(r"売残[^\d]*([\d,]+)", text)
    if sell_match:
      sell_margin = int(sell_match.group(1).replace(",", ""))

    return {"buy": buy_margin, "sell": sell_margin}
  except Exception:
    return None


def update_supabase():
  if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ エラー: SUPABASE設定が不足しています。")
    return

  headers = {
      "apikey": SUPABASE_KEY,
      "Authorization": f"Bearer {SUPABASE_KEY}",
      "Content-Type": "application/json",
  }

  print("1. Supabaseから銘柄リストを取得中...")
  get_url = f"{SUPABASE_URL}/rest/v1/stocks_master?select=*"
  res = requests.get(get_url, headers=headers)

  if res.status_code not in [200, 206]:
    print(f"❌ 銘柄取得エラー: {res.status_code} - {res.text}")
    return

  rows = res.json()
  print(f"   Supabase登録銘柄数: {len(rows)} 件")

  print("2. Yahoo!ファイナンスから信用残高を順次取得・更新中...")
  updated_count = 0

  for idx, row in enumerate(rows):
    raw_ticker = str(row.get("Ticker") or row.get("ticker") or "")
    code_4digit = raw_ticker.replace(".T", "").strip()

    if not code_4digit.isdigit() or len(code_4digit) != 4:
      continue

    # Yahooから取得
    data = get_margin_from_yahoo(code_4digit)
    if data and (data["buy"] > 0 or data["sell"] > 0):
      patch_url = (
          f"{SUPABASE_URL}/rest/v1/stocks_master?Ticker=eq.{raw_ticker}"
          if "Ticker" in row
          else f"{SUPABASE_URL}/rest/v1/stocks_master?ticker=eq.{raw_ticker}"
      )

      payload = {"margin_buy": data["buy"], "margin_sell": data["sell"]}

      patch_res = requests.patch(patch_url, json=payload, headers=headers)
      if patch_res.status_code in [200, 204]:
        updated_count += 1
        if code_4digit == "2433":
          print(f"   🎯 博報堂(2433) 更新成功: {data}")

    # アクセスブロック防止のための間隔設定（0.2秒）
    time.sleep(0.2)

    if (idx + 1) % 50 == 0:
      print(f"   進捗: {idx + 1} / {len(rows)} 件完了 (更新成功: {updated_count} 件)")

  print(f"🎉 完了！ 計 {updated_count} 件の信用残高データを正確に更新しました！")


if __name__ == "__main__":
  update_supabase()
