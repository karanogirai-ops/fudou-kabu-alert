import streamlit as st
import yfinance as yf
import pandas as pd
import csv
import datetime
import time

# --- 1. 設定 ---
SLEEP_TIME = 0.5         # YahooからBANされないための待機時間（秒）

# --- 2. 処理関数 ---
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

# --- 3. セッション状態の初期化 ---
if "groups" not in st.session_state:
    st.session_state.groups = {
        "基本グループ": load_default_stocks()
    }

# --- 4. 画面UI ---
st.title("🚀 株式回転率チェッカー（分割スキャン対応）")
st.write("銘柄をグループ（100社単位など）に分けて管理し、安全にスキャンを実行します。")

# ★ グループ＆銘柄の管理セクション
with st.expander("⚙️ グループの作成・名前変更・銘柄追加", expanded=False):
    
    # 新規グループの作成
    col_g1, col_g2 = st.columns([3, 1])
    with col_g1:
        new_group_name = st.text_input("新しいグループを作成（例: プライム100社）", key="new_group_input")
    with col_g2:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        if st.button("グループを作成"):
            if new_group_name and new_group_name not in st.session_state.groups:
                st.session_state.groups[new_group_name] = []
                st.success(f"グループ「{new_group_name}」を作成しました！")
                st.rerun()
            elif new_group_name in st.session_state.groups:
                st.warning("そのグループ名は既に存在します。")

    st.divider()

    # 管理対象グループの選択
    active_group = st.selectbox("編集対象のグループを選択", list(st.session_state.groups.keys()))
    
    # ★ 追加：グループ名の変更機能
    col_r1, col_r2 = st.columns([3, 1])
    with col_r1:
        rename_group_input = st.text_input("選択中グループの名前を変更", value=active_group, key=f"rename_{active_group}")
    with col_r2:
        st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
        if st.button("名前を変更"):
            if rename_group_input and rename_group_input != active_group:
                if rename_group_input in st.session_state.groups:
                    st.warning("そのグループ名は既に存在します。")
                else:
                    st.session_state.groups[rename_group_input] = st.session_state.groups.pop(active_group)
                    st.success(f"「{active_group}」を「{rename_group_input}」に変更しました！")
                    st.rerun()

    st.markdown(f"**現在の「{active_group}」の登録数:** {len(st.session_state.groups[active_group])} 銘柄")
    if st.session_state.groups[active_group]:
        st.dataframe(pd.DataFrame(st.session_state.groups[active_group]), use_container_width=True)

    # 銘柄の一括追加（テキストエリアでコピペ対応）
    st.markdown("**📥 テキストエリアからコピペで一括追加**")
    st.caption("改行区切りで「コード, 銘柄名」または「コードのみ」を一括入力できます。")
    bulk_input = st.text_area(
        "入力例:\n7203.T, トヨタ自動車\n9984.T, ソフトバンクG\n\n(コードだけでもOK):\n8306.T\n8316.T", 
        height=140
    )
    
    if st.button("このグループに一括追加"):
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
                
                st.session_state.groups[active_group].append({
                    "ticker": formatted_ticker,
                    "name": name
                })
                added_count += 1
            
            st.success(f"「{active_group}」に {added_count} 件の銘柄を追加しました！")
            st.rerun()

    # グループの削除
    if active_group != "基本グループ":
        if st.button(f"🗑️ 「{active_group}」グループごと削除"):
            del st.session_state.groups[active_group]
            st.success(f"グループ「{active_group}」を削除しました。")
            st.rerun()

st.divider()

# ★ スキャン設定と実行
selected_scan_group = st.selectbox("🎯 スキャンを実行するグループを選択", list(st.session_state.groups.keys()))

threshold_percent = st.number_input(
    "アラートを出す回転率の閾値（%）",
    min_value=1.0,
    max_value=200.0,
    value=5.0,
    step=1.0,
    help="この数値以上の回転率になった銘柄を「過熱」として抽出します。"
)

if st.button("今すぐスキャンを実行"):
    stocks = st.session_state.groups[selected_scan_group]
    total_stocks = len(stocks)
    
    if total_stocks == 0:
        st.warning(f"「{selected_scan_group}」には銘柄が登録されていません。上の設定画面から追加してください。")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = []
        alert_count = 0
        now = datetime.datetime.now()
        
        for i, info in enumerate(stocks):
            ticker = info["ticker"]
            name = info["name"]
            
            status_text.text(f"スキャン中... ({i+1}/{total_stocks}): {name} を確認しています")
            progress_bar.progress((i + 1) / total_stocks)
            
            try:
                stock = yf.Ticker(ticker)
                history = stock.history(period="5d")
                
                if history.empty:
                    continue 
                    
                latest_date = history.index[-1].date()
                
                if now.hour < 16 and latest_date == now.date() and len(history) >= 2:
                    target_index = -2
                else:
                    target_index = -1
                    
                target_data = history.iloc[target_index]
                daily_volume = target_data['Volume']
                target_date_str = target_data.name.strftime('%Y/%m/%d')
                
                shares_outstanding = stock.info.get('sharesOutstanding')
                
                if shares_outstanding is None or shares_outstanding <= 0:
                    continue 
                
                turnover_rate = (daily_volume / shares_outstanding) * 100
                
                if turnover_rate >= threshold_percent:
                    alert_count += 1
                    status = f"🚨 過熱 ({target_date_str})"
                    
                    results.append({
                        "銘柄名": name,
                        "回転率 (%)": round(turnover_rate, 2),
                        "状態": status
                    })
                
            except Exception:
                pass 
            
            time.sleep(SLEEP_TIME)
        
        status_text.text("すべてのスキャンが完了しました！")
        
        if results:
            st.success(f"スキャン完了！ {alert_count}件の過熱銘柄が発見されました。")
            st.table(pd.DataFrame(results))
        else:
            st.info(f"スキャン完了！ 今回、閾値（{threshold_percent}%）を超えた銘柄はありませんでした。")
