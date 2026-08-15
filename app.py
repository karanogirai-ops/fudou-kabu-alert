import streamlit as st
import yfinance as yf
import pandas as pd
import csv
import datetime

# --- 1. 設定 ---
THRESHOLD_PERCENT = 10.0  # 過熱と判定する閾値（%）

# --- 2. 処理関数 ---
def load_stocks():
    stocks = []
    try:
        with open("stocks.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    fs = float(row["FloatShares"])
                except ValueError:
                    fs = 0.0
                stocks.append({
                    "ticker": row["Ticker"],
                    "name": row["Name"],
                    "float_shares": fs
                })
    except Exception as e:
        st.error(f"CSVファイルの読み込みエラー: {e}")
    return stocks

# --- 3. 画面UIとメイン処理 ---
st.title("🚀 浮動株回転率チェッカー")
st.write("ボタンを押すと現在の相場をスキャンし、画面上に結果を表示します。")

if st.button("今すぐスキャンを実行"):
    with st.spinner("相場データを取得・計算中..."):
        stocks = load_stocks()
        results = []
        alert_count = 0
        now = datetime.datetime.now()
        
        for info in stocks:
            ticker = info["ticker"]
            name = info["name"]
            
            try:
                stock = yf.Ticker(ticker)
                history = stock.history(period="5d")
                
                # エラー切り分け①：出来高（チャート）データがない場合
                if history.empty:
                    st.warning(f"📉 {name} ({ticker}): 出来高データが取得できません（yfinance未対応）。")
                    continue
                    
                latest_date = history.index[-1].date()
                
                # 16時を境界に、参照するデータを切り替える判定ロジック
                if now.hour < 16 and latest_date == now.date() and len(history) >= 2:
                    target_index = -2
                else:
                    target_index = -1
                    
                target_data = history.iloc[target_index]
                daily_volume = target_data['Volume']
                target_date_str = target_data.name.strftime('%Y/%m/%d')
                
                # ハイブリッド取得：yfinanceのデータを優先し、なければCSVの数値を使う
                auto_float = stock.info.get('floatShares')
                if auto_float is not None and auto_float > 0:
                    float_shares = auto_float
                else:
                    float_shares = info["float_shares"]
                
                # エラー切り分け②：浮動株数が不明（0）な場合
                if float_shares <= 0:
                    st.warning(f"❓ {name} ({ticker}): 浮動株数が不明なため計算できません（CSVを確認してください）。")
                    continue
                
                # 回転率の計算
                turnover_rate = (daily_volume / float_shares) * 100
                
                # 閾値判定
                if turnover_rate >= THRESHOLD_PERCENT:
                    alert_count += 1
                    status = f"🚨 過熱 ({target_date_str})"
                else:
                    status = f"🟢 正常 ({target_date_str})"
                
                results.append({
                    "銘柄名": name,
                    "回転率 (%)": round(turnover_rate, 2),
                    "状態": status
                })
                
            except Exception as e:
                # エラー切り分け③：その他の予期せぬエラー
                st.error(f"⚠️ {name} ({ticker}): 予期せぬエラーが発生しました（詳細: {e}）")
        
        # 画面に結果を表示
        if results:
            st.success(f"スキャン完了！ {alert_count}件の過熱銘柄が見つかりました。")
            st.table(pd.DataFrame(results))
        else:
            st.info("正常に計算できたデータがありませんでした。")
