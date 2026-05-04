import os
import asyncio
import pandas as pd
from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from alpha_vantage.timeseries import TimeSeries
from openai import OpenAI

# --- API 키는 Railway 환경변수에서 가져옴 ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
ALPHA_KEY = os.getenv("ALPHA_VANTAGE_KEY")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY")

# Railway가 자동으로 할당하는 포트 & 도메인
PORT = int(os.getenv("PORT", "8080"))
RAILWAY_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "localhost")

# 데이터 & AI 클라이언트
ts = TimeSeries(key=ALPHA_KEY, output_format="pandas")
ai = OpenAI(api_key=DEEPSEEK_KEY, base_url="https://api.deepseek.com/v1")

# --- 텔레그램 명령어 처리 ---
async def start(update: Update, context):
    await update.message.reply_text("종목 심볼(예: AAPL)을 보내주세요!")

async def analyze(update: Update, context):
    symbol = update.message.text.upper().strip()
    await update.message.reply_text(f"{symbol} 분석 중... 조금만 기다려 주세요 ⏳")
    try:
        data, _ = ts.get_daily(symbol=symbol, outputsize="compact")
        close_prices = data["4. close"].head(30).to_string()
        response = ai.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "당신은 전문 투자 분석가입니다. 주어진 주가 데이터를 바탕으로 추세, 지지/저항선, 간단한 투자 의견을 알려주세요."},
                {"role": "user", "content": f"{symbol} 최근 30일 종가:\n{close_prices}\n\n분석해주세요."}
            ]
        )
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        await update.message.reply_text(f"오류 발생: {e}")

# --- 메인 서버 ---
async def main():
    # 텔레그램 봇 애플리케이션
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze))

    # 웹훅 설정 (Railway 도메인으로 자동 연결)
    webhook_url = f"https://{RAILWAY_DOMAIN}/telegram"
    await app.bot.set_webhook(webhook_url)

    # Railway health check용 웹 서버
    async def health(request):
        return web.Response(text="OK")
    web_app = web.Application()
    web_app.add_routes([web.get("/", health)])
    # 텔레그램 업데이트 받을 경로
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=webhook_url,
        url_path="telegram"
    )

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    # 서버 종료될 때까지 대기
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
