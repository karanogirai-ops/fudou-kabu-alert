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
    except Exception as e:
        pass
    return stocks

# --- 3. セッション状態（画面上のリスト保持）の初期化 ---
if "stock_list" not in st.session_state:
    st.session_state.stock_list = load_default_stocks()

# --- 4. 画面UI ---
st.title("🚀 株式回転率チェッカー")
st.write("ボタンを押すと現在の相場をスキャンし、画面上に結果を表示します。")

# ★ 銘柄管理セクション（追加・削除機能）
with st.expander("⚙️ 監視銘柄の追加・削除・確認", expanded=False):
    st.subheader("現在の監視銘柄リスト")
    if st.session_state.stock_list:
        df_list = pd.DataFrame(st.session_state.stock_list)
        st.dataframe(df_list, use_container_width=True)
    else:
        st.write("登録されている銘柄がありません。")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**➕ 銘柄の追加**")
        new_ticker = st.text_input("銘柄コード（例: 7203.T）", key="add_ticker")
        new_name = st.text_input("銘柄名（例: トヨタ自動車）", key="add_name")
        if st.button("銘柄を追加"):
            if new_ticker and new_name:
                # 末尾に .T がない場合は自動付与
                formatted_ticker = new_ticker.upper() if new_ticker.endswith(".T") else f"{new_ticker}.T"
                st.session_state.stock_list.append({"ticker": formatted_ticker, "name": new_name})
                st.success(f"{new_name} ({formatted_ticker}) を追加しました！")
                st.rerun()
            else:
                st.warning("コードと名前の両方を入力してください。")

    with col2:
        st.markdown("**🗑️ 銘柄の削除**")
        if st.session_state.stock_list:
            delete_options = [f"{s['name']} ({s['ticker']})" for s in st.session_state.stock_list]
            selected_to_delete = st.selectbox("削除する銘柄を選択", delete_options)
            if st.button("選択した銘柄を削除"):
                st.session_state.stock_list = [
                    s for s in st.session_state.stock_list 
                    if f"{s['name']} ({s['ticker']})" != selected_to_delete
                ]
                st.success("削除しました！")
                st.rerun()

st.divider()

# ★ 閾値設定
threshold_percent = st.number_input(
    "アラートを出す回転率の閾値（%）",
    min_value=1.0,
    max_value=200.0,
    value=5.0,
    step=1.0,
    help="この数値以上の回転率になった銘柄を「過熱」として抽出します。"
)

# ★ スキャン実行
if st.button("今すぐスキャンを実行"):
    stocks = st.session_state.stock_list
    total_stocks = len(stocks)
    
    if total_stocks == 0:
        st.warning("銘柄リストが空です。上の設定画面から銘柄を追加してください。")
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
                
            except Exception as e:
                pass 
            
            time.sleep(SLEEP_TIME)
        
        status_text.text("すべてのスキャンが完了しました！")
        
        if results:
            st.success(f"スキャン完了！ {alert_count}件の過熱銘柄が発見されました。")
            st.table(pd.DataFrame(results))
        else:
            st.info(f"スキャン完了！ 今回、閾値（{threshold_percent}%）を超えた銘柄はありませんでした。")
