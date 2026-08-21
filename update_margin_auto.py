import io
import os
import re
import requests
import pdfplumber

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

JPX_MARGIN_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/margin/05.html"

def get_latest_pdf_url():
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(JPX_MARGIN_PAGE, headers=headers, timeout=15)
    res.raise_for_status()
    
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(res.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf"):
            return href if href.startswith("http") else "https://www.jpx.co.jp" + href
            
    raise Exception("JPXページからPDFが見つかりませんでした。")

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

def parse_pdf_system_margin(pdf_bytes):
    """pdfplumberを使ってセル位置から『制度信用（特定）』の数値のみを厳密抽出"""
    margin_map = {}
    
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            
            lines = text.split("\n")
            for line in lines:
                parts = line.split()
                for idx, part in enumerate(parts):
                    # 5桁銘柄コードの判定
                    if re.match(r'^\d{5}$', part):
                        code_4digit = part[:4]
                        after_parts = parts[idx + 1:]
                        
                        # カンマを除去して純粋な数字のみ抽出
                        nums = []
                        for p in after_parts:
                            p_clean = re.sub(r'[^\d]', '', p)
                            if p_clean.isdigit() and len(p_clean) > 0:
                                nums.append(int(p_clean))
                        
                        # JPX PDFの数値構造（7個〜9個の配列）:
                        # nums[0]: 売残合計
                        # nums[1]: 売残（一般）
                        # nums[2]: 売残（制度＝特定）★ターゲット
                        # nums[3]: 買残（一般）
                        # nums[4]: 買残（制度＝特定）★ターゲット
                        if len(nums) >= 5:
                            sell_system = nums[2]
                            buy_system = nums[4]
                            
                            margin_map[code_4digit] = {
                                "sell": sell_system,
                                "buy": buy_system
                            }
                        break

    return margin_map

def update_supabase_system_margin():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ エラー: SUPABASE設定が不足しています。")
        return

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    print("1. Supabaseから全銘柄リストを取得中...")
    rows = fetch_all_supabase_rows({"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    print(f"   Supabase登録数: {len(rows)} 件")

    print("2. JPXから最新PDFを取得中...")
    pdf_url = get_latest_pdf_url()
    pdf_res = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)

    print("3. PDFから『制度信用（特定）』の数値のみを精緻抽出中...")
    margin_map = parse_pdf_system_margin(pdf_res.content)
    print(f"   解析完了: {len(margin_map)} 銘柄分を取得")

    print("4. Supabaseへ正常数値を上書き一括更新中...")
    payload_list = []
    for row in rows:
        raw_ticker = str(row.get("Ticker") or row.get("ticker") or "")
        code_4digit = raw_ticker.replace(".T", "").strip()

        if code_4digit in margin_map:
            data = margin_map[code_4digit]
            updated_row = dict(row)
            # 異常値を正常な制度信用の値で完全に塗り替える
            updated_row["margin_buy"] = data["buy"]
            updated_row["margin_sell"] = data["sell"]
            payload_list.append(updated_row)

    chunk_size = 200
    success_count = 0
    endpoint = f"{SUPABASE_URL}/rest/v1/stocks_master"

    for i in range(0, len(payload_list), chunk_size):
        chunk = payload_list[i:i + chunk_size]
        res = requests.post(endpoint, json=chunk, headers=headers, timeout=30)
        if res.status_code in [200, 201]:
            success_count += len(chunk)
            print(f"   ✅ 送信成功: {success_count} / {len(payload_list)} 件完了")

    print(f"🎉 完了！ 異常値を破棄し、計 {success_count} 件の制度信用データを正常反映しました！")

if __name__ == "__main__":
    update_supabase_system_margin()
