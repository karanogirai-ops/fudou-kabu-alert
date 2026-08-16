import streamlit as st
import yfinance as yf
import pandas as pd
import csv
import datetime
import time
import requests

# --- 1. 設定 & Supabase REST API設定 ---
SLEEP_TIME = 0.5

def get_supabase_config():
    url = st.secrets["SUPABASE_URL"].rstrip("/")
    key = st.secrets["SUPABASE_KEY"].strip()
    
    # URLが末尾にrest/v1を含んでいない場合は正しく補正
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
    """Supabase REST APIからグループデータを取得"""
    try:
        rest_url, headers = get_supabase_config()
        endpoint = f"{rest_url}/app_data?id=eq.stock_groups&select=data"
        res = requests.get(endpoint, headers=headers, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            if data and len(data) > 0 and "data" in data[0]:
                return data[0]["data"]
        else:
            st.error(f"データ取得エラー ({res.status_code}): {res.text}")
    except Exception as e:
        st.error(f"データ取得エラー: {e}")
    
    # データが存在しないかエラー時は初期データを作成して保存
    initial_groups = {"基本グループ": load_default_stocks()}
    save_groups(initial_groups)
    return initial_groups

def save_groups(groups):
    """Supabase REST APIへグループデータを保存"""
    try:
        rest_url, headers = get_supabase_config()
        endpoint = f"{rest_url}/app_data"
        payload = {
            "id": "stock_groups",
            "data": groups
        }
        # upsert処理 (id重複時は上書き)
        headers_upsert = headers.copy()
        headers_upsert["Prefer"] = "resolution=merge-duplicates"
        
        res = requests.post(endpoint, json=payload, headers=headers_upsert, timeout=10)
        if res.status_code not in [200, 201, 204]:
            st.error(f"データ保存エラー ({res.status_code}): {res.text}")
    except Exception as e:
        st.error(f"データ保存エラー: {e}")

# --- 3. 画面UIと処理 ---
st.title("🚀 株式回転率チェッカー（Supabase永続化対応）")

groups = load_groups()

# ★ グループ＆銘柄の管理セクション
with st.expander("⚙️ グループの作成・名前変更・銘柄管理", expanded=False):
    
    # 1. 新規グループの作成
    new_group_name = st.text_input("新しいグループを作成（例: プライム100社）", key="new_group_input")
    if st.button("グループを作成", use_container_width=True):
        if new_group_name and new_group_name not in groups:
            groups[new_group_name] = []
            save_groups(groups)
            st.success(f"グループ「{new_group_name}」を作成・保存しました！")
            st.rerun()
        elif new_group_name in groups:
            st.warning("そのグループ名は既に存在します。")

    st.divider()

    # 2. 管理対象グループの選択
    group_names = list(groups.keys())
    active_group = st.selectbox("編集対象のグループを選択", group_names)
    
    # 3. グループ名の変更機能
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
    
    # ★ 銘柄一覧表示＆選択削除
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

    # 4. 銘柄の一括追加
    st.markdown("**📥 テキストエリアからコピペで一括追加**")
    st.caption("改行区切りで「コード, 銘柄名」または「コードのみ」を一括入力できます。")
    bulk_input = st.text_area(
        "入力例:\n7203.T, トヨタ自動車\n9984.T, ソフトバンクG\n\n(コードだけでもOK):\n8306.T\n8316.T", 
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

    # 5. グループの削除
    if active_group != "基本グループ":
        if st.button(f"🗑️ 「{active_group}」グループごと削除", use_container_width=True):
            del groups[active_group]
            save_groups(groups)
            st.success(f"グループ「{active_group}」を削除しました。")
            st.rerun()

st.divider()

# ★ スキャン設定と実行
selected_scan_group = st.selectbox("🎯 スキャンを実行するグループを選択", list(groups.keys()))

threshold_percent = st.number_input(
    "アラートを出す回転率の閾値（%）",
    min_value=1.0,
    max_value=200.0,
    value=5.0,
    step=1.0,
    help="直近5営業日のうち、この数値以上の回転率になった日がある銘柄を抽出します。"
)

if st.button("今すぐスキャンを実行（直近5営業日）", use_container_width=True):
    stocks = groups[selected_scan_group]
    total_stocks = len(stocks)
    
    if total_stocks == 0:
        st.warning(f"「{selected_scan_group}」には銘柄が登録されていません。上の設定画面から追加してください。")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = []
        alert_count = 0
        
        for i, info in enumerate(stocks):
            ticker = info["ticker"]
            name = info["name"]
            
            status_text.text(f"スキャン中... ({i+1}/{total_stocks}): {name} を確認しています")
            progress_bar.progress((i + 1) / total_stocks)
            
            try:
                stock = yf.Ticker(ticker)
                history = stock.history(period="10d")
                
                if history.empty:
                    continue 
                
                shares_outstanding = stock.info.get('sharesOutstanding')
                
                if shares_outstanding is None or shares_outstanding <= 0:
                    continue 
                
                recent_history = history.tail(5)
                
                for idx, row in recent_history.iterrows():
                    daily_volume = row['Volume']
                    date_str = idx.strftime('%Y/%m/%d')
                    turnover_rate = (daily_volume / shares_outstanding) * 100
                    
                    if turnover_rate >= threshold_percent:
                        alert_count += 1
                        results.append({
                            "日付": date_str,
                            "銘柄名": name,
                            "コード": ticker,
                            "回転率 (%)": round(turnover_rate, 2),
                        })
                
            except Exception:
                pass 
            
            time.sleep(SLEEP_TIME)
        
        status_text.text("すべてのスキャンが完了しました！")
        
        if results:
            st.success(f"スキャン完了！ 直近5営業日の中で計 {alert_count} 件の過熱（閾値超え）が発見されました。")
            df_results = pd.DataFrame(results)
            df_results = df_results.sort_values("日付", ascending=False)
            st.dataframe(df_results, use_container_width=True, hide_index=True)
        else:
            st.info(f"スキャン完了！ 直近5営業日の中で閾値（{threshold_percent}%）を超えた銘柄はありませんでした。")
