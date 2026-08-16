import streamlit as st
import yfinance as yf
import pandas as pd
import datetime
import time
import requests

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
        "Prefer": "return=representation"
    }
    return rest_url, headers

def load_groups():
    try:
        rest_url, headers = get_supabase_config()
        endpoint = f"{rest_url}/app_data?id=eq.stock_groups&select=data"
        res = requests.get(endpoint, headers=headers, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            if data and len(data) > 0 and "data" in data[0]:
                return data[0]["data"]
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
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
        st.error(f"データ保存エラー: {e}")

# --- 2. stocks.csv の読み込み ---
@st.cache_data
def load_csv_master():
    try:
        df = pd.read_csv("stocks.csv", encoding="utf-8")
    except UnicodeDecodeError:
        df = pd.read_csv("stocks.csv", encoding="cp932")
    return df

# --- 3. キャッシュ付き発行済株式数取得 ---
@st.cache_data(ttl=86400)
def get_shares_outstanding(ticker):
    try:
        stock = yf.Ticker(ticker)
        s_out = stock.fast_info.get('shares_outstanding')
        if not s_out:
            s_out = stock.info.get('sharesOutstanding')
        if s_out and s_out > 0:
            return float(s_out)
    except Exception:
        pass
    return None

# --- 4. 画面UIと処理 ---
st.title("🚀 株式回転率チェッカー（17seg業種別対応）")

csv_df = load_csv_master()
groups = load_groups()

# ★ 検索モード選択
st.markdown("### 🎯 検索モードの選択")
search_mode = st.radio(
    "スキャン方法を選んでください:",
    ["🏢 17業種区分（17seg-Name）でスキャン", "🏷️ 市場区分（Categoy）でスキャン", "📁 カスタムグループ（Supabase保存）でスキャン"],
    horizontal=True
)

target_stocks = []

if search_mode == "🏢 17業種区分（17seg-Name）でスキャン":
    # "-"（ハイフン/未分類）を除外した17業種リストを作成
    valid_17seg_df = csv_df[csv_df["17seg-Name"].astype(str).str.strip() != "-"]
    unique_17seg = sorted([str(x) for x in valid_17seg_df["17seg-Name"].dropna().unique()])
    
    selected_17seg = st.selectbox("17業種（17seg-Name）を選択", unique_17seg)
    filtered_df = csv_df[csv_df["17seg-Name"] == selected_17seg]
    
    st.info(f"選択中: **{selected_17seg}** （該当: **{len(filtered_df)}** 銘柄）")
    
    for _, row in filtered_df.iterrows():
        target_stocks.append({
            "ticker": str(row["Ticker"]),
            "name": str(row["Name"])
        })

elif search_mode == "🏷️ 市場区分（Categoy）でスキャン":
    unique_categoy = sorted([str(x) for x in csv_df["Categoy"].dropna().unique()])
    selected_categoy = st.selectbox("市場区分（Categoy）を選択", unique_categoy)
    filtered_df = csv_df[csv_df["Categoy"] == selected_categoy]
    
    st.info(f"選択中: **{selected_categoy}** （該当: **{len(filtered_df)}** 銘柄）")
    
    for _, row in filtered_df.iterrows():
        target_stocks.append({
            "ticker": str(row["Ticker"]),
            "name": str(row["Name"])
        })

else:
    # カスタムグループ検索
    group_names = list(groups.keys()) if groups else []
    if not group_names:
        st.warning("カスタムグループが登録されていません。下の設定画面から作成してください。")
    else:
        selected_group_name = st.selectbox("グループを選択", group_names)
        target_stocks = groups[selected_group_name]
        st.info(f"選択中: **{selected_group_name}** （該当: **{len(target_stocks)}** 銘柄）")

st.divider()

# ★ スキャン設定
threshold_percent = st.number_input(
    "アラートを出す回転率の閾値（%）",
    min_value=1.0,
    max_value=200.0,
    value=5.0,
    step=1.0
)

if st.button("🚀 今すぐスキャンを実行する", use_container_width=True):
    total_stocks = len(target_stocks)
    
    if total_stocks == 0:
        st.warning("対象となる銘柄がありません。")
    else:
        status_text = st.empty()
        progress_bar = st.progress(0)
        
        ticker_list = [s["ticker"] for s in target_stocks]
        name_map = {s["ticker"]: s["name"] for s in target_stocks}
        
        results = []
        alert_count = 0
        
        total_chunks = (total_stocks + CHUNK_SIZE - 1) // CHUNK_SIZE
        
        for c_idx in range(total_chunks):
            chunk_tickers = ticker_list[c_idx * CHUNK_SIZE : (c_idx + 1) * CHUNK_SIZE]
            current_processed = min((c_idx + 1) * CHUNK_SIZE, total_stocks)
            
            status_text.info(f"スキャン進行中... {current_processed} / {total_stocks} 銘柄完了（{c_idx + 1}/{total_chunks}）")
            
            try:
                downloaded = yf.download(tickers=chunk_tickers, period="10d", group_by="ticker", progress=False)
                
                for ticker in chunk_tickers:
                    name = name_map[ticker]
                    
                    if len(chunk_tickers) == 1:
                        stock_hist = downloaded
                    else:
                        stock_hist = downloaded.get(ticker)
                    
                    if stock_hist is None or stock_hist.empty:
                        continue
                    
                    stock_hist = stock_hist.dropna(subset=['Volume', 'Close'])
                    recent_history = stock_hist.tail(5)
                    
                    if recent_history['Volume'].sum() <= 0:
                        continue
                    
                    shares_outstanding = get_shares_outstanding(ticker)
                    if not shares_outstanding or shares_outstanding <= 0:
                        continue
                    
                    for idx, row in recent_history.iterrows():
                        daily_volume = float(row['Volume'])
                        close_price = float(row['Close'])
                        date_str = idx.strftime('%Y/%m/%d')
                        turnover_rate = (daily_volume / shares_outstanding) * 100
                        
                        market_cap_oku = int(round((close_price * shares_outstanding) / 100_000_000))
                        
                        if turnover_rate >= threshold_percent:
                            alert_count += 1
                            results.append({
                                "日付": date_str,
                                "コード": ticker,
                                "銘柄名": name,
                                "回転率 (%)": round(turnover_rate, 2),
                                "時価総額（億円）": f"{market_cap_oku:,}",
                                "発行済株式数": f"{int(shares_outstanding):,}",
                                "株価（円）": round(close_price, 1)
                            })
            except Exception:
                pass
            
            progress_bar.progress((c_idx + 1) / total_chunks)
            time.sleep(0.2)
        
        status_text.text("すべてのスキャンが完了しました！")
        
        if results:
            st.success(f"スキャン完了！ 計 {alert_count} 件の過熱（閾値超え）が発見されました。")
            df_results = pd.DataFrame(results)
            df_results = df_results.sort_values("日付", ascending=False)
            st.dataframe(df_results, use_container_width=True, hide_index=True)
        else:
            st.info(f"スキャン完了！ 閾値（{threshold_percent}%）を超えた銘柄はありませんでした。")

st.divider()

# ★ カスタムグループ管理（折りたたみ）
with st.expander("⚙️ カスタムグループの作成・編集（Supabase保存）", expanded=False):
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
        
        st.markdown(f"**現在の「{active_group}」の登録一覧 (計 {len(groups[active_group])} 銘柄)**")
        if groups[active_group]:
            df_display = pd.DataFrame(groups[active_group])
            st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            delete_options = [f"{item['ticker']} | {item['name']}" for item in groups[active_group]]
            selected_to_delete = st.selectbox("🗑️ 削除したい銘柄を選択", delete_options)
            if st.button("選択した銘柄を削除", use_container_width=True):
                target_ticker = selected_to_delete.split(" | ")[0]
                groups[active_group] = [item for item in groups[active_group] if item["ticker"] != target_ticker]
                save_groups(groups)
                st.success("削除しました！")
                st.rerun()

        st.divider()
        bulk_input = st.text_area("コピペで一括追加（コード, 銘柄名）:", height=100)
        if st.button("一括追加", use_container_width=True):
            if bulk_input:
                for line in bulk_input.strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if parts[0]:
                        t = parts[0].upper() if parts[0].endswith(".T") else f"{parts[0]}.T"
                        n = parts[1] if len(parts) > 1 else t
                        groups[active_group].append({"ticker": t, "name": n})
                save_groups(groups)
                st.success("追加しました！")
                st.rerun()
