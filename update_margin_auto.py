import io
import os
import re
import pdfplumber
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

JPX_MARGIN_PAGE = (
    "https://www.jpx.co.jp/markets/statistics-equities/margin/05.html"
)


def get_latest_pdf_url():
  headers = {"User-Agent": "Mozilla/5.0"}
  res = requests.get(JPX_MARGIN_PAGE, headers=headers, timeout=15)
  res.raise_for_status()

  from bs4 import BeautifulSoup

  soup = BeautifulSoup(res.text, "html.parser")
  for a in soup.find_all("a", href=True):
    href = a["href"]
    if href.lower().endswith(".pdf"):
      return (
          href if href.startswith("http") else "https://www.jpx.co.jp" + href
      )

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


def parse_pdf_table_strict(pdf_bytes):
  """表構造（セル位置）を直接指定して制度信用（特定）の数値を完全に正確に抽出"""
  margin_map = {}

  with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
    for page in pdf.pages:
      # 明示的な表抽出設定（縦横のテキスト配置からグリッドを生成）
      tables = page.extract_tables({
          "vertical_strategy": "text",
          "horizontal_strategy": "text",
          "snap_tolerance": 3,
      })

      for table in tables:
        for row in table:
          if not row:
            continue

          # セル内の無駄な改行や空白を除去
          clean_row = [
              str(cell).strip().replace("\n", "").replace(",", "")
              for cell in row
              if cell is not None
          ]

          # 行内に5桁の銘柄コードを探す
          for idx, cell in enumerate(clean_row):
            if re.match(r"^\d{5}$", cell):
              code_4digit = cell[:4]

              # コードより右側にある「純粋な数字セル」のみを取り出す
              nums = []
              for val in clean_row[idx + 1 :]:
                # 前週比や▲記号、ハイフン等を除外した数字のみ
                clean_num = re.sub(r"[^\d]", "", val)
                if clean_num.isdigit() and len(clean_num) > 0:
                  nums.append(int(clean_num))

              # JPXのPDF列構成（数字のみの配列）：
              # [0] 売り残合計
              # [1] 売り残（一般）
              # [2] 売り残（制度＝特定）★
              # [3] 買い残（一般）
              # [4] 買い残（制度＝特定）★
              if len(nums) >= 5:
                sell_system = nums[2]
                buy_system = nums[4]

                margin_map[code_4digit] = {
                    "sell": sell_system,
                    "buy": buy_system,
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
      "Prefer": "resolution=merge-duplicates",
  }

  print("1. Supabaseから全銘柄リストを取得中...")
  rows = fetch_all_supabase_rows({
      "apikey": SUPABASE_KEY,
      "Authorization": f"Bearer {SUPABASE_KEY}",
  })
  print(f"   Supabase登録数: {len(rows)} 件")

  print("2. JPXから最新PDFを取得中...")
  pdf_url = get_latest_pdf_url()
  pdf_res = requests.get(
      pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30
  )

  print("3. 表構造（Grid）から制度信用（特定）の数値を抽出中...")
  margin_map = parse_pdf_table_strict(pdf_res.content)
  print(f"   解析完了: {len(margin_map)} 銘柄分を抽出")

  print("4. Supabaseへ正常数値を上書き更新中...")
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
    chunk = payload_list[i : i + chunk_size]
    res = requests.post(endpoint, json=chunk, headers=headers, timeout=30)
    if res.status_code in [200, 201]:
      success_count += len(chunk)

  print(
      f"🎉 完了！ 計 {success_count} 件の制度信用データを正確に更新しました！"
  )


if __name__ == "__main__":
  update_supabase_system_margin()
