import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

# アクセスブロック回避のためのUser-Agentリスト
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/118.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
]

def get_margin_from_yahoo(code_4digit):
    """Yahoo!ファイナンスから個別の信用残高（買残・売残）を取得"""
    url = f"https://finance.yahoo.co.jp/quote/{code_4digit}.T/margin"
    headers = {"User-Agent": random.choice(USER_AGENTS)}

    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                text = soup.get_text()

                buy_margin = 0
                sell_margin = 0

                buy_match = re.search(r'買残[^\d]*([\d,]+)', text)
                if buy_match:
                    buy_margin = int(buy_match.group(1).replace(",", ""))

                sell_match = re.search(r'売残[^\d]*([\d,]+)', text)
                if sell_match:
                    sell_margin = int(sell_match.group(1).replace(",", ""))

                return {"buy": buy_margin, "sell": sell_margin}
            elif res.status_code == 403 or res.status_code == 429:
                # アクセス制限時は数秒待機して再トライ
                time.sleep(2 * (attempt + 1))
                headers["User-Agent"] = random.choice(USER_AGENTS)
        except Exception:
            time.sleep(1)

    return None

def fetch_all_supabase_rows(headers):
    """Supabaseのデフォルト1,000件上限を回避して全銘柄を取得"""
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
            print(f"❌ Supabase全件取得エラー ({res.status_code}): {res.text}")
            break

    return all_rows

def update_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ エラー: SUPABASE設定が不足しています。")
        return

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    print("1. Supabaseから全銘柄リストを取得中（ページネーション対応）...")
    rows = fetch_all_supabase_rows(headers)
    print(f"   Supabase登録全銘柄数: {len(rows)} 件")

    print("2. Yahoo!ファイナンスから信用残高を順次取得・更新中...")
    updated_count = 0

    for idx, row in enumerate(rows):
        raw_ticker = str(row.get("Ticker") or row.get("ticker") or "")
        code_4digit = raw_ticker.replace(".T", "").strip()

        if not code_4digit.isdigit() or len(code_4digit) != 4:
            continue

        data = get_margin_from_yahoo(code_4digit)
        if data and (data["buy"] > 0 or data["sell"] > 0):
            patch_url = f"{SUPABASE_URL}/rest/v1/stocks_master?Ticker=eq.{raw_ticker}" if "Ticker" in row else f"{SUPABASE_URL}/rest/v1/stocks_master?ticker=eq.{raw_ticker}"
            payload = {
                "margin_buy": data["buy"],
                "margin_sell": data["sell"]
            }

            patch_res = requests.patch(patch_url, json=payload, headers=headers)
            if patch_res.status_code in [200, 204]:
                updated_count += 1
                if code_4digit == "2433":
                    print(f"   🎯 博報堂(2433) 更新成功: {data}")

        # アクセス間隔をランダム化 (0.3秒〜0.6秒)
        time.sleep(random.uniform(0.3, 0.6))

        if (idx + 1) % 50 == 0:
            print(f"   進捗: {idx + 1} / {len(rows)} 件完了 (更新成功: {updated_count} 件)")

    print(f"🎉 完了！ 計 {updated_count} 件の信用残高データを正確に更新しました！")

if __name__ == "__main__":
    update_supabase()
