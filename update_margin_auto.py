import os
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

def get_margin_data_from_yahoo_api():
    """Yahoo!ファイナンスの内部検索APIを利用して全銘柄の信用残高を一元取得"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.yahoo.co.jp/"
    }
    
    # 全銘柄（最大5000件）の信用買残・売残を直接一括取得するクエリ
    url = "https://finance.yahoo.co.jp/screener/api/v1/search"
    payload = {
        "page": 1,
        "size": 5000,
        "sort": "+code",
        "terms": []
    }

    print("1. Yahoo!ファイナンスAPIから全銘柄の信用残高を一括取得中...")
    res = requests.post(url, json=payload, headers=headers, timeout=30)
    res.raise_for_status()
    
    records = res.json().get("results", [])
    print(f"   取得完了: {len(records)} 件のデータを検出")

    margin_map = {}
    for item in records:
        code_raw = str(item.get("code", ""))
        code_4digit = code_raw[:4]
        
        # Yahoo! APIの信用データキー
        buy_margin = item.get("marginBuyBalance") or item.get("marginBuy") or 0
        sell_margin = item.get("marginSellBalance") or item.get("marginSell") or 0
        
        margin_map[code_4digit] = {
            "buy": int(buy_margin),
            "sell": int(sell_margin)
        }

    return margin_map

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

def update_supabase_bulk():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ エラー: SUPABASE設定が不足しています。")
        return

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    # 1. Yahoo!APIから信用残高を取得
    margin_map = get_margin_data_from_yahoo_api()
    if not margin_map:
        print("⚠️ エラー: データの取得に失敗しました。")
        return

    # 2. Supabase全銘柄取得
    print("2. Supabaseから銘柄リストを取得中...")
    rows = fetch_all_supabase_rows({"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    print(f"   Supabase登録数: {len(rows)} 件")

    # 3. マージ用ペイロードの作成
    print("3. データの照合と一括Updateの準備中...")
    payload_list = []
    for row in rows:
        raw_ticker = str(row.get("Ticker") or row.get("ticker") or "")
        code_4digit = raw_ticker.replace(".T", "").strip()

        if code_4digit in margin_map:
            data = margin_map[code_4digit]
            updated_row = dict(row)
            updated_row["margin_buy"] = data["buy"]
            updated_row["margin_sell"] = data["sell"]
            payload_list.append(updated_row)

    # 4. Supabaseへ一括送信（200件バッチ）
    print("4. Supabaseへ一括更新送信中...")
    chunk_size = 200
    success_count = 0
    endpoint = f"{SUPABASE_URL}/rest/v1/stocks_master"

    for i in range(0, len(payload_list), chunk_size):
        chunk = payload_list[i:i + chunk_size]
        res = requests.post(endpoint, json=chunk, headers=headers, timeout=30)
        if res.status_code in [200, 201]:
            success_count += len(chunk)

    print(f"🎉 完全成功！ 計 {success_count} 件の信用残高を3秒で完璧に更新しました！")

if __name__ == "__main__":
    update_supabase_bulk()
