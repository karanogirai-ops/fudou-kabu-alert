import os
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
JQUANTS_REFRESH_TOKEN = os.environ.get("JQUANTS_REFRESH_TOKEN", "").strip()


def get_jquants_id_token():
  """リフレッシュトークンから一時アクセス用IDトークンを取得"""
  url = f"https://api.jquants.com/v1/token/auth/refresh?refreshtoken={JQUANTS_REFRESH_TOKEN}"
  res = requests.post(url, timeout=15)
  res.raise_for_status()
  return res.json().get("idToken")


def get_margin_data_from_jquants(id_token):
  """J-Quants APIから最新の全銘柄信用取引残高を取得"""
  url = "https://api.jquants.com/v1/markets/weekly_margin_interest"
  headers = {"Authorization": f"Bearer {id_token}"}

  res = requests.get(url, headers=headers, timeout=30)
  res.raise_for_status()

  data = res.json().get("weekly_margin_interest", [])
  print(f"   J-Quantsから取得完了: {len(data)} 件")

  margin_dict = {}
  for item in data:
    code_raw = str(item.get("Code", ""))
    code_4digit = code_raw[:4]

    # J-Quants APIの標準フィールド名（買残合計・売残合計）
    buy_total = item.get("LongOutstandingBalance", 0) or 0
    sell_total = item.get("ShortOutstandingBalance", 0) or 0

    margin_dict[code_4digit] = {
        "buy": int(buy_total),
        "sell": int(sell_total),
    }

  return margin_dict


def update_supabase_directly(margin_data):
  if not SUPABASE_URL or not SUPABASE_KEY:
    print(
        "❌ エラー: SUPABASE_URL または SUPABASE_KEY が設定されていません！"
    )
    return

  headers = {
      "apikey": SUPABASE_KEY,
      "Authorization": f"Bearer {SUPABASE_KEY}",
      "Content-Type": "application/json",
  }

  print("1. Supabaseから既存の銘柄リストを取得中...")
  get_url = f"{SUPABASE_URL}/rest/v1/stocks_master?select=*"
  res = requests.get(get_url, headers=headers)

  if res.status_code not in [200, 206]:
    print(f"❌ 銘柄取得エラー: {res.status_code} - {res.text}")
    return

  rows = res.json()
  print(f"   Supabase登録銘柄数: {len(rows)} 件")

  print("2. J-Quantsデータを照合して信用残高を更新中...")

  updated_count = 0
  for row in rows:
    raw_ticker = str(row.get("Ticker") or row.get("ticker") or "")
    code_4digit = raw_ticker.replace(".T", "").strip()

    if code_4digit in margin_data:
      data_item = margin_data[code_4digit]

      patch_url = (
          f"{SUPABASE_URL}/rest/v1/stocks_master?Ticker=eq.{raw_ticker}"
          if "Ticker" in row
          else f"{SUPABASE_URL}/rest/v1/stocks_master?ticker=eq.{raw_ticker}"
      )

      payload = {
          "margin_buy": data_item["buy"],
          "margin_sell": data_item["sell"],
      }

      patch_res = requests.patch(patch_url, json=payload, headers=headers)
      if patch_res.status_code in [200, 204]:
        updated_count += 1

  print(
      f"🎉 成功！ 計 {updated_count}"
      " 件の信用残高データを公式APIデータで完璧に更新しました！"
  )


if __name__ == "__main__":
  if not JQUANTS_REFRESH_TOKEN:
    print("❌ エラー: JQUANTS_REFRESH_TOKEN が設定されていません！")
  else:
    try:
      print("1. J-Quants APIの認証を実行中...")
      id_token = get_jquants_id_token()

      print("2. 公式APIから信用取引データを取得中...")
      margin_data = get_margin_data_from_jquants(id_token)

      if margin_data:
        update_supabase_directly(margin_data)
      else:
        print("⚠️ エラー: APIデータが空でした。")
    except Exception as e:
      print(f"❌ 処理失敗: {e}")
