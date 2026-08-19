import time
import pandas as pd
import requests
import streamlit as st
import yfinance as yf

CHUNK_SIZE = 200


# --- 1. Supabase REST API設定 ---
def get_supabase_config():
  url = st.secrets["SUPABASE_URL"].rstrip("/")
  key = st.secrets["SUPABASE_KEY"].strip()

  if not url.endswith("/rest/v1"):
    rest_url = f"{url}/rest/v1"
  else:
    rest_url = url

  headers = {
      "apikey": key,
      "Authorization": f"Bearer {key}",
      "Content-Type": "application/json",
      "Prefer": "return=representation",
  }
  return rest_url, headers


# --- 2. Supabaseからの全件データ取得（ページネーション対応） ---
@st.cache_data(ttl=3600)
def load_supabase_master():
  """1,000件制限を回避して全件取得"""
  all_data = []
  page_size = 1000
  offset = 0

  try:
    rest_url, headers = get_supabase_config()

    while True:
      headers_read = headers.copy()
      headers_read["Range-Unit"] = "items"
      headers_read["Range"] = f"{offset}-{offset + page_size - 1}"

      endpoint = f"{rest_url}/stocks_master?select=*"
      res = requests.get(endpoint, headers=headers_read, timeout=10)

      if res.status_code in [200, 206]:
        data = res.json()
        if not data:
          break
        all_data.extend(data)
        if len(data) < page_size:
          break
        offset += page_size
      else:
        break

    if all_data:
      return pd.DataFrame(all_data)
  except Exception as e:
    st.error(f"Supabaseマスタ取得エラー: {e}")
  return pd.DataFrame()


def load_groups():
  try:
    rest_url, headers = get_supabase_config()
    endpoint = f"{rest_url}/app_data?id=eq.stock_groups&select=data"
    res = requests.get(endpoint, headers=headers, timeout=10)

    if res.status_code in [200, 206]:
      data = res.json()
      if data and len(data) > 0 and "data" in data[0]:
        return data[0]["data"]
  except Exception as e:
    st.error(f"グループ取得エラー: {e}")
  return {}


def save_groups(groups):
  try:
    rest_url, headers = get_supabase_config()
    endpoint = f"{rest_url}/app_data"
    payload = {"id": "stock_groups", "data": groups}
    headers_upsert = headers.copy()
    headers_upsert["Prefer"] = "resolution=merge-duplicates"
    requests.post(endpoint, json=payload, headers=headers_upsert, timeout=10)
  except Exception as e:
    st.error(f"グループ保存エラー: {e}")


# --- 3. 発行済株式数取得（キャッシュ機能付き） ---
@st.cache_data(ttl=86400)
def get_shares_outstanding(ticker):
  try:
    stock = yf.Ticker(ticker)
    s_out = stock.fast_info.get("shares_outstanding")
    if not s_out:
      s_out = stock.info.get("sharesOutstanding")
    if s_out and s_out > 0:
      return float(s_out)
  except Exception:
    pass
  return None


# --- 4. 画面UIと処理 ---
st.title("🚀 株式回転率 & 需給チェッカー（クラウドマスタ対応）")

# データ読み込み
master_df = load_supabase_master()
groups = load_groups()

if master_df.empty:
  st.warning(
      "⚠️ Supabaseの stocks_master"
      " テーブルからデータを取得できませんでした。"
  )

# ★ 1. スキャン計算基準の選択
st.markdown("### 📊 1. 回転率の計算基準を選択")
calc_mode = st.radio(
    "回転率（%）の計算基準:",
    [
        "📈 総株数ベース（通常: 出来高 ÷ 発行済株式数）",
        "🎈 浮動株数ベース（精密: 出来高 ÷ [発行済株式数 × 浮動株比率]）",
    ],
    horizontal=False,
)

is_float_mode = "浮動株数ベース" in calc_mode

st.divider()

# ★ 2. 検索対象グループの選択
st.markdown("### 🎯 2. 検索対象を選択")
search_mode = st.radio(
    "対象銘柄の絞り込み方法:",
    [
        "🏢 17業種区分（17seg-Name）",
        "🏷️ 市場区分（Categoy）",
        "📁 カスタムグループ",
    ],
    horizontal=True,
)

target_stocks = []

if not master_df.empty:
  col_ticker = "Ticker" if "Ticker" in master_df.columns else "ticker"
  col_name = "Name" if "Name" in master_df.columns else "name"
  col_categoy = "Categoy" if "Categoy" in master_df.columns else "categoy"
  col_17seg_name = (
      "17seg-Name"
      if "17seg-Name" in master_df.columns
      else (
          "17seg_name" if "17seg_name" in master_df.columns else "17seg"
      )
  )

  if search_mode == "🏢 17業種区分（17seg-Name）":
    valid_df = master_df[
        master_df[col_17seg_name].astype(str).str.strip() != "-"
    ]
    unique_categories = sorted(
        [str(x) for x in valid_df[col_17seg_name].dropna().unique()]
    )

    selected_cat = st.selectbox("17業種を選択", unique_categories)
    filtered_df = master_df[master_df[col_17seg_name] == selected_cat]
    st.info(
        f"選択中: **{selected_cat}** （該当: **{len(filtered_df)}** 銘柄）"
    )

    for _, row in filtered_df.iterrows():
      target_stocks.append({
          "ticker": str(row[col_ticker]),
          "name": str(row[col_name]),
          "float_ratio": (
              float(row.get("float_ratio", 1.0))
              if pd.notnull(row.get("float_ratio"))
              else 1.0
          ),
          "margin_buy": (
              float(row.get("margin_buy", 0))
              if pd.notnull(row.get("margin_buy"))
              else 0
          ),
          "margin_sell": (
              float(row.get("margin_sell", 0))
              if pd.notnull(row.get("margin_sell"))
              else 0
          ),
      })

  elif search_mode == "🏷️ 市場区分（Categoy）":
    unique_categoy = sorted(
        [str(x) for x in master_df[col_categoy].dropna().unique()]
    )

    selected_cat = st.selectbox("市場区分を選択", unique_categoy)
    filtered_df = master_df[master_df[col_categoy] == selected_cat]
    st.info(
        f"選択中: **{selected_cat}** （該当: **{len(filtered_df)}** 銘柄）"
    )

    for _, row in filtered_df.iterrows():
      target_stocks.append({
          "ticker": str(row[col_ticker]),
          "name": str(row[col_name]),
          "float_ratio": (
              float(row.get("float_ratio", 1.0))
              if pd.notnull(row.get("float_ratio"))
              else 1.0
          ),
          "margin_buy": (
              float(row.get("margin_buy", 0))
              if pd.notnull(row.get("margin_buy"))
              else 0
          ),
          "margin_sell": (
              float(row.get("margin_sell", 0))
              if pd.notnull(row.get("margin_sell"))
              else 0
          ),
      })

  else:
    group_names = list(groups.keys()) if groups else []
    if not group_names:
      st.warning(
          "カスタムグループが登録されていません。画面下部から作成してください。"
      )
    else:
      selected_group_name = st.selectbox("グループを選択", group_names)
      raw_target = groups[selected_group_name]
      st.info(
          f"選択中: **{selected_group_name}** （該当:"
          f" **{len(raw_target)}** 銘柄）"
      )

      master_dict = {row[col_ticker]: row for _, row in master_df.iterrows()}
      for item in raw_target:
        t = item["ticker"]
        row_data = master_dict.get(t, {})
        fr = row_data.get("float_ratio", 1.0)
        mb = row_data.get("margin_buy", 0)
        ms = row_data.get("margin_sell", 0)

        target_stocks.append({
            "ticker": t,
            "name": item["name"],
            "float_ratio": (
                float(fr) if pd.notnull(fr) and float(fr) > 0 else 1.0
            ),
            "margin_buy": float(mb) if pd.notnull(mb) else 0,
            "margin_sell": float(ms) if pd.notnull(ms) else 0,
        })

st.divider()

# ★ 3. 需給フィルター ＆ スキャン実行設定
st.markdown("### ⚙️ 3. スキャン・需給フィルター条件")
col1, col2 = st.columns(2)

with col1:
  threshold_percent = st.number_input(
      f"回転率の閾値（%） [{'浮動株' if is_float_mode else '総株数'}]",
      min_value=1.0,
      max_value=500.0,
      value=5.0 if not is_float_mode else 10.0,
      step=1.0,
  )

with col2:
  max_ratio_filter = st.number_input(
      "上限 信用倍率（倍） ※0でフィルター無効",
      min_value=0.0,
      max_value=100.0,
      value=0.0,
      step=0.5,
      help=(
          "例: 2.0"
          " に設定すると、信用倍率 2.0倍以下（売残多め・踏み上げ期待）の銘柄のみ抽出します。"
      ),
  )

if st.button("🚀 今すぐスキャンを実行する", use_container_width=True):
  total_stocks = len(target_stocks)

  if total_stocks == 0:
    st.warning("対象となる銘柄がありません。")
  else:
    status_text = st.empty()
    progress_bar = st.progress(0)

    ticker_list = [s["ticker"] for s in target_stocks]
    stock_dict = {s["ticker"]: s for s in target_stocks}

    results = []
    alert_count = 0

    total_chunks = (total_stocks + CHUNK_SIZE - 1) // CHUNK_SIZE

    for c_idx in range(total_chunks):
      chunk_tickers = ticker_list[c_idx * CHUNK_SIZE : (c_idx + 1) * CHUNK_SIZE]
      current_processed = min((c_idx + 1) * CHUNK_SIZE, total_stocks)

      status_text.info(
          f"スキャン進行中... {current_processed} / {total_stocks}"
          f" 銘柄完了（{c_idx + 1}/{total_chunks}）"
      )

      try:
        downloaded = yf.download(
            tickers=chunk_tickers, period="10d", group_by="ticker", progress=False
        )

        for ticker in chunk_tickers:
          s_info = stock_dict[ticker]
          name = s_info["name"]
          float_ratio = s_info["float_ratio"]
          margin_buy = s_info["margin_buy"]
          margin_sell = s_info["margin_sell"]

          # 信用倍率の計算
          margin_ratio = (
              (margin_buy / margin_sell)
              if margin_sell > 0
              else (999.0 if margin_buy > 0 else 0.0)
          )

          # 信用倍率フィルター
          if max_ratio_filter > 0 and margin_ratio > max_ratio_filter:
            continue

          if len(chunk_tickers) == 1:
            stock_hist = downloaded
          else:
            stock_hist = downloaded.get(ticker)

          if stock_hist is None or stock_hist.empty:
            continue

          stock_hist = stock_hist.dropna(subset=["Volume", "Close"])
          recent_history = stock_hist.tail(5)

          if recent_history["Volume"].sum() <= 0:
            continue

          shares_outstanding = get_shares_outstanding(ticker)
          if not shares_outstanding or shares_outstanding <= 0:
            continue

          effective_shares = (
              (shares_outstanding * float_ratio)
              if is_float_mode
              else shares_outstanding
          )

          for idx, row in recent_history.iterrows():
            daily_volume = float(row["Volume"])
            close_price = float(row["Close"])
            date_str = idx.strftime("%Y/%m/%d")

            turnover_rate = (daily_volume / effective_shares) * 100
            # 取引総額（百万円単位）
            trading_value_hyakuman = int(
                round((close_price * daily_volume) / 1_000_000)
            )
            digest_days = (
                round(margin_buy / daily_volume, 1) if daily_volume > 0 else 0
            )

            if turnover_rate >= threshold_percent:
              alert_count += 1
              res_item = {
                  "日付": date_str,
                  "コード": ticker,
                  "銘柄名": name,
                  "回転率 (%)": round(turnover_rate, 2),
                  "取引総額（百万円）": f"{trading_value_hyakuman:,}",
                  "出来高（株）": f"{int(daily_volume):,}",
                  "株価（円）": round(close_price, 1),
                  "信用買残（株）": (
                      f"{int(margin_buy):,}" if margin_buy > 0 else "-"
                  ),
                  "信用売残（株）": (
                      f"{int(margin_sell):,}" if margin_sell > 0 else "-"
                  ),
                  "信用倍率（倍）": (
                      round(margin_ratio, 2)
                      if margin_ratio != 999.0
                      else "売りゼロ"
                  ),
                  "買残消化日数（日）": digest_days,
              }
              results.append(res_item)
      except Exception:
        pass

      progress_bar.progress((c_idx + 1) / total_chunks)
      time.sleep(0.2)

    status_text.text("すべてのスキャンが完了しました！")

    if results:
      st.success(
          f"スキャン完了！ 計 {alert_count} 件の過熱（閾値超え）が発見されました。"
      )
      df_results = pd.DataFrame(results)
      df_results = df_results.sort_values("日付", ascending=False)
      st.dataframe(df_results, use_container_width=True, hide_index=True)
    else:
      st.info("スキャン完了！ 条件に該当する銘柄はありませんでした。")

st.divider()

# ★ 4. カスタムグループ管理
with st.expander(
    "⚙️ カスタムグループの作成・編集（Supabase保存）", expanded=False
):
  new_group_name = st.text_input("新しいグループを作成", key="new_group_input")
  if st.button("グループを作成", use_container_width=True):
    if new_group_name and new_group_name not in groups:
      groups[new_group_name] = []
      save_groups(groups)
      st.success(f"グループ「{new_group_name}」を作成しました！")
      st.rerun()
    elif new_group_name in groups:
      st.warning("そのグループ名は既に存在します。")

  if groups:
    st.divider()
    active_group = st.selectbox("編集対象グループを選択", list(groups.keys()))

    st.markdown(
        f"**現在の「{active_group}」の登録一覧 (計"
        f" {len(groups[active_group])} 銘柄)**"
    )
    if groups[active_group]:
      df_display = pd.DataFrame(groups[active_group])
      st.dataframe(df_display, use_container_width=True, hide_index=True)

      delete_options = [
          f"{item['ticker']} | {item['name']}" for item in groups[active_group]
      ]
      selected_to_delete = st.selectbox(
          "🗑️ 削除したい銘柄を選択", delete_options
      )
      if st.button("選択した銘柄を削除", use_container_width=True):
        target_ticker = selected_to_delete.split(" | ")[0]
        groups[active_group] = [
            item
            for item in groups[active_group]
            if item["ticker"] != target_ticker
        ]
        save_groups(groups)
        st.success("削除しました！")
        st.rerun()

    st.divider()
    bulk_input = st.text_area(
        "コピペで一括追加（コード, 銘柄名）:", height=100
    )
    if st.button("一括追加", use_container_width=True):
      if bulk_input:
        for line in bulk_input.strip().split("\n"):
          parts = [p.strip() for p in line.split(",")]
          if parts[0]:
            t = (
                parts[0].upper()
                if parts[0].endswith(".T")
                else f"{parts[0]}.T"
            )
            n = parts[1] if len(parts) > 1 else t
            groups[active_group].append({"ticker": t, "name": n})
        save_groups(groups)
        st.success("追加しました！")
        st.rerun()
