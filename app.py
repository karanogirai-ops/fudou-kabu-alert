import streamlit as st
import yfinance as yf
import pandas as pd
import csv
import datetime
import time  # 待機時間を制御するためのライブラリを追加

# --- 1. 設定 ---
THRESHOLD_PERCENT = 5.0  # 過熱と判定する閾値（%）
SLEEP_TIME = 0.5         # ★YahooからBANされないための待機時間（秒）

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

if st.button("今すぐスキャンを実行"):
    stocks = load_stocks()
    total_stocks = len(stocks)
    
    if total_stocks == 0:
        st.warning("銘柄リストが空です。stocks.csvを確認してください。")
    else:
        # ★ 進捗状況（プログレスバー）の表示準備
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results = []
        alert_count = 0
        now = datetime.datetime.now()
        
        for i, info in enumerate(stocks):
            ticker = info["ticker"]
            name = info["name"]
            
            # ★ 画面に進捗状況をテキストとバーで表示
            status_text.text(f"スキャン中... ({i+1}/{total_stocks}): {name} を確認しています")
            progress_bar.progress((i + 1) / total_stocks)
            
            try:
                stock = yf.Ticker(ticker)
                history = stock.history(period="5d")
                
                if history.empty:
                    continue  # データがない場合はスキップ
                    
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
                    continue  # 株数が不明な場合もスキップ（大量処理中は警告を省いて画面を綺麗に保つ）
                
                turnover_rate = (daily_volume / shares_outstanding) * 100
                
                if turnover_rate >= THRESHOLD_PERCENT:
                    alert_count += 1
                    status = f"🚨 過熱 ({target_date_str})"
                    
                    # ★ 閾値を超えた「過熱銘柄」だけをリストに追加して画面に表示する
                    results.append({
                        "銘柄名": name,
                        "回転率 (%)": round(turnover_rate, 2),
                        "状態": status
                    })
                
            except Exception as e:
                pass  # 大量処理中は細かいエラーで止めず、無視して次へ進む
            
            # ★ 次の銘柄に行く前に0.5秒休憩する（アクセス制限BAN対策）
            time.sleep(SLEEP_TIME)
        
        # 処理完了後の画面表示
        status_text.text("すべてのスキャンが完了しました！")
        
        if results:
            st.success(f"スキャン完了！ {alert_count}件の過熱銘柄が発見されました。")
            st.table(pd.DataFrame(results))
        else:
            st.info(f"スキャン完了！ 今回、閾値（{THRESHOLD_PERCENT}%）を超えた銘柄はありませんでした。")
