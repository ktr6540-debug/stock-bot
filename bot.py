import os
import asyncio
import json
import hmac
import hashlib
import base64
import time
from datetime import datetime
import pandas as pd
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from openai import OpenAI

# Alpha Vantage
from alpha_vantage.timeseries import TimeSeries

# FinanceDataReader (한국 주식 데이터)
import FinanceDataReader as fdr

# ============================================================
# 1. 환경 변수 관리
# ============================================================
TELEGRAM_TOKEN          = os.getenv("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY        = os.getenv("DEEPSEEK_API_KEY")
ALPHA_VANTAGE_KEY       = os.getenv("ALPHAVANTAGE_API_KEY")

# OKX (듀얼 인베스트먼트)
OKX_API_KEY             = os.getenv("OKX_API_KEY")
OKX_SECRET_KEY          = os.getenv("OKX_SECRET_KEY")
OKX_PASSPHRASE          = os.getenv("OKX_PASSPHRASE")

# SerpAPI (뉴스 검색)
SERPAPI_KEY             = os.getenv("SERPAPI_KEY")

# OpenDART (한국 공시 데이터)
DART_API_KEY            = os.getenv("DART_API_KEY")  # OpenDART API 키

# ----------------------------------------------------------
# AI 클라이언트
# ----------------------------------------------------------
ai_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com/v1")

# ----------------------------------------------------------
# Alpha Vantage TimeSeries
# ----------------------------------------------------------
ts = TimeSeries(key=ALPHA_VANTAGE_KEY, output_format="pandas")

# ============================================================
# 2. 유틸 함수들
# ============================================================
def get_price_data_alpha(symbol: str, days: int = 30):
    """Alpha Vantage에서 일봉 종가 데이터를 가져옴 (미국 주식 위주)"""
    data, _ = ts.get_daily(symbol=symbol, outputsize="compact")
    return data["4. close"].head(days)

def get_price_data_fdr(symbol: str, country: str = "KR", days: int = 30):
    """FinanceDataReader에서 한국/미국 주식의 종가 데이터를 가져옴"""
    # symbol 형식: "005930" (한국), "AAPL" (미국)
    if country.upper() == "KR":
        full_symbol = symbol  # 이미 종목코드 형태라고 가정
    else:
        full_symbol = symbol  # AAPL, TSLA 등
    df = fdr.DataReader(full_symbol)
    if df.empty:
        raise ValueError(f"{full_symbol}에 대한 주가 데이터를 찾을 수 없습니다.")
    return df["Close"].tail(days)

# OKX API 인증 헤더 생성
def okx_headers(method, path, body=""):
    timestamp = str(int(time.time()))
    message = timestamp + method + path + body
    mac = hmac.new(
        OKX_SECRET_KEY.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    signature = base64.b64encode(mac).decode()
    return {
        "OK-ACCESS-KEY": OKX_API_KEY,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
        "Content-Type": "application/json"
    }

# SerpAPI 뉴스 검색
def search_news(query: str, num: int = 5):
    base_url = "https://serpapi.com/search"
    params = {
        "q": query + " 주식 또는 투자 뉴스",
        "tbm": "nws",
        "api_key": SERPAPI_KEY,
        "num": num,
        "hl": "ko",
        "gl": "kr"
    }
    resp = requests.get(base_url, params=params)
    if resp.status_code != 200:
        return []
    result = resp.json()
    news_list = result.get("news_results", [])
    return [{"title": n["title"], "link": n["link"], "snippet": n.get("snippet", "")} for n in news_list]

# OpenDART 회사명 → 고유번호 매핑 (간단한 사전, 필요시 확장)
def get_dart_corp_code(company_name: str):
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    params = {"crtfc_key": DART_API_KEY}
    # 실제로는 xml 파싱이 필요하지만, 간단히 자주 쓰는 종목만 사전 매핑
    mapping = {
        "삼성전자": "00126380",
        "SK하이닉스": "00164779",
        "현대차": "00164788",
        "NAVER": "00179984",
        "카카오": "00259578"
    }
    return mapping.get(company_name, None)

# OpenDART 재무제표 일부 가져오기 (예: 손익계산서)
def get_dart_financial(corp_code: str, year: str = "2025", quarter: str = "4"):
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bsns_year": year,
        "reprt_code": "1101" + quarter,  # 11011: 1분기, 11013: 3분기 등
        "fs_div": "OFS"  # 연결재무제표
    }
    resp = requests.get(url, params=params)
    if resp.status_code == 200:
        data = resp.json()
        if data.get("status") == "000":
            return data.get("list", [])
    return []

# ============================================================
# 3. 봇 명령어 처리
# ============================================================

# --- 시작 / 도움말 ---
async def start(update: Update, context):
    await update.message.reply_text(
        "👋 주식/코인 분석 봇입니다!\n\n"
        "📈 기술적 분석: /analyze AAPL\n"
        "💰 가치 평가: /value AAPL\n"
        "💱 듀얼 인베스트: /dual BTC\n"
        "📰 뉴스 분석: /news 삼성전자\n"
        "🇰🇷 한국 주식: /kvalue 삼성전자\n"
        "❓ 도움말: /help"
    )

async def help_cmd(update: Update, context):
    await update.message.reply_text(
        "/analyze [심볼] : 최근 30일 주가 기술적 분석\n"
        "/value [심볼] : PER, PBR 등 기본적 분석\n"
        "/dual [코인] : OKX 듀얼 인베스트먼트 상품 추천\n"
        "/news [종목명] : 최신 뉴스 검색 후 AI 요약\n"
        "/kvalue [회사명] : 한국 주식 재무 분석 (OpenDART+FDR)"
    )

# --- 기술적 분석 ---
async def analyze(update: Update, context):
    if not context.args:
        await update.message.reply_text("사용법: /analyze AAPL")
        return
    symbol = context.args[0].upper().strip()
    await update.message.reply_text(f"🔍 {symbol} 기술적 분석 중... ⏳")
    try:
        # 한국 주식인지 확인 (종목코드가 숫자 6자리 or .KS 포함)
        if symbol.isdigit() and len(symbol) == 6:
            close_prices = get_price_data_fdr(symbol, country="KR")
        elif ".KS" in symbol:
            close_prices = get_price_data_fdr(symbol.replace(".KS", ""), country="KR")
        else:
            close_prices = get_price_data_alpha(symbol)  # 미국 주식 등
        price_str = close_prices.to_string()
        response = ai_client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "전문 투자 분석가로서, 주가 데이터를 바탕으로 추세, 지지/저항선, 단기 의견을 제시하세요."},
                {"role": "user", "content": f"{symbol} 최근 30일 종가:\n{price_str}\n\n기술적 분석 부탁드립니다."}
            ]
        )
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {e}")

# --- 기본적 분석 (Alpha Vantage OVERVIEW) ---
async def value(update: Update, context):
    if not context.args:
        await update.message.reply_text("사용법: /value AAPL")
        return
    symbol = context.args[0].upper().strip()
    await update.message.reply_text(f"📊 {symbol} 기본적 분석 중... ⏳")
    try:
        overview_url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={symbol}&apikey={ALPHA_VANTAGE_KEY}"
        overview = requests.get(overview_url).json()
        if not overview:
            raise ValueError("기업 개요 정보를 가져오지 못했습니다.")
        per = overview.get("PERRatio", "N/A")
        pbr = overview.get("PriceToBookRatio", "N/A")
        eps = overview.get("EPS", "N/A")
        roe = overview.get("ReturnOnEquityTTM", "N/A")
        market_cap = overview.get("MarketCapitalization", "N/A")
        sector = overview.get("Sector", "N/A")
        overview_text = f"PER: {per}\nPBR: {pbr}\nEPS: {eps}\nROE(TTM): {roe}\n시가총액: {market_cap}\n섹터: {sector}"
        close_prices = get_price_data_alpha(symbol, days=10).to_string()
        response = ai_client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "가치 투자 전문가로서 현재 주가의 적정성을 평가해주세요."},
                {"role": "user", "content": f"{symbol} 재무 정보:\n{overview_text}\n\n최근 10일 종가:\n{close_prices}\n\n적정 주가 수준과 투자 의견을 제시해주세요."}
            ]
        )
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {e}")

# --- 한국 주식 분석 (FDR + OpenDART) ---
async def kvalue(update: Update, context):
    if not context.args:
        await update.message.reply_text("사용법: /kvalue 삼성전자")
        return
    company_name = " ".join(context.args)
    await update.message.reply_text(f"🇰🇷 {company_name} 재무 분석 중... ⏳")
    try:
        corp_code = get_dart_corp_code(company_name)
        if not corp_code:
            await update.message.reply_text(f"'{company_name}'은(는) 지원되지 않는 회사입니다. (예: 삼성전자, SK하이닉스 등)")
            return
        # OpenDART 재무제표 조회
        today = datetime.now()
        year = str(today.year - 1)  # 전년도 데이터
        financials = get_dart_financial(corp_code, year=year, quarter="4")
        # 필요한 지표 추출 (매출, 영업이익, 당기순이익 등)
        if not financials:
            await update.message.reply_text("재무제표 데이터를 가져오지 못했습니다.")
            return
        # 간단히 표시
        fin_text = "\n".join([f"{item['account_nm']}: {item['thstrm_amount']}" for item in financials[:10]])
        # 주가 데이터 (FDR)
        symbol_code = {"삼성전자":"005930", "SK하이닉스":"000660"}.get(company_name, None)
        if symbol_code:
            prices = get_price_data_fdr(symbol_code, country="KR").to_string()
        else:
            prices = "주가 데이터 없음"
        prompt = f"{company_name} 재무제표 (일부):\n{fin_text}\n\n최근 주가:\n{prices}\n\n분석해주세요."
        response = ai_client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "한국 주식 애널리스트로서, 주어진 재무 데이터와 주가를 바탕으로 투자 의견을 제시하세요."},
                {"role": "user", "content": prompt}
            ]
        )
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {e}")

# --- 듀얼 인베스트먼트 (OKX) ---
async def dual(update: Update, context):
    if not context.args:
        await update.message.reply_text("사용법: /dual BTC")
        return
    base_ccy = context.args[0].upper().strip()
    await update.message.reply_text(f"💱 {base_ccy} 듀얼 인베스트먼트 상품 조회 중... ⏳")
    try:
        # OKX 듀얼 인베스트먼트 상품 목록 API
        path = f"/api/v5/finance/sfp/dcd/products?baseCcy={base_ccy}"
        full_url = f"https://www.okx.com{path}"
        headers = okx_headers("GET", path)
        resp = requests.get(full_url, headers=headers)
        if resp.status_code != 200:
            raise ValueError(f"OKX API 오류: {resp.text}")
        products = resp.json().get("data", [])
        if not products:
            await update.message.reply_text(f"{base_ccy}에 대한 듀얼 인베스트먼트 상품이 없습니다.")
            return
        # 필요한 필드만 추려서 전송
        simplified = []
        for p in products[:20]:  # 최대 20개
            simplified.append({
                "투자유형": p.get("investType", ""),
                "행사가": p.get("strikePrice", ""),
                "결제일": p.get("settleDate", ""),
                "연이율(APY)": p.get("apy", ""),
                "만기": p.get("tenor", ""),
                "최소투자": p.get("minInvest", ""),
                "상태": p.get("state", "")
            })
        data_json = json.dumps(simplified, ensure_ascii=False, indent=2)
        # DeepSeek 분석 요청
        response = ai_client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "암호화폐 듀얼 인베스트먼트 전문가입니다. 주어진 상품 목록을 분석하여 수익률, 리스크, 추천 상품을 제안하세요."},
                {"role": "user", "content": f"{base_ccy} 듀얼 인베스트먼트 상품:\n{data_json}\n\n추천 부탁드립니다."}
            ]
        )
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {e}")

# --- 뉴스 검색 분석 ---
async def news(update: Update, context):
    if not context.args:
        await update.message.reply_text("사용법: /news 테슬라")
        return
    query = " ".join(context.args)
    await update.message.reply_text(f"📰 '{query}' 관련 뉴스 수집 중... ⏳")
    try:
        articles = search_news(query)
        if not articles:
            await update.message.reply_text("관련 뉴스를 찾을 수 없습니다.")
            return
        # 뉴스 내용을 텍스트로 구성
        news_text = ""
        for i, art in enumerate(articles, 1):
            news_text += f"{i}. {art['title']} - {art['snippet']}\n"
        # DeepSeek 요약
        response = ai_client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "최신 금융 뉴스를 요약하고, 주요 내용과 시장에 미칠 영향을 분석하세요."},
                {"role": "user", "content": f"'{query}'에 대한 최신 뉴스:\n{news_text}\n\n분석 및 요약 부탁드립니다."}
            ]
        )
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {e}")

# --- 일반 텍스트 처리 ---
async def handle_text(update: Update, context):
    await update.message.reply_text(
        "⚠️ 명령어를 사용해주세요!\n"
        "/analyze, /value, /dual, /news, /kvalue"
    )

# ============================================================
# 4. 봇 실행
# ============================================================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("value", value))
    app.add_handler(CommandHandler("kvalue", kvalue))
    app.add_handler(CommandHandler("dual", dual))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🤖 모든 기능이 통합된 봇 시작...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
