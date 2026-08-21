import os
import re
import requests
from bs4 import BeautifulSoup
import pypdf

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

JPX_MARGIN_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/margin/05.html"

def get_latest_pdf_url():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    res = requests.get(JPX_MARGIN_PAGE, headers=headers, timeout=15)
    res.raise_for_status()
    
    soup = BeautifulSoup(res.text, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf"):
            return href if href.startswith("http") else "https://www.jpx.co.jp" + href
            
    raise Exception("JPXのページからPDFリンクが見つかりませんでした。")

def parse_margin_pdf(pdf_path):
    reader = pypdf.PdfReader(pdf_path)
    extracted_data = []
    
    full_text = ""
    for page in reader.pages:
        text = page.extract_text()
        if text:
            full_text += text + "\n"
            
    lines = full_text.split("\n")
    
    for line in lines:
        parts = line.split()
        for idx, part in enumerate(parts):
            if re.match(r'^\d{5}$', part):
                code_raw = part[:4] + ".T"
                
                after_parts = parts[idx + 1:]
                clean_nums = []
                for p in after_parts:
                    p_clean = p.replace(',', '').replace('▲', '').strip()
                    if p_clean.isdigit():
                        clean_nums.append(int(p_clean))
                
                sell_margin = 0
                buy_margin = 0
                
                if len(clean_nums) >= 5:
                    sell_margin = clean_nums[0]
                    buy_margin = clean_nums[4]
                elif len(clean_nums) >= 2:
                    sell_margin = clean_nums[0]
                    buy_margin = clean_nums[1]
                else:
                    break
                
                # 有効なデータのみ抽出
                if sell_margin > 0 or buy_margin > 0:
                    extracted_data.append({
                        "Ticker": code_raw,
                        "ticker": code_raw,
                        "margin_sell": sell_margin,
                        "margin_buy": buy_margin
                    })
                break
                
    return extracted_data

def update_supabase(data):
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ エラー: SUPABASE_URL または SUPABASE_KEY が環境変数に設定されていません！")
        return

    endpoint = f"{SUPABASE_URL}/rest/v1/stocks_master"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    
    # 送信サンプルをログ出力
    print(f"📊 Supabaseへ送信する最初の3件のデータサンプル:")
    print(data[:3])

    chunk_size = 200
    success_count = 0
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        res = requests.post(endpoint, json=chunk, headers=headers, timeout=15)
        if res.status_code in [200, 201]:
            success_count += len(chunk)
            print(f"✅ 送信成功: {success_count} / {len(data)} 件完了")
        else:
            print(f"❌ Supabase送信エラー ({res.status_code}): {res.text}")

if __name__ == "__main__":
    print("1. JPXから最新PDFのURLを取得中...")
    pdf_url = get_latest_pdf_url()
    print(f"   URL検出: {pdf_url}")
    
    print("2. PDFをダウンロード中...")
    pdf_res = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    with open("latest_margin.pdf", "wb") as f:
        f.write(pdf_res.content)
        
    print("3. PDFから信用データを解析中...")
    margin_data = parse_margin_pdf("latest_margin.pdf")
    print(f"   抽出完了: {len(margin_data)} 銘柄 (残高あり銘柄数)")
    
    if margin_data:
        print("4. Supabaseへデータを送信中...")
        update_supabase(margin_data)
        print("🎉 処理が終了しました。")
    else:
        print("⚠️ エラー: PDFから信用残高データを抽出できませんでした。")
