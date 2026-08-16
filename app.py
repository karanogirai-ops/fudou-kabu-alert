import streamlit as st
import yfinance as yf
import pandas as pd
import csv
import datetime
import time
import requests

# --- 1. 設定 & Supabase REST API設定 ---
# 一度に通信する銘柄数（BAN対策として200銘柄ずつ小分け取得）
CHUNK_SIZE = 200

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

# --- 2. 永続化（Supabase REST API読み書き）関数 ---
def load_default_stocks():
    stocks = []
    try:
        with open("stocks.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stocks.append({
                    "ticker": row["Ticker"],
                    "name": row["Name"]
                })
    except Exception:
        pass
    return stocks

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
    
    initial_groups = {"基本グループ": load_default_stocks()}
    save_groups(initial_groups)
    return initial_groups

def save_groups(groups):
    try:
        rest_url, headers = get_supabase_config()
        endpoint = f"{rest_url}/app_data"
        payload = {
            "id": "stock_groups",
            "data": groups
        }
        headers_upsert = headers.copy()
        headers_upsert["Prefer"] = "resolution=merge-duplicates"
        
        res = requests.post(endpoint, json=payload, headers=headers_upsert, timeout=10)
    except Exception as e:
        st.error(f"データ保存エラー: {e}")

# --- 3. 発行済株式数の一括取得＆キャッシュ（通信激減処理） ---
@st.cache_data(ttl=86400)
def fetch_shares_outstanding_batch(ticker_list):
    """
    主要銘柄・全銘柄の発行済株式数を可能な限り効率的に取得
    24時間キャッシュするため、1日1回以上の通信は発生しません
    """
    shares_map = {}
    # 安全のため小分け取得
    for i in range(0, len(ticker_list), 50):
        chunk = ticker_list[i:i + 50]
        for t in chunk:
            try:
                stock = yf.Ticker(t)
                # fast_infoを使うことで低負荷かつ高速に取得
                s_out = stock.fast_info.get('shares_outstanding') or stock.info.get('sharesOutstanding')
                if s_out and s_out > 0:
                    shares_map[t] = s_out
            except Exception:
                pass
        time.sleep(0.2)
    return shares_map

# --- 4. 画面UIと処理 ---
st.title("🚀 株式回転率チェッカー（東証全銘柄・極小通信対応）")

groups = load_groups()

# ★ グループ＆銘柄の管理セクション
with st.expander("⚙️ グループの作成・名前変更・銘柄管理", expanded=False):
    
    new_group_name = st.text_input("新しいグループを作成（例: 東証全銘柄）", key="new_group_input")
    if st.button("グループを作成", use_container_width=True):
        if new_group_name and new_group_name not in groups:
            groups[new_group_name] = []
            save_groups(groups)
            st.success(f"グループ「{new_group_name}」を作成・保存しました！")
            st.rerun()
        elif new_group_name in groups:
            st.warning("そのグループ名は既に存在します。")

    st.divider()

    group_names = list(groups.keys())
    active_group = st.selectbox("編集対象のグループを選択", group_names)
    
    rename_group_input = st.text_input("選択中グループの名前を変更", value=active_group, key=f"rename_{active_group}")
    if st.button("名前を変更", use_container_width=True):
        if rename_group_input and rename_group_input != active_group:
            if rename_group_input in groups:
                st.warning("そのグループ名は既に存在します。")
            else:
                groups[rename_group_input] = groups.pop(active_group)
                save_groups(groups)
                st.success(f"「{active_group}」を「{rename_group_input}」に変更・保存しました！")
                st.rerun()

    st.markdown(f"**現在の「{active_group}」の登録一覧 (計 {len(groups[active_group])} 銘柄)**")
    
    if groups[active_group]:
        df_display = pd.DataFrame(groups[active_group])
        df_display.columns = ["コード", "銘柄名"]
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        delete_options = [f"{item['ticker']} | {item['name']}" for item in groups[active_group]]
        selected_to_delete = st.selectbox("🗑️ 削除したい銘柄を選択", delete_options, key=f"del_select_{active_group}")
        
        if st.button("選択した銘柄を削除", use_container_width=True):
            target_ticker = selected_to_delete.split(" | ")[0]
            groups[active_group] = [item for item in groups[active_group] if item["ticker"] != target_ticker]
            save_groups(groups)
            st.success("削除して保存しました！")
            st.rerun()
    else:
        st.info("このグループには銘柄が登録されていません。")

    st.divider()

    st.markdown("**📥 CSV/コピペから一括追加**")
    bulk_input = st.text_area(
        "JPXのExcel/CSV等から「コード, 銘柄名」をコピペしてください:", 
        height=140
    )
    
    if st.button("このグループに一括追加", use_container_width=True):
        if bulk_input:
            lines = bulk_input.strip().split("\n")
            added_count = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",")]
                raw_ticker = parts[0]
                name = parts[1] if len(parts) > 1 else raw_ticker
                
                formatted_ticker = raw_ticker.upper() if raw_ticker.endswith(".T") else f"{raw_ticker}.T"
                
                groups[active_group].append({
                    "ticker": formatted_ticker,
                    "name": name
                })
                added_count += 1
            
            save_groups(groups)
            st.success(f"「{active_group}」に {added_count} 件の銘柄を追加・保存しました！")
            st.rerun()

    if active_group != "基本グループ":
        if st.button(f"🗑️ 「{active_group}」グループごと削除", use_container_width=True):
            del groups[active_group]
            save_groups(groups)
            st.success(f"グループ「{active_group}」を削除しました。")
            st.rerun()

st.divider()

# ★ 超安全・超高速スキャン実行
selected_scan_group = st.selectbox("🎯 スキャンを実行するグループを選択", list(groups.keys()))

threshold_percent = st.number_input(
    "アラートを出す回転率の閾値（%）",
    min_value=1.0,
    max_value=200.0,
    value=5.0,
    step=1.0
)

if st.button("🛡️ BAN対策スキャンを実行（安全一括取得）", use_container_width=True):
    stocks = groups[selected_scan_group]
    total_stocks = len(stocks)
    
    if total_stocks == 0:
        st.warning(f"「{selected_scan_group}」には銘柄が登録されていません。")
    else:
        status_text = st.empty()
        progress_bar = st.progress(0)
        
        ticker_list = [s["ticker"] for s in stocks]
        name_map = {s["ticker"]: s["name"] for s in stocks}
        
        # Step 1: 発行済株式数を安全に準備
        status_text.info(f"1/2: 発行済株式数データの準備中...（全 {total_stocks} 銘柄）")
        shares_map = fetch_shares_outstanding_batch(tuple(ticker_list))
        
        results = []
        alert_count = 0
        
        # Step 2: 200銘柄ずつのチャンク（小分け）通信で株価データ取得
        status_text.info(f"2/2: 株価・出来高データを安全に一括取得中...")
        
        total_chunks = (total_stocks + CHUNK_SIZE - 1) // CHUNK_SIZE
        
        for c_idx in range(total_chunks):
            chunk_tickers = ticker_list[c_idx * CHUNK_SIZE : (c_idx + 1) * CHUNK_SIZE]
            
            try:
                # 200銘柄まとめて1回の通信
                downloaded = yf.download(tickers=chunk_tickers, period="10d", group_by="ticker", progress=False)
                
                for ticker in chunk_tickers:
                    name = name_map[ticker]
                    shares_outstanding = shares_map.get(ticker)
                    
                    if not shares_outstanding or shares_outstanding <= 0:
                        continue
                    
                    if len(chunk_tickers) == 1:
                        stock_hist = downloaded
                    else:
                        stock_hist = downloaded.get(ticker)
                    
                    if stock_hist is None or stock_hist.empty:
                        continue
                    
                    stock_hist = stock_hist.dropna(subset=['Volume', 'Close'])
                    recent_history = stock_hist.tail(5)
                    
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
            except Exception as e:
                pass
            
            progress_bar.progress((c_idx + 1) / total_chunks)
            time.sleep(0.5) # BAN回避用ウェイト
        
        status_text.text("すべてのスキャンが完了しました！")
        
        if results:
            st.success(f"スキャン完了！ 計 {alert_count} 件の過熱（閾値超え）が発見されました。")
            df_results = pd.DataFrame(results)
            df_results = df_results.sort_values("日付", ascending=False)
            st.dataframe(df_results, use_container_width=True, hide_index=True)
        else:
            st.info(f"スキャン完了！ 閾値（{threshold_percent}%）を超えた銘柄はありませんでした。")
