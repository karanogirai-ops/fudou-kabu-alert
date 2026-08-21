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


def parse_margin_pdf_robust(pdf_bytes):
  """pdfplumberのレイアウト解析（extract_words）を使って

  座標ベースで各行の要素を正確に順序付けし、数値を取り出す
  """
  extracted_dict = {}

  with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
    for page in pdf.pages:
      words = page.extract_words(x_tolerance=3, y_tolerance=3)
      if not words:
        continue

      # Y座標（行）ごとに単語をグループ化
      lines_dict = {}
      for w in words:
        top_key = round(w["top"], 1)
        if top_key not in lines_dict:
          lines_dict[top_key] = []
        lines_dict[top_key].append(w)

      # 行ごとにX座標（左からの位置）順に並び替え
      for top_key in sorted(lines_dict.keys()):
        line_words = sorted(lines_dict[top_key], key=lambda x: x["x0"])
        text_tokens = [w["text"] for w in line_words]

        # 行内に5桁のコード（例: 24330）があるか判定
        for idx, token in enumerate(text_tokens):
          if re.match(r"^\d{5}$", token):
            code_4digit = token[:4]
            after_tokens = text_tokens[idx + 1 :]

            # コードより右側のトークンから純粋な数字のみ抽出
            nums = []
            for t in after_tokens:
              clean_t = re.sub(r"[^\d]", "", t)
              if clean_t.isdigit() and len(clean_t) > 0:
                nums.append(int(clean_t))

            # JPXの配置: [0]売残合計, [1]売残一般, [2]売残制度, [3]買残一般, [4]買残制度, [5]買残合計 (または前週比入りで7個)
            if len(nums) >= 6:
              sell_total = nums[0]
              buy_total = nums[-1]  # 配列の最後が必ず「買残合計」
              extracted_dict[code_4digit] = {
                  "sell": sell_total,
                  "buy": buy_total,
              }
            elif len(nums) >= 2:
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

  print("2. 座標解析データを照合して信用残高を更新中...")

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
      " 件の信用残高データを正確に上書き更新しました！"
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

    print("3. 位置座標（words）を精密解析中...")
    pdf_data = parse_margin_pdf_robust(res.content)
    print(f"   抽出成功銘柄数: {len(pdf_data)} 件")

    if pdf_data:
      update_supabase_directly(pdf_data)
    else:
      print("⚠️ エラー: PDFからデータを抽出できませんでした。")
  except Exception as e:
    print(f"❌ 処理失敗: {e}")
