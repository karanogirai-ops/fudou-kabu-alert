import os
import re
import requests
from bs4 import BeautifulSoup
import pypdf

# GitHub Secrets または環境変数からSupabaseの接続情報を取得
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

# JPX「銘柄別信用取引週末残高」ページURL
JPX_MARGIN_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/margin/05.html"

def get_latest_pdf_url():
    """05.html ページから最新のPDFリンクを取得"""
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
    """PDFを全ページ読み込み、銘柄コードと信用売残(合計)・買残(合計)を正確に抽出"""
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
            # 5桁数字（末尾0）の銘柄コード（例: 13010 -> 1301.T）
            if re.match(r'^\d{5}$', part):
                code_raw = part[:4] + ".T"
                
                # 銘柄コードより後ろのパートから数値だけを抽出
                after_parts = parts[idx + 1:]
                clean_nums = []
                for p in after_parts:
                    p_clean = p.replace(',', '')
                    if p_clean.isdigit():
                        clean_nums.append(int(p_clean))
                
                # 東証PDFの列レイアウト:
                # 1番目の数値 = 売残高（合計）
                # 5番目の数値 = 買残高（合計）
                if len(clean_nums) >= 5:
                    sell_margin = clean_nums[0]
                    buy_margin = clean_nums[4]
                elif len(clean_nums) >= 2:
                    sell_margin = clean_nums[0]
                    buy_margin = clean_nums[1]
                else:
                    break
                
                # Supabaseのカラム名が Ticker / ticker のどちらでも適合するよう両方含める
                extracted_data.append({
                    "Ticker": code_raw,
                    "ticker": code_raw,
                    "margin_sell": sell_margin,
                    "margin_buy": buy_margin
                })
                break
                
    return extracted_data

def update_supabase(data):
    """Supabaseの stocks_master テーブルへ分割アップサート（上書き更新）"""
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("SUPABASE_URL または SUPABASE_KEY が設定されていません。")
        return

    endpoint = f"{SUPABASE_URL}/rest/v1/stocks_master"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }
    
    chunk_size = 200
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        res = requests.post(endpoint, json=chunk, headers=headers, timeout=15)
        if res.status_code in [200, 201]:
            print(f"送信成功: {i + len(chunk)} / {len(data)} 件完了")
        else:
            print(f"エラー ({res.status_code}): {res.text}")

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
    print(f"   抽出完了: {len(margin_data)} 銘柄")
    
    if margin_data:
        print("4. Supabaseへデータを送信中...")
        update_supabase(margin_data)
        print("🎉 信用残高データの完全自動更新が終了しました！")
