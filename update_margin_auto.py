import os
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
JQUANTS_REFRESH_TOKEN = os.environ.get("JQUANTS_REFRESH_TOKEN", "").strip()


def test_jquants_auth():
  print("--- [ステップ1: J-Quants 認証テスト] ---")
  if not JQUANTS_REFRESH_TOKEN:
    print(
        "❌ FAIL: JQUANTS_REFRESH_TOKEN が GitHub Secrets"
        " に登録されていません。"
    )
    return None

  url = f"https://api.jquants.com/v1/token/auth/refresh?refreshtoken={JQUANTS_REFRESH_TOKEN}"
  res = requests.post(url, timeout=15)
  if res.status_code == 200:
    id_token = res.json().get("idToken")
    print(f"✅ SUCCESS: IDトークン取得成功 (先頭10文字: {id_token[:10]}...)")
    return id_token
  else:
    print(
        f"❌ FAIL: 認証エラー (ステータスコード: {res.status_code}) - {res.text}"
    )
    return None


def test_jquants_fetch(id_token):
  print("\n--- [ステップ2: J-Quants データ取得テスト] ---")
  url = "https://api.jquants.com/v1/markets/weekly_margin_interest"
  headers = {"Authorization": f"Bearer {id_token}"}

  res = requests.get(url, headers=headers, timeout=30)
  if res.status_code != 200:
    print(
        f"❌ FAIL: API取得エラー (ステータスコード: {res.status_code}) -"
        f" {res.text}"
    )
    return None

  data = res.json().get("weekly_margin_interest", [])
  print(f"✅ SUCCESS: データ取得成功 ({len(data)} 件のレコード)")

  if data:
    sample = data[0]
    print(f"   サンプルデータ (1件目): {sample}")

  margin_dict = {}
  for item in data:
    code_raw = str(item.get("Code", ""))
    code_4digit = code_raw[:4]
    buy_total = item.get("LongOutstandingBalance", 0) or 0
    sell_total = item.get("ShortOutstandingBalance", 0) or 0
    margin_dict[code_4digit] = {"buy": int(buy_total), "sell": int(sell_total)}

  # 博報堂（2433）のデータをピンポイント確認
  if "2433" in margin_dict:
    print(f"   🎯 博報堂(2433)のAPI取得値: {margin_dict['2433']}")
  else:
    print("   ⚠️ 博報堂(2433)がAPI取得データに含まれていません。")

  return margin_dict


def test_supabase_patch(margin_data):
  print("\n--- [ステップ3: Supabase 更新テスト] ---")
  if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ FAIL: SUPABASE_URL または SUPABASE_KEY が不足しています。")
    return

  headers = {
      "apikey": SUPABASE_KEY,
      "Authorization": f"Bearer {SUPABASE_KEY}",
      "Content-Type": "application/json",
  }

  get_url = f"{SUPABASE_URL}/rest/v1/stocks_master?select=*"
  res = requests.get(get_url, headers=headers)
  if res.status_code not in [200, 206]:
    print(
        f"❌ FAIL: Supabase読み込みエラー ({res.status_code}) - {res.text}"
    )
    return

  rows = res.json()
  print(f"✅ Supabase取得成功 ({len(rows)} 銘柄)")

  # 博報堂（2433）単体でPATCH更新を直接テスト
  hakuhodo_row = None
  for r in rows:
    raw_t = str(r.get("Ticker") or r.get("ticker") or "")
    if "2433" in raw_t:
      hakuhodo_row = r
      break

  if not hakuhodo_row:
    print("❌ FAIL: Supabase内に '2433' の銘柄が見つかりませんでした。")
    return

  raw_ticker = str(hakuhodo_row.get("Ticker") or hakuhodo_row.get("ticker"))
  print(f"   対象銘柄キー: {raw_ticker}")

  if "2433" in margin_data:
    item = margin_data["2433"]
    patch_url = (
        f"{SUPABASE_URL}/rest/v1/stocks_master?Ticker=eq.{raw_ticker}"
        if "Ticker" in hakuhodo_row
        else f"{SUPABASE_URL}/rest/v1/stocks_master?ticker=eq.{raw_ticker}"
    )
    payload = {"margin_buy": item["buy"], "margin_sell": item["sell"]}

    patch_res = requests.patch(patch_url, json=payload, headers=headers)
    print(
        f"   PATCH送信ステータス: {patch_res.status_code} (レスポンス:"
        f" '{patch_res.text}')"
    )
    if patch_res.status_code in [200, 204]:
      print(
          f"✅ SUCCESS: 博報堂(2433)を更新しました！ (買残: {item['buy']},"
          f" 売残: {item['sell']})"
      )
    else:
      print("❌ FAIL: PATCH更新に失敗しました。")


if __name__ == "__main__":
  id_token = test_jquants_auth()
  if id_token:
    margin_data = test_jquants_fetch(id_token)
    if margin_data:
      test_supabase_patch(margin_data)
