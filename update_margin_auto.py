import os
from datetime import datetime, timedelta
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
  """J-Quants APIから直近の金曜日の日付を指定して信用取引残高を取得"""
  url = "https://api.jquants.com/v1/markets/weekly_margin_interest"
  headers = {"Authorization": f"Bearer {id_token}"}

  # 直近の金曜日から過去4週間分の日付を検索
  today = datetime.now()
  date_candidates = []
  for i in range(30):
    d = today - timedelta(days=i)
    if d.weekday() == 4:  # 金曜日
      date_candidates.append(d.strftime("%Y-%m-%d"))

  print(f"1. 検索対象の日付候補: {date_candidates[:3]}")

  data = []
  target_date_used = ""
  for date_str in date_candidates:
    print(f"   日付 '{date_str}' でJ-Quants APIを問い合わせ中...")
    params = {"date": date_str}
    res = requests.get(url, headers=headers, params=params, timeout=30)
    if res.status_code == 200:
      res_data = res.json().get("weekly_margin_interest", [])
      if res_data:
        data = res_data
        target_date_used = date_str
        print(
            f"✅ データ取得成功！ ({date_str} 時点のデータ: {len(data)} 件)"
        )
        break

  if not data:
    print(
      "⚠️ パラメータなしで全件取得を試行中..."
    )
    res = requests.get(url, headers=headers, timeout=30)
    if res.status_code == 200:
      data = res.json().get("weekly_margin_interest", [])
      print(f"   取得件数: {len(data)} 件")

  margin_dict = {}
  for item in data:
    code_raw = str(item.get("Code", ""))
    code_4digit = code_raw[:4]

    buy_total = item.get("LongOutstandingBalance", 0) or 0
    sell_total = item.get("ShortOutstandingBalance", 0) or 0

    margin_dict[code_4digit] = {
        "buy": int(buy_total),
        "sell": int(sell_total),
    }

  return margin_dict


def update_supabase_bulk(margin_data):
  """Supabaseの既存データを取得し、Upsert（一括マージ更新）で確実に保存"""
  if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ エラー: SUPABASE設定が不足しています。")
    return

  headers = {
      "apikey": SUPABASE_KEY,
      "Authorization": f"Bearer {SUPABASE_KEY}",
      "Content-Type": "application/json",
      "Prefer": "resolution=merge-duplicates",
  }

  # 1. Supabaseから現在のレコード全件を取得
  print("2. Supabaseから既存の銘柄リストを取得中...")
  get_url = f"{SUPABASE_URL}/rest/v1/stocks_master?select=*"
  res = requests.get(
      get_url,
      headers={
          "apikey": SUPABASE_KEY,
          "Authorization": f"Bearer {SUPABASE_KEY}",
      },
  )

  if res.status_code not in [200, 206]:
    print(f"❌ 銘柄取得エラー: {res.status_code} - {res.text}")
    return

  rows = res.json()
  print(f"   Supabase登録銘柄数: {len(rows)} 件")

  # 2. 更新用ペイロードの作成
  payload_list = []
  for row in rows:
    ticker_val = row.get("Ticker") or row.get("ticker")
    if not ticker_val:
      continue

    code_4digit = str(ticker_val).replace(".T", "").strip()

    if code_4digit in margin_data:
      item = margin_data[code_4digit]
      # 既存のレコードに上書きするフィールドを構成
      updated_row = dict(row)
      updated_row["margin_buy"] = item["buy"]
      updated_row["margin_sell"] = item["sell"]
      payload_list.append(updated_row)

  print(f"3. Supabaseへ一括データ更新中... ({len(payload_list)} 件)")

  if not payload_list:
    print("⚠️ 更新対象のデータが0件でした。")
    return

  # 博報堂（2433）の更新データを確認用ログ出力
  for p in payload_list:
    if "2433" in str(p.get("Ticker") or p.get("ticker")):
      print(f"   🎯 博報堂(2433)の更新内容: {p}")
      break

  # 200件ずつのチャンクでPostgREST Upsert通信
  chunk_size = 200
  success_count = 0
  endpoint = f"{SUPABASE_URL}/rest/v1/stocks_master"

  for i in range(0, len(payload_list), chunk_size):
    chunk = payload_list[i : i + chunk_size]
    res = requests.post(endpoint, json=chunk, headers=headers, timeout=30)
    if res.status_code in [200, 201]:
      success_count += len(chunk)
      print(f"   ✅ Upsert送信成功: {success_count} / {len(payload_list)} 件完了")
    else:
      print(f"   ❌ Supabase Upsert エラー ({res.status_code}): {res.text}")

  print(f"🎉 完了！ 計 {success_count} 件の信用残高データをSupabaseへ反映しました。")


if __name__ == "__main__":
  if not JQUANTS_REFRESH_TOKEN:
    print("❌ エラー: JQUANTS_REFRESH_TOKEN が設定されていません！")
  else:
    try:
      print("1. J-Quants API 認証実行中...")
      id_token = get_jquants_id_token()

      print("2. J-Quants API 信用取引データ取得中...")
      margin_data = get_margin_data_from_jquants(id_token)

      if margin_data:
        update_supabase_bulk(margin_data)
      else:
        print("⚠️ エラー: APIからデータを取得できませんでした。")
    except Exception as e:
      print(f"❌ 処理失敗: {e}")
