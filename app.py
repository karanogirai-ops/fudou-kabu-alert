import streamlit as st
import yfinance as yf
import pandas as pd
import csv
import datetime
import time

# --- 1. 設定 ---
SLEEP_TIME = 0.5         # YahooからBANされないための待機時間（秒）

# --- 2. 処理関数 ---
def load_stocks():
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
        st.error(f"CSVファイルの読み込みエラー: {e}")
    return stocks

# --- 3. 画面UIとメイン処理 ---
st.title("🚀 株式回転率チェッカー（大量スキャン対応版）")
st.write("ボタンを押すと現在の相場をスキャンし、画面上に結果を表示します。")
st.caption("※計算基準を「発行済株式数」に変更し、株数の自動取得化を実現しました。")

# ★ 閾値設定（上限を200.0%に設定）
threshold_percent = st.number_input(
    "アラートを出す回転率の閾値（%）",
    min_value=1.0,
    max_value=200.0,  # 上限を200%に変更
    value=5.0,        # 標準値
    step=1.0,         # 1ごとに変更
    help="この数値以上の回転率になった銘柄を「過熱」として抽出します。"
)

if st.button("今すぐスキャンを実行"):
    stocks = load_stocks()
    total_stocks = len(stocks)
    
    if total_stocks == 0:
        st.warning("銘柄リストが空です。stocks.csvを確認してください。")
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
