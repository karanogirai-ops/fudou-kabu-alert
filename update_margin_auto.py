import io
import os
import re
from bs4 import BeautifulSoup
import pdfplumber
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

JPX_MARGIN_PAGE = (
    "https://www.jpx.co.jp/markets/statistics-equities/margin/05.html"
)


def get_latest_pdf_url():
  headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
  res = requests.get(JPX_MARGIN_PAGE, headers=headers, timeout=15)
  res.raise_for_status()

  soup = BeautifulSoup(res.text, "html.parser")
  for a in soup.find_all("a", href=True):
    href = a["href"]
    if href.lower().endswith(".pdf"):
      return (
          href if href.startswith("http") else "https://www.jpx.co.jp" + href
      )

  raise Exception("JPXのページからPDFリンクが見つかりませんでした。")


def parse_margin_pdf_tables(pdf_bytes):
  """pdfplumberを使用してPDF内の表構造（テーブル）を格子のまま抽出し、

  売残合計（1列目の数値）と買残合計（最終列の数値）を正確に取得する
  """
  extracted_dict = {}

  with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
    for page in pdf.pages:
      # ページ内のテーブルを抽出
      tables = page.extract_tables()
      for table in tables:
        for row in table:
          if not row:
            continue

          # 行内のテキストを整理
          clean_row = [
              str(cell).strip().replace("\n", "") if cell else ""
              for cell in row
          ]

          # 銘柄コード（4桁または5桁）を探す
          for idx, cell in enumerate(clean_row):
            clean_code = cell.replace(".0", "")
            if re.match(r"^\d{4}$", clean_code) or re.match(
                r"^\d{5}$", clean_code
            ):
              code_4digit = clean_code[:4]

              # コードより右側の列から数値セルのみを取り出す
              after_cells = clean_row[idx + 1 :]
              nums = []
              for val in after_cells:
                # カンマや記号を除去して純粋な数値かどうか判定
                clean_num = re.sub(r"[^\d]", "", val)
                if clean_num.isdigit() and len(clean_num) > 0:
                  nums.append(int(clean_num))

              # JPXの表レイアウト:
              # 数値配列の最初 [0] が「売り残高（合計）」、最後 [-1] が「買い残高（合計）」
              if len(nums) >= 2:
                sell_total = nums[0]
                buy_total = nums[-1]
                extracted_dict[code_4digit] = {
                    "sell": sell_total,
                    "buy": buy_total,
                }
              break

  return extracted_dict


def update_supabase_directly(pdf_data):
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

  print("2. PDF表データを照合して信用残高（合計値）を更新中...")

  updated_count = 0
  for row in rows:
    raw_ticker = str(row.get("Ticker") or row.get("ticker") or "")
    code_4digit = raw_ticker.replace(".T", "").strip()

    if code_4digit in pdf_data:
      data_item = pdf_data[code_4digit]

      if "Ticker" in row:
        patch_url = (
            f"{SUPABASE_URL}/rest/v1/stocks_master?Ticker=eq.{raw_ticker}"
        )
      else:
        patch_url = (
            f"{SUPABASE_URL}/rest/v1/stocks_master?ticker=eq.{raw_ticker}"
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
      " 件の信用残高（PDF表解析データ）を正確に上書き更新しました！"
  )


if __name__ == "__main__":
  print("1. JPXから最新PDFのURLを取得中...")
  try:
    pdf_url = get_latest_pdf_url()
    print(f"   URL検出: {pdf_url}")

    print("2. PDFファイルをダウンロード中...")
    res = requests.get(
        pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30
    )

    print("3. pdfplumberでPDFの表構造を精密解析中...")
    pdf_data = parse_margin_pdf_tables(res.content)
    print(f"   抽出完了: {len(pdf_data)} 銘柄分")

    if pdf_data:
      update_supabase_directly(pdf_data)
    else:
      print("⚠️ エラー: PDFから表データを抽出できませんでした。")
  except Exception as e:
    print(f"❌ 処理失敗: {e}")
