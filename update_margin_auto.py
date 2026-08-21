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
    extracted_dict = {}
    
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
                code_4digit = part[:4]
                
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
                
                # 4桁コードをキーとして保持
                extracted_dict[code_4digit] = {
                    "sell": sell_margin,
                    "buy": buy_margin
                }
                break
                
    return extracted_dict

def update_supabase_directly(pdf_data):
    """既存のstocks_masterの全行を取得し、Tickerに合わせてPATCH（個別に確実更新）"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ エラー: SUPABASE_URL または SUPABASE_KEY が設定されていません！")
        return

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    # 1. 既存の全銘柄の Ticker / ticker を取得
    print("1. Supabaseから既存の銘柄リストを取得中...")
    get_url = f"{SUPABASE_URL}/rest/v1/stocks_master?select=*"
    res = requests.get(get_url, headers=headers)
    
    if res.status_code not in [200, 206]:
        print(f"❌ 銘柄取得エラー: {res.status_code} - {res.text}")
        return

    rows = res.json()
    print(f"   Supabase登録銘柄数: {len(rows)} 件")

    # 2. 1行ずつマッチングして更新（100件ずつ並列処理）
    print("2. 信用データを照合して個別UPDATE（確実上書き）中...")
    
    updated_count = 0
    for row in rows:
        # Tickerまたはtickerから4桁コードを取り出す (例: "1301.T" -> "1301", "1301" -> "1301")
        raw_ticker = str(row.get("Ticker") or row.get("ticker") or "")
        code_4digit = raw_ticker.replace(".T", "").strip()
        
        if code_4digit in pdf_data:
            data_item = pdf_data[code_4digit]
            
            # IDまたはTickerをキーにして個別更新
            if "Ticker" in row:
                patch_url = f"{SUPABASE_URL}/rest/v1/stocks_master?Ticker=eq.{raw_ticker}"
            else:
                patch_url = f"{SUPABASE_URL}/rest/v1/stocks_master?ticker=eq.{raw_ticker}"
                
            payload = {
                "margin_buy": data_item["buy"],
                "margin_sell": data_item["sell"]
            }
            
            patch_res = requests.patch(patch_url, json=payload, headers=headers)
            if patch_res.status_code in [200, 204]:
                updated_count += 1

    print(f"🎉 成功！ 計 {updated_count} 件の既存銘柄に信用残高データを上書き更新しました！")

if __name__ == "__main__":
    print("1. JPXから最新PDFのURLを取得中...")
    pdf_url = get_latest_pdf_url()
    print(f"   URL検出: {pdf_url}")
    
    print("2. PDFをダウンロード中...")
    pdf_res = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    with open("latest_margin.pdf", "wb") as f:
        f.write(pdf_res.content)
        
    print("3. PDFから信用データを解析中...")
    pdf_data = parse_margin_pdf("latest_margin.pdf")
    print(f"   抽出完了: {len(pdf_data)} 銘柄分")
    
    if pdf_data:
        update_supabase_directly(pdf_data)
    else:
        print("⚠️ エラー: PDFからデータを抽出できませんでした。")
