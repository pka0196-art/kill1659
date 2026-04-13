import io
import math
import os
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf


# --------------------------------------------------
# 화면 설정
# --------------------------------------------------
st.set_page_config(
    page_title="키움 모의실시간 자동추천 TOP5",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1450px; padding-top: 1rem; padding-bottom: 2rem;}
    .card {
        padding: 1rem 1rem 0.85rem 1rem;
        border: 1px solid rgba(128,128,128,0.18);
        border-radius: 16px;
        margin-bottom: 0.9rem;
        min-height: 330px;
    }
    .rank-badge {
        display: inline-block;
        padding: 0.22rem 0.55rem;
        border-radius: 999px;
        border: 1px solid rgba(128,128,128,0.25);
        font-size: 0.85rem;
        font-weight: 700;
        margin-bottom: 0.45rem;
    }
    .title-row {
        font-size: 1.35rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
    }
    .subtle {
        color: #666;
        font-size: 0.92rem;
        margin-bottom: 0.45rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------
# 기본 종목 우주
# --------------------------------------------------
NAME_TO_CODE = {
    "삼성전자": "005930",
    "SK하이닉스": "000660",
    "한미반도체": "042700",
    "DB하이텍": "000990",
    "리노공업": "058470",
    "ISC": "095340",
    "동진쎄미켐": "005290",
    "제주반도체": "080220",
    "네패스아크": "330860",
    "원익IPS": "240810",
    "이오테크닉스": "039030",
    "휴림로봇": "090710",
    "레인보우로보틱스": "277810",
    "클로봇": "466100",
    "두산로보틱스": "454910",
    "에스피지": "058610",
    "유일로보틱스": "388720",
    "LIG넥스원": "079550",
    "한국항공우주": "047810",
    "한화에어로스페이스": "012450",
    "현대로템": "064350",
    "대한해운": "005880",
    "팬오션": "028670",
    "흥아해운": "003280",
    "KSS해운": "044450",
    "HMM": "011200",
    "LS ELECTRIC": "010120",
    "HD현대일렉트릭": "267260",
    "효성중공업": "298040",
    "두산에너빌리티": "034020",
    "에코프로": "086520",
    "에코프로비엠": "247540",
    "포스코퓨처엠": "003670",
    "금양": "001570",
    "엘앤에프": "066970",
    "리튬포어스": "073570",
    "에코플라스틱": "038110",
    "화신": "010690",
    "성우하이텍": "015750",
    "현대공업": "170030",
    "삼성중공업": "010140",
    "한화오션": "042660",
    "HD한국조선해양": "009540",
    "NAVER": "035420",
    "카카오": "035720",
    "더존비즈온": "012510",
    "솔트룩스": "304100",
    "넥스틸": "092790",
    "세아제강": "306200",
    "휴스틸": "005010",
    "하이스틸": "071090",
    "GS글로벌": "001250",
    "우리기술": "032820",
    "센서뷰": "321370",
}
CODE_TO_NAME = {v: k for k, v in NAME_TO_CODE.items()}

MARKET_UNIVERSE = list(NAME_TO_CODE.keys())

THEME_KEYWORDS = [
    "AI", "인공지능", "반도체", "HBM", "로봇", "휴머노이드", "방산", "리튬", "희토류",
    "전기차", "2차전지", "조선", "해운", "원전", "바이오", "제약", "데이터센터",
    "전력", "우주", "스페이스", "유가", "천연가스", "구리", "철강", "건설", "통신",
    "보안", "드론", "자동차", "플랫폼", "헬스케어"
]


# --------------------------------------------------
# 데이터 클래스
# --------------------------------------------------
@dataclass
class KiwoomConfig:
    appkey: str
    secretkey: str
    use_mock: bool = True

    @property
    def base_url(self) -> str:
        return "https://mockapi.kiwoom.com" if self.use_mock else "https://api.kiwoom.com"


@dataclass
class AnalysisResult:
    name: str
    code: str
    ticker: str
    market: str
    current_price: float | None
    price_note: str
    price_asof: str
    score: float
    grade: str
    setup: str
    trend: str
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    summary: str
    reasons: list[str]
    news_items: list[dict]
    disclosure_items: list[dict]
    themes: list[str]
    df: pd.DataFrame


# --------------------------------------------------
# 키움 REST 클라이언트
# --------------------------------------------------
class KiwoomClient:
    def __init__(self, config: KiwoomConfig):
        self.config = config
        self.token: str | None = None

    def issue_token(self) -> dict[str, Any]:
        url = f"{self.config.base_url}/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.appkey,
            "secretkey": self.config.secretkey,
        }
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        self.token = data.get("token")
        return data

    def _headers(self, api_id: str) -> dict[str, str]:
        if not self.token:
            self.issue_token()
        return {
            "authorization": f"Bearer {self.token}",
            "api-id": api_id,
            "cont-yn": "N",
            "next-key": "",
            "Content-Type": "application/json;charset=UTF-8",
        }

    def post(self, path: str, api_id: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.config.base_url}{path}"
        resp = requests.post(url, headers=self._headers(api_id), json=body, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_quote(self, code: str) -> dict[str, Any]:
        # 키움 공식 가이드의 주식호가요청 ka10004 사용
        return self.post("/api/dostk/mrkcond", "ka10004", {"stk_cd": code})


# --------------------------------------------------
# 유틸
# --------------------------------------------------
def resolve_stock_input(text: str) -> tuple[str, str, str, str]:
    raw = (text or "").strip()
    if not raw:
        return "", "", "", ""
    if raw.isdigit() and len(raw) == 6:
        code = raw
        name = CODE_TO_NAME.get(code, code)
    else:
        normalized = re.sub(r"\s+", "", raw).upper()
        code = ""
        name = raw
        for nm, cd in NAME_TO_CODE.items():
            if re.sub(r"\s+", "", nm).upper() == normalized:
                name = nm
                code = cd
                break
        if not code and raw.upper().endswith((".KS", ".KQ")) and len(raw.split(".")[0]) == 6:
            code = raw.split(".")[0]
            name = CODE_TO_NAME.get(code, code)
    if not code:
        return name, "", "", ""
    market = "KOSPI" if code.startswith(("0", "1", "2", "3")) else "KOSDAQ"
    ticker = f"{code}.KS" if market == "KOSPI" else f"{code}.KQ"
    return name, code, ticker, market


def safe_float(value, digits: int = 2):
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return round(float(value), digits)
    except Exception:
        return None


def format_price(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "-"
    return f"{float(value):,.0f}"


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift(1)).abs()
    low_close = (df["Low"] - df["Close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def enrich_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["SMA5"] = out["Close"].rolling(5).mean()
    out["SMA20"] = out["Close"].rolling(20).mean()
    out["SMA60"] = out["Close"].rolling(60).mean()
    out["EMA12"] = out["Close"].ewm(span=12, adjust=False).mean()
    out["EMA26"] = out["Close"].ewm(span=26, adjust=False).mean()
    out["MACD"] = out["EMA12"] - out["EMA26"]
    out["MACD_SIGNAL"] = out["MACD"].ewm(span=9, adjust=False).mean()
    out["RSI14"] = compute_rsi(out["Close"], 14)
    out["ATR14"] = compute_atr(out, 14)
    out["VOL_MA20"] = out["Volume"].rolling(20).mean()
    out["VOL_RATIO"] = out["Volume"] / out["VOL_MA20"].replace(0, np.nan)
    out["HIGH20"] = out["High"].rolling(20).max()
    out["LOW20"] = out["Low"].rolling(20).min()
    out["HIGH60"] = out["High"].rolling(60).max()
    return out


def compute_grade(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def decide_setup(row: pd.Series) -> tuple[str, str]:
    close = row["Close"]
    sma20 = row["SMA20"]
    sma60 = row["SMA60"]
    high20 = row["HIGH20"]
    vol_ratio = row["VOL_RATIO"]
    rsi = row["RSI14"]
    macd = row["MACD"]
    macd_signal = row["MACD_SIGNAL"]
    atr = row["ATR14"]

    vals = [sma20, sma60, high20, vol_ratio, rsi, macd, macd_signal, atr]
    if any(pd.isna(x) for x in vals):
        return "데이터부족", "지표 계산에 필요한 데이터가 충분하지 않습니다."

    near_breakout = close >= high20 * 0.985
    volume_ok = vol_ratio >= 1.4
    trend_ok = close > sma20 > sma60
    momentum_ok = macd > macd_signal and rsi >= 52

    if near_breakout and volume_ok and trend_ok and momentum_ok:
        return "돌파형", "20일 고점권 접근 + 거래량 동반 + 추세 정배열"

    pullback_zone = abs(close - sma20) <= atr * 0.9
    pullback_rsi = 43 <= rsi <= 60
    if trend_ok and pullback_zone and pullback_rsi:
        return "눌림목형", "상승 추세 안에서 20일선 근처 눌림"

    sideways = abs((row["HIGH20"] - row["LOW20"]) / close) <= 0.12
    if sideways and close >= sma20 and vol_ratio >= 1.0:
        return "박스상단대기", "변동성 압축 후 상단 돌파 대기"

    if close < sma20 < sma60:
        return "약세형", "이평선 역배열 구간"

    return "관망형", "명확한 진입 패턴이 약합니다."


def calculate_score(row: pd.Series, setup: str) -> tuple[float, list[str], str]:
    score = 0.0
    reasons = []

    close = row["Close"]
    sma20 = row["SMA20"]
    sma60 = row["SMA60"]
    rsi = row["RSI14"]
    macd = row["MACD"]
    macd_signal = row["MACD_SIGNAL"]
    vol_ratio = row["VOL_RATIO"]
    atr = row["ATR14"]
    high20 = row["HIGH20"]

    if close > sma20:
        score += 15
        reasons.append("현재가가 20일선 위")
    if sma20 > sma60:
        score += 15
        reasons.append("20일선이 60일선 위")
    if macd > macd_signal:
        score += 12
        reasons.append("MACD 방향 우세")
    if 45 <= rsi <= 68:
        score += 10
        reasons.append("RSI 과열 아님")
    elif rsi > 75:
        score -= 6
        reasons.append("RSI 과열 부담")
    if vol_ratio >= 1.4:
        score += 13
        reasons.append("거래량 증가")
    elif vol_ratio < 0.8:
        score -= 4
        reasons.append("거래량 약함")
    if close >= high20 * 0.985:
        score += 10
        reasons.append("최근 20일 고점권 접근")

    volatility_pct = (atr / close) * 100 if close else 0
    if 2 <= volatility_pct <= 7:
        score += 8
        reasons.append("변동성 적정")
    elif volatility_pct > 10:
        score -= 5
        reasons.append("변동성 과도")

    setup_bonus = {
        "돌파형": 20,
        "눌림목형": 16,
        "박스상단대기": 12,
        "관망형": 3,
        "데이터부족": -10,
        "약세형": -15,
    }.get(setup, 0)
    score += setup_bonus
    reasons.append(f"패턴 점수: {setup}")

    score = max(0, min(100, score))
    trend_text = "상승 우위" if close > sma20 > sma60 else "약세 또는 중립"
    return round(score, 1), reasons, trend_text


def calculate_technical_prices(row: pd.Series, setup: str, stop_pct: float = 0.07, reward_risk: float = 1.8) -> tuple[float | None, float | None, float | None]:
    close = float(row["Close"])
    sma5 = float(row["SMA5"]) if not pd.isna(row["SMA5"]) else close
    sma20 = float(row["SMA20"]) if not pd.isna(row["SMA20"]) else close
    high20 = float(row["HIGH20"]) if not pd.isna(row["HIGH20"]) else close
    low20 = float(row["LOW20"]) if not pd.isna(row["LOW20"]) else None
    atr = float(row["ATR14"]) if not pd.isna(row["ATR14"]) else close * 0.03

    if setup == "돌파형":
        entry = max(high20 * 1.003, close * 0.997)
    elif setup == "눌림목형":
        entry = min(close * 1.002, sma20 + atr * 0.2)
    elif setup == "박스상단대기":
        entry = high20 * 1.002
    elif setup == "약세형":
        entry = sma20 * 1.005
    else:
        entry = sma5

    stop = entry * (1 - stop_pct)
    if low20 and stop > low20:
        stop = min(stop, low20 * 0.997)

    risk = max(entry - stop, entry * 0.03)
    target = entry + risk * reward_risk
    return entry, stop, target


def extract_kiwoom_current_price(quote_json: dict[str, Any]) -> str:
    candidates = [
        "cur_prc", "cur_price", "now_prc", "stck_prpr", "price", "close", "cur",
        "sel_1th_pre_bid", "buy_1th_pre_bid"
    ]
    for key in candidates:
        if key in quote_json and str(quote_json.get(key, "")).strip():
            return str(quote_json.get(key))
    if isinstance(quote_json.get("data"), dict):
        data = quote_json["data"]
        for key in candidates:
            if key in data and str(data.get(key, "")).strip():
                return str(data.get(key))
    return "-"


def get_current_price_kiwoom_or_yf(client: KiwoomClient | None, code: str, ticker: str, fallback_close: float) -> tuple[float, str, str]:
    if client:
        try:
            q = client.get_quote(code)
            text = extract_kiwoom_current_price(q)
            num = int(str(text).replace(",", "").replace("+", "").replace("-", ""))
            if num > 0:
                return float(num), "kiwoom_quote", "키움 모의실시간 현재가 기준"
        except Exception:
            pass

    try:
        intraday = yf.download(
            ticker,
            period="1d",
            interval="1m",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if intraday is not None and not intraday.empty:
            if isinstance(intraday.columns, pd.MultiIndex):
                intraday.columns = intraday.columns.get_level_values(0)
            intraday = intraday.dropna(subset=["Close"])
            if not intraday.empty:
                return float(intraday["Close"].iloc[-1]), str(intraday.index[-1]), "1분봉 최근가 기준"
    except Exception:
        pass

    return float(fallback_close), "daily_close", "일봉 종가 기준"


def fetch_google_news(query: str, days: int = 14, max_items: int = 5) -> list[dict]:
    if not query:
        return []
    rss_url = f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    headers = {"User-Agent": "Mozilla/5.0"}
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    try:
        resp = requests.get(rss_url, timeout=12, headers=headers)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception:
        return []

    items = []
    seen = set()
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_raw = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else "출처미상"

        if not title or title in seen:
            continue

        published = None
        if pub_date_raw:
            try:
                published = parsedate_to_datetime(pub_date_raw)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
            except Exception:
                published = None

        if published and published < cutoff:
            continue

        seen.add(title)
        items.append({
            "title": title,
            "link": link,
            "source": source,
            "published": published.astimezone(timezone.utc).strftime("%Y-%m-%d") if published else "-",
        })
        if len(items) >= max_items:
            break
    return items


@st.cache_data(ttl=86400, show_spinner=False)
def load_dart_corp_codes(dart_key: str) -> pd.DataFrame:
    if not dart_key:
        return pd.DataFrame(columns=["corp_code", "corp_name", "stock_code"])
    url = "https://opendart.fss.or.kr/api/corpCode.xml"
    resp = requests.get(url, params={"crtfc_key": dart_key}, timeout=20)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = zf.namelist()[0]
        xml_bytes = zf.read(name)

    root = ET.fromstring(xml_bytes)
    rows = []
    for item in root.findall(".//list"):
        rows.append({
            "corp_code": (item.findtext("corp_code") or "").strip(),
            "corp_name": (item.findtext("corp_name") or "").strip(),
            "stock_code": (item.findtext("stock_code") or "").strip(),
        })
    return pd.DataFrame(rows)


def find_dart_corp_code(dart_key: str, name: str, code: str) -> str | None:
    if not dart_key:
        return None
    df = load_dart_corp_codes(dart_key)
    if df.empty:
        return None
    hit = df[df["stock_code"] == code]
    if not hit.empty:
        return str(hit.iloc[0]["corp_code"])
    hit = df[df["corp_name"] == name]
    if not hit.empty:
        return str(hit.iloc[0]["corp_code"])
    return None


def fetch_dart_disclosures(dart_key: str, corp_code: str | None, days: int = 30, max_items: int = 5) -> list[dict]:
    if not dart_key or not corp_code:
        return []

    end_de = datetime.now().strftime("%Y%m%d")
    bgn_de = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": dart_key,
        "corp_code": corp_code,
        "bgn_de": bgn_de,
        "end_de": end_de,
        "last_reprt_at": "Y",
        "page_no": 1,
        "page_count": max_items,
    }

    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    items = []
    for item in data.get("list", [])[:max_items]:
        rcept_no = str(item.get("rcept_no", "")).strip()
        viewer = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}" if rcept_no else ""
        items.append({
            "title": item.get("report_nm", ""),
            "date": item.get("rcept_dt", ""),
            "corp_name": item.get("corp_name", ""),
            "link": viewer,
        })
    return items


def detect_themes(titles: list[str]) -> list[str]:
    joined = " ".join(titles)
    out = []
    for kw in THEME_KEYWORDS:
        if kw.lower() in joined.lower() and kw not in out:
            out.append(kw)
    return out[:6]


def build_chart(df: pd.DataFrame, name: str) -> go.Figure:
    last_df = df.tail(90).copy()
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=last_df.index,
            open=last_df["Open"],
            high=last_df["High"],
            low=last_df["Low"],
            close=last_df["Close"],
            name="캔들",
        )
    )
    fig.add_trace(go.Scatter(x=last_df.index, y=last_df["SMA20"], mode="lines", name="SMA20"))
    fig.add_trace(go.Scatter(x=last_df.index, y=last_df["SMA60"], mode="lines", name="SMA60"))
    fig.update_layout(
        title=f"{name} 최근 90거래일 차트",
        xaxis_rangeslider_visible=False,
        height=480,
        margin=dict(l=10, r=10, t=45, b=10),
        legend=dict(orientation="h"),
    )
    return fig


def analyze_one(
    stock_input: str,
    client: KiwoomClient | None,
    dart_key: str,
    period: str,
    stop_pct: float,
    reward_risk: float,
    news_days: int,
    disc_days: int,
) -> AnalysisResult | None:
    name, code, ticker, market = resolve_stock_input(stock_input)
    if not ticker:
        return None

    df = yf.download(
        ticker,
        period=period,
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna(subset=["Open", "High", "Low", "Close"]).copy()
    df = enrich_indicators(df)
    last = df.iloc[-1]

    current_price, price_asof, price_note = get_current_price_kiwoom_or_yf(client, code, ticker, float(last["Close"]))

    calc_row = last.copy()
    calc_row["Close"] = current_price

    setup, setup_desc = decide_setup(calc_row)
    score, reasons, trend = calculate_score(calc_row, setup)
    grade = compute_grade(score)
    entry, stop, target = calculate_technical_prices(calc_row, setup, stop_pct=stop_pct, reward_risk=reward_risk)

    news_items = fetch_google_news(name, days=news_days, max_items=5)
    corp_code = find_dart_corp_code(dart_key, name, code)
    disclosure_items = fetch_dart_disclosures(dart_key, corp_code, days=disc_days, max_items=5)
    themes = detect_themes([x["title"] for x in news_items])

    explain = [setup_desc] + reasons
    explain.append("기술적 매수가는 현재가가 아니라 패턴/이평/고점구조 기준으로 계산")
    explain.append(f"현재가 반영 기준: {price_note}")
    if themes:
        explain.append("감지 테마: " + ", ".join(themes))
    if disclosure_items:
        explain.append(f"최근 {disc_days}일 공시 {len(disclosure_items)}건 확인")

    summary = (
        f"{name}은(는) 현재 **{setup}** 성격이 가장 강합니다. "
        f"점수는 **{score}점({grade})**, 추세 평가는 **{trend}** 입니다."
    )

    return AnalysisResult(
        name=name,
        code=code,
        ticker=ticker,
        market=market,
        current_price=safe_float(current_price, 2),
        price_note=price_note,
        price_asof=str(price_asof),
        score=score,
        grade=grade,
        setup=setup,
        trend=trend,
        entry_price=safe_float(entry, 2),
        stop_price=safe_float(stop, 2),
        target_price=safe_float(target, 2),
        summary=summary,
        reasons=explain,
        news_items=news_items,
        disclosure_items=disclosure_items,
        themes=themes,
        df=df,
    )


@st.cache_data(ttl=900, show_spinner=False)
def auto_recommend_top5(
    universe: tuple[str, ...],
    appkey: str,
    secretkey: str,
    use_mock: bool,
    dart_key: str,
    period: str,
    stop_pct: float,
    reward_risk: float,
    news_days: int,
    disc_days: int,
) -> list[AnalysisResult]:
    client = None
    if appkey and secretkey:
        try:
            client = KiwoomClient(KiwoomConfig(appkey=appkey, secretkey=secretkey, use_mock=use_mock))
        except Exception:
            client = None

    results = []
    for item in universe:
        try:
            result = analyze_one(
                item,
                client=client,
                dart_key=dart_key,
                period=period,
                stop_pct=stop_pct,
                reward_risk=reward_risk,
                news_days=news_days,
                disc_days=disc_days,
            )
            if result is None:
                continue
            if result.score < 48:
                continue
            if result.setup == "약세형":
                continue
            results.append(result)
        except Exception:
            continue
        time.sleep(0.02)

    results.sort(key=lambda x: x.score, reverse=True)
    return results[:5]


# --------------------------------------------------
# 화면
# --------------------------------------------------
st.title("📈 키움 모의실시간 자동추천 TOP5 + 종목 검색")
st.caption("키움 모의투자 실시간 현재가를 우선 사용하고, 추천주는 5개만 뽑아 보여주는 버전입니다.")

with st.expander("사용 전 꼭 읽어주세요", expanded=True):
    st.markdown(
        """
        - 키움 App Key / Secret Key를 넣으면 **키움 모의투자 시세**를 우선 사용합니다.
        - 추천주는 **TOP5만 표시**합니다.
        - 기술적 매수가는 현재가가 아니라 **차트 패턴/이평/고점 구조 기반**으로 계산합니다.
        - 공시까지 보려면 Open DART API Key가 필요합니다.
        """
    )

with st.sidebar:
    st.header("키움 설정")
    appkey = st.text_input("키움 App Key", value=os.getenv("KIWOOM_APPKEY", ""))
    secretkey = st.text_input("키움 Secret Key", value=os.getenv("KIWOOM_SECRETKEY", ""), type="password")
    use_mock = st.checkbox("키움 모의투자 사용", value=True)
    dart_key = st.text_input("Open DART API Key (공시용, 선택)", value=os.getenv("DART_API_KEY", ""))
    st.caption("모의투자 도메인은 KRX만 지원됩니다.")

tab_auto, tab_search = st.tabs(["자동 추천 TOP5", "종목 검색"])

with tab_auto:
    st.subheader("자동 추천 TOP5")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        period = st.selectbox("분석 기간", ["6mo", "1y", "2y"], index=1, key="auto_period")
    with c2:
        stop_label = st.selectbox("손절 비율", ["5%", "7%", "10%"], index=1, key="auto_stop")
    with c3:
        rr = st.selectbox("손익비", [1.5, 1.8, 2.0], index=1, key="auto_rr")
    with c4:
        news_days = st.selectbox("뉴스 기간", [7, 14, 30], index=1, key="auto_news_days")

    disc_days = st.selectbox("공시 기간(일)", [7, 14, 30, 60], index=2, key="auto_disc_days")
    run_auto = st.button("자동 추천 TOP5 실행", use_container_width=True)

    if run_auto:
        stop_pct = {"5%": 0.05, "7%": 0.07, "10%": 0.10}[stop_label]
        with st.spinner("자동 추천 TOP5 계산 중입니다..."):
            results = auto_recommend_top5(
                tuple(MARKET_UNIVERSE),
                appkey=appkey,
                secretkey=secretkey,
                use_mock=use_mock,
                dart_key=dart_key,
                period=period,
                stop_pct=stop_pct,
                reward_risk=float(rr),
                news_days=int(news_days),
                disc_days=int(disc_days),
            )

        if not results:
            st.warning("현재 조건에 맞는 추천 종목이 없습니다.")
        else:
            st.markdown("### 오늘 장전 자동 추천 TOP5")
            cols = st.columns(5)
            for idx, (col, r) in enumerate(zip(cols, results), start=1):
                with col:
                    st.markdown('<div class="card">', unsafe_allow_html=True)
                    st.markdown(f'<div class="rank-badge">TOP {idx}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="title-row">{r.name}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="subtle">{r.market} | 점수 {r.score} / 100 | 등급 {r.grade} | 패턴 {r.setup}</div>', unsafe_allow_html=True)
                    st.write(f"**현재가:** {format_price(r.current_price)}")
                    st.write(f"**기술적 매수가:** {format_price(r.entry_price)}")
                    st.write(f"**손절가:** {format_price(r.stop_price)}")
                    st.write(f"**목표가:** {format_price(r.target_price)}")
                    st.write("**추천 이유**")
                    for reason in r.reasons[:4]:
                        st.write(f"- {reason}")
                    if r.news_items:
                        st.write(f"**대표 뉴스:** {r.news_items[0]['title']}")
                    st.markdown('</div>', unsafe_allow_html=True)

            st.markdown("### 추천 순위표")
            rank_df = pd.DataFrame([
                {
                    "순위": i + 1,
                    "종목명": r.name,
                    "시장": r.market,
                    "종목코드": r.code,
                    "점수": r.score,
                    "등급": r.grade,
                    "패턴": r.setup,
                    "현재가": format_price(r.current_price),
                    "기술적 매수가": format_price(r.entry_price),
                    "손절가": format_price(r.stop_price),
                    "목표가": format_price(r.target_price),
                    "추세": r.trend,
                    "현재가 기준": r.price_note,
                }
                for i, r in enumerate(results)
            ])
            st.dataframe(rank_df, use_container_width=True, hide_index=True)

with tab_search:
    st.subheader("종목 검색")
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        stock_input = st.text_input("종목명 또는 코드", value="삼성전자")
    with s2:
        search_period = st.selectbox("분석 기간", ["6mo", "1y", "2y"], index=1, key="search_period")
    with s3:
        search_stop = st.selectbox("손절 비율", ["5%", "7%", "10%"], index=1, key="search_stop")
    with s4:
        search_rr = st.selectbox("손익비", [1.5, 1.8, 2.0], index=1, key="search_rr")

    s5, s6 = st.columns(2)
    with s5:
        search_news_days = st.selectbox("뉴스 기간", [7, 14, 30], index=1, key="search_news_days")
    with s6:
        search_disc_days = st.selectbox("공시 기간(일)", [7, 14, 30, 60], index=2, key="search_disc_days")

    run_search = st.button("종목 분석 실행", use_container_width=True)

    if run_search:
        search_stop_pct = {"5%": 0.05, "7%": 0.07, "10%": 0.10}[search_stop]
        client = None
        if appkey and secretkey:
            try:
                client = KiwoomClient(KiwoomConfig(appkey=appkey, secretkey=secretkey, use_mock=use_mock))
            except Exception:
                client = None

        with st.spinner("종목 분석 중입니다..."):
            result = analyze_one(
                stock_input,
                client=client,
                dart_key=dart_key,
                period=search_period,
                stop_pct=search_stop_pct,
                reward_risk=float(search_rr),
                news_days=int(search_news_days),
                disc_days=int(search_disc_days),
            )

        if result is None:
            st.error("종목 데이터를 불러오지 못했습니다.")
        else:
            top_a, top_b, top_c, top_d = st.columns(4)
            top_a.metric("종목명", result.name)
            top_b.metric("현재가", format_price(result.current_price))
            top_c.metric("점수", f"{result.score} / 100")
            top_d.metric("등급", result.grade)
            st.caption(f"현재가 반영 기준: {result.price_note} | 기준시각: {result.price_asof}")

            st.markdown("### 분석 요약")
            st.markdown(result.summary)

            l1, l2, l3, l4 = st.columns(4)
            l1.metric("기술적 매수가", format_price(result.entry_price))
            l2.metric("손절가", format_price(result.stop_price))
            l3.metric("목표가", format_price(result.target_price))
            l4.metric("패턴", result.setup)

            left, right = st.columns([1.1, 1.0])
            with left:
                st.plotly_chart(build_chart(result.df, result.name), use_container_width=True)
                st.markdown("### 추천 근거")
                for reason in result.reasons:
                    st.write(f"- {reason}")

            with right:
                st.markdown("### 추천 뉴스")
                if result.news_items:
                    for item in result.news_items:
                        if item["link"]:
                            st.markdown(f"- [{item['title']}]({item['link']})")
                        else:
                            st.write(f"- {item['title']}")
                        st.caption(f"{item['source']} | {item['published']}")
                else:
                    st.write("최근 추천 뉴스가 없습니다.")

                st.markdown("### 최근 공시")
                if result.disclosure_items:
                    for item in result.disclosure_items:
                        if item["link"]:
                            st.markdown(f"- [{item['title']}]({item['link']})")
                        else:
                            st.write(f"- {item['title']}")
                        st.caption(item["date"])
                else:
                    if dart_key:
                        st.write("최근 공시가 없거나 조회되지 않았습니다.")
                    else:
                        st.write("Open DART API Key를 입력하면 공시를 함께 볼 수 있습니다.")

st.divider()
st.markdown(
    """
    **실행 방법**
    1. `pip install streamlit yfinance pandas numpy plotly requests`
    2. `streamlit run kiwoom_mock_realtime_top5.py`
    3. 키움 App Key / Secret Key를 넣으면 키움 모의실시간 현재가를 우선 사용
    """
)
