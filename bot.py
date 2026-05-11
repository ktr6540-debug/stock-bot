import os
import pandas as pd
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from alpha_vantage.timeseries import TimeSeries
from openai import OpenAI

# --- Railway 환경 변수에서 API 키 읽어오기 ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")
ALPHA_KEY = os.getenv("ALPHAVANTAGE_API_KEY")  # Railway에 등록된 이름과 동일

# --- 데이터 & AI 클라이언트 초기화 ---
ts = TimeSeries(key=ALPHA_KEY, output_format="pandas")
ai = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com/v1")

# --- 텔레그램 명령어 처리 ---
async def start(update: Update, context):
    await update.message.reply_text(
        "👋 안녕하세요! 투자 분석 봇입니다.\n"
        "종목 심볼(예: AAPL, TSLA, 005930.KS)을 보내주시면 AI가 분석해드립니다."
    )

async def analyze(update: Update, context):
    symbol = update.message.text.upper().strip()
    await update.message.reply_text(f"🔍 {symbol} 분석 중... 잠시만 기다려 주세요 ⏳")
    
    try:
        # Alpha Vantage에서 최근 30일 일봉 데이터 가져오기
        data, _ = ts.get_daily(symbol=symbol, outputsize="compact")
        close_prices = data["4. close"].head(30).to_string()

        # DeepSeek V4에 분석 요청
        response = ai.chat.completions.create(
            model="deepseek-v4-flash",  # 또는 deepseek-v4-pro
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 전문 투자 분석가입니다. "
                        "주어진 주가 데이터를 바탕으로 다음 내용을 분석해주세요:\n"
                        "- 최근 추세 (상승/하락/횡보)\n"
                        "- 주요 지지선과 저항선\n"
                        "- 거래량 동향 (가능한 경우)\n"
                        "- 단기 투자 의견 (보수적 관점)"
                    )
                },
                {
                    "role": "user",
                    "content": f"{symbol} 최근 30일 종가 데이터:\n{close_prices}\n\n위 데이터를 분석해주세요."
                }
            ],
            temperature=1.0,
            top_p=1.0
        )

        analysis = response.choices[0].message.content

        # 텔레그램 메시지 길이 제한(4096자) 처리
        if len(analysis) > 4000:
            for i in range(0, len(analysis), 4000):
                await update.message.reply_text(analysis[i:i+4000])
        else:
            await update.message.reply_text(f"📊 {symbol} 분석 결과:\n\n{analysis}")

    except Exception as e:
        await update.message.reply_text(f"❌ 오류가 발생했습니다: {e}")

# --- 메인 실행 (폴링 방식) ---
def main():
    # 텔레그램 봇 애플리케이션 생성
    app = Application.builder().token(TOKEN).build()

    # 명령어 핸들러 등록
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze))

    print("🤖 봇이 폴링 모드로 시작되었습니다...")
    # 폴링 시작 (에러 발생 시 자동 재시도)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
