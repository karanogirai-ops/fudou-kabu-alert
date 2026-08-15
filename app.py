import streamlit as st
import yfinance as yf
import requests
import pandas as pd
import csv
import datetime

# --- 1. 設定 ---
WEBHOOK_URL = "ここにDiscordのWebhook URLを貼り付けます"
THRESHOLD_PERCENT = 10.0  # アラート閾値（%）

# --- 2. 処理関数 ---
def send_discord(msg):
    requests.post(WEBHOOK_URL, json={"content": msg})

def load_stocks():
    stocks = []
    try:
        with open("stocks.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                stocks.append({
                    "ticker": row["Ticker"],
                    "name": row["Name"],
                    "float_shares": float(row["FloatShares"])
                })
    except Exception as e:
        st.error(f"CSVファイルの読み込みエラー: {e}")
    return stocks

# --- 3. 画面UIとメイン処理 ---
st.title("🚀 浮動株回転率チェッカー")
st.write("ボタンを押すと現在の相場をスキャンし、過熱銘柄をDiscordに通知します。")

if st.button("今すぐスキャンを実行"):
    with st.spinner("相場データを取得・計算中..."):
        stocks = load_stocks()
        results = []
        alert_count = 0
        
        for info in stocks:
            ticker = info["ticker"]
            name = info["name"]
            
            try:
                stock = yf.Ticker(ticker)
                history = stock.history(period="1d")
                
                if history.empty:
                    continue
                    
                current_price = history['Close'].iloc[0]
                daily_volume = history['Volume'].iloc[0]
                
                # ★ハイブリッド取得：yfinanceのデータを優先し、なければCSVの数値を使う
                auto_float = stock.info.get('floatShares')
                if auto_float is not None and auto_float > 0:
                    float_shares = auto_float
                else:
                    float_shares = info["float_shares"]
                
                # 回転率の計算
                turnover_rate = (daily_volume / float_shares) * 100
                
                # 閾値判定とDiscord通知
                if turnover_rate >= THRESHOLD_PERCENT:
                    alert_count += 1
                    prev_close = stock.info.get('previousClose', current_price)
                    price_change = ((current_price - prev_close) / prev_close) * 100
                    date_str = datetime.datetime.now().strftime("%Y/%m/%d %H:%M")
                    
                    msg = (
                        f"🚨 **浮動株回転率アラート({THRESHOLD_PERCENT}%超え)** 🚨\n"
                        f"・銘柄: **{name} ({ticker})**\n"
                        f"・回転率: **{turnover_rate:.2f} %**\n"
                        f"・上昇率: **{price_change:.2f} %**\n"
                        f"・確認日時: {date_str}"
                    )
                    send_discord(msg)
                    status = "🚨 通知済"
                else:
                    status = "🟢 正常"
                
                results.append({
                    "銘柄名": name,
                    "回転率 (%)": round(turnover_rate, 2),
                    "状態": status
                })
                
            except Exception as e:
                st.warning(f"{name} のデータ取得に失敗しました。")
        
        # 画面に結果を表示
        if results:
            st.success(f"スキャン完了！ {alert_count}件のアラートを送信しました。")
            st.table(pd.DataFrame(results))
        else:
            st.info("データが取得できませんでした。")