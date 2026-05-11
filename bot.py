import os

print("TELEGRAM_TOKEN exists:", bool(os.getenv("TELEGRAM_TOKEN")))
print("DEEPSEEK_API_KEY exists:", bool(os.getenv("DEEPSEEK_API_KEY")))
print("ALPHAVANTAGE_API_KEY exists:", bool(os.getenv("ALPHAVANTAGE_API_KEY")))
import asyncio
from aiohttp import web

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

from alpha_vantage.timeseries import TimeSeries
from openai import OpenAI


# ======================================
# 환경변수 불러오기
# ======================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY")

# Railway 포트
PORT = int(os.getenv("PORT", "8080"))

# Railway 도메인
# 반드시 본인 Railway 도메인으로 수정!!
RAILWAY_DOMAIN = "web-production-56619.up.railway.app"


# ======================================
# 환경변수 체크
# ======================================
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN 환경변수가 없습니다.")

if not DEEPSEEK_API_KEY:
    raise ValueError("DEEPSEEK_API_KEY 환경변수가 없습니다.")

if not ALPHAVANTAGE_API_KEY:
    raise ValueError("ALPHAVANTAGE_API_KEY 환경변수가 없습니다.")


# ======================================
# Alpha Vantage
# ======================================
ts = TimeSeries(
    key=ALPHAVANTAGE_API_KEY,
    output_format="pandas"
)


# ======================================
# DeepSeek
# ======================================
ai = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com/v1"
)


# ======================================
# /start
# ======================================
async def start(update: Update, context):
    await update.message.reply_text(
        "안녕하세요 👋\n\n"
        "미국 주식 심볼을 보내주세요!\n\n"
        "예시:\n"
        "AAPL\n"
        "TSLA\n"
        "MSFT\n"
        "NVDA"
    )


# ======================================
# 종목 분석
# ======================================
async def analyze(update: Update, context):

    symbol = update.message.text.upper().strip()

    await update.message.reply_text(
        f"{symbol} 분석 중입니다 ⏳"
    )

    try:

        # 최근 주가 데이터 가져오기
        data, meta_data = ts.get_daily(
            symbol=symbol,
            outputsize="compact"
        )

        # 최근 30일 종가
        close_prices = data["4. close"].head(30)

        # 문자열 변환
        close_text = close_prices.to_string()

        # DeepSeek 분석
        response = ai.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 전문 투자 분석가입니다.\n"
                        "주어진 주가 데이터를 분석해서:\n"
                        "- 현재 추세\n"
                        "- 지지선\n"
                        "- 저항선\n"
                        "- 단기 전망\n"
                        "- 투자 리스크\n"
                        "- 투자 의견\n"
                        "을 한국어로 쉽게 설명해주세요."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"{symbol} 최근 30일 종가 데이터:\n\n"
                        f"{close_text}\n\n"
                        "분석해주세요."
                    )
                }
            ],
            temperature=0.7,
        )

        result = response.choices[0].message.content

        await update.message.reply_text(result)

    except Exception as e:

        await update.message.reply_text(
            f"오류 발생:\n{str(e)}"
        )


# ======================================
# Health Check
# ======================================
async def health(request):
    return web.Response(text="Bot is running!")


# ======================================
# 메인 실행
# ======================================
async def main():

    # 텔레그램 앱 생성
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # 핸들러 등록
    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            analyze
        )
    )

    # 웹훅 URL
    webhook_url = f"https://{RAILWAY_DOMAIN}/telegram"

    # 웹훅 설정
    await app.bot.set_webhook(webhook_url)

    # 앱 초기화
    await app.initialize()
    await app.start()

    # 웹훅 시작
    await app.updater.start_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path="telegram",
        webhook_url=webhook_url,
    )

    # Health Check 서버
    web_app = web.Application()

    web_app.router.add_get("/", health)

    runner = web.AppRunner(web_app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    print("Bot started successfully!")

    # 무한 실행 유지
    await asyncio.Event().wait()


# ======================================
# 시작
# ======================================
if __name__ == "__main__":
    asyncio.run(main())
