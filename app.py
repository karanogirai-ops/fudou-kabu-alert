import streamlit as st
import yfinance as yf
import pandas as pd
import csv
import datetime

# --- 1. 設定 ---
# 発行済株式数ベースは数字が小さくなるため、閾値を5%に下げて設定します
THRESHOLD_PERCENT = 5.0  

# --- 2. 処理関数 ---
def load_stocks():
    stocks = []
    try:
        with open("stocks.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # ★ FloatShares（浮動株）の読み込みを完全に廃止しました！
                # これからはTickerとNameだけをリストとして読み込みます。
                stocks.append({
                    "ticker": row["Ticker"],
                    "name": row["Name"]
                })
    except Exception as e:
        st.error(f"CSVファイルの読み込みエラー: {e}")
    return stocks

# --- 3. 画面UIとメイン処理 ---
st.title("🚀 株式回転率チェッカー（完全自動版）")
st.write("ボタンを押すと現在の相場をスキャンし、画面上に結果を表示します。")
st.caption("※計算基準を「発行済株式数」に変更し、株数の自動取得化を実現しました。")

if st.button("今すぐスキャンを実行"):
    with st.spinner("相場データと発行済株式数を自動取得中..."):
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
                
                # エラー切り分け①：出来高データがない場合
                if history.empty:
                    st.warning(f"📉 {name} ({ticker}): 株価・出来高データが取得できません（yfinance未対応）。")
                    continue
                    
                latest_date = history.index[-1].date()
                
                # 16時を境界に、参照するデータを切り替える
                if now.hour < 16 and latest_date == now.date() and len(history) >= 2:
                    target_index = -2
                else:
                    target_index = -1
                    
                target_data = history.iloc[target_index]
                daily_volume = target_data['Volume']
                target_date_str = target_data.name.strftime('%Y/%m/%d')
                
                # ★ 新ロジック：発行済株式数（sharesOutstanding）を完全自動取得！
                shares_outstanding = stock.info.get('sharesOutstanding')
                
                # エラー切り分け②：発行済株式数が不明な場合
                if shares_outstanding is None or shares_outstanding <= 0:
                    st.warning(f"❓ {name} ({ticker}): 発行済株式数が取得できないため計算できません。")
                    continue
                
                # 回転率の計算（発行済株式数ベース）
                turnover_rate = (daily_volume / shares_outstanding) * 100
                
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
