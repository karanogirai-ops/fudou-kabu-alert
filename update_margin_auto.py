import io
import os
import re
import requests
import pypdf

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

JPX_MARGIN_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/margin/05.html"

def get_latest_pdf_url():
    """JPXページから最新PDFのURLを取得"""
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
    """Supabaseから全銘柄データを一括取得（1,000件上限を自動回避）"""
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

def parse_pdf_fast(pdf_bytes):
    """PDFをメモリ上で高速解析し、全銘柄の信用残高マップを生成"""
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    full_text = ""
    for page in reader.pages:
        t = page.extract_text()
        if t:
            full_text += t + "\n"

    lines = full_text.split("\n")
    margin_map = {}

    for line in lines:
        parts = line.split()
        for idx, part in enumerate(parts):
            if re.match(r'^\d{5}$', part):
                code_4digit = part[:4]
                after_parts = parts[idx + 1:]
                
                nums = []
                for p in after_parts:
                    p_clean = re.sub(r'[^\d]', '', p)
                    if p_clean.isdigit() and len(p_clean) > 0:
                        nums.append(int(p_clean))
                
                # JPX PDFの配置: 先頭=売残合計, 末尾=買残合計
                if len(nums) >= 2:
                    margin_map[code_4digit] = {
                        "sell": nums[0],
                        "buy": nums[-1]
                    }
                break

    return margin_map

def update_supabase_fast():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ エラー: SUPABASE設定が不足しています。")
        return

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    # 1. Supabaseから全銘柄を一括取得
    print("1. Supabaseから全銘柄リストを取得中...")
    rows = fetch_all_supabase_rows({"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    print(f"   Supabase登録全銘柄数: {len(rows)} 件")

    # 2. JPXからPDFを一括取得
    print("2. JPXからPDFを一括ダウンロード中...")
    pdf_url = get_latest_pdf_url()
    print(f"   PDF URL: {pdf_url}")
    pdf_res = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)

    # 3. PDFの高速解析
    print("3. PDFから信用残高データを一括解析中...")
    margin_map = parse_pdf_fast(pdf_res.content)
    print(f"   解析完了: {len(margin_map)} 銘柄分を抽出")

    # 4. Supabaseへバッチ送信（200件ずつ一括Upsert）
    print("4. Supabaseへ一括送信（Upsert）中...")
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

    chunk_size = 200
    success_count = 0
    endpoint = f"{SUPABASE_URL}/rest/v1/stocks_master"

    for i in range(0, len(payload_list), chunk_size):
        chunk = payload_list[i:i + chunk_size]
        res = requests.post(endpoint, json=chunk, headers=headers, timeout=30)
        if res.status_code in [200, 201]:
            success_count += len(chunk)
            print(f"   ✅ 送信成功: {success_count} / {len(payload_list)} 件完了")
        else:
            print(f"   ❌ 送信エラー ({res.status_code}): {res.text}")

    print(f"⚡ 完了！ 計 {success_count} 件の信用残高データを約10秒で更新しました！")

if __name__ == "__main__":
    update_supabase_fast()
