"""FastAPI сервер — точка входа бэкенда Trading Mini App.

Публичные эндпоинты проксируют рыночные данные BingX (USDT-M Perpetual).
API-ключ для них не нужен — это публичные данные биржи.

Запуск (из папки backend):
    uvicorn main:app --reload
или напрямую:
    python main.py
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import anthropic
import httpx
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Импорт config работает и из папки backend (локально: `uvicorn main:app`),
# и как пакет из корня проекта (Railway: `uvicorn backend.main:app`).
try:
    import config
except ModuleNotFoundError:
    from backend import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("trading.bingx")

# Путь к фронтенду: <корень проекта>/frontend/index.html
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
INDEX_FILE = FRONTEND_DIR / "index.html"

# Порт из окружения (Railway задаёт $PORT, локально — 8000).
port = int(os.environ.get("PORT", 8000))

# Общий async HTTP-клиент к BingX (создаётся в lifespan, переиспользуется).
_client: httpx.AsyncClient | None = None

# Клиент для внешних API (CryptoPanic / CryptoCompare / Coinglass) — без base_url.
_ext_client: httpx.AsyncClient | None = None

# Модель Claude для AI-анализа: Haiku 4.5 — быстрая и дешёвая.
ANALYZE_MODEL = "claude-haiku-4-5"

# Async-клиент Anthropic (создаётся лениво при первом запросе анализа).
_anthropic: anthropic.AsyncAnthropic | None = None


# --- Ошибки / lifecycle --------------------------------------------------------

class BingXError(Exception):
    """Ошибка обращения к BingX: монета не найдена / API-ошибка / сеть."""

    def __init__(self, message: str, status_code: int = 404) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Поднимаем и закрываем общий HTTP-клиент вместе с приложением."""
    global _client, _ext_client
    _client = httpx.AsyncClient(
        base_url=config.BINGX_BASE_URL,
        timeout=httpx.Timeout(10.0),
    )
    _ext_client = httpx.AsyncClient(
        timeout=httpx.Timeout(12.0),
        headers={"User-Agent": "TradingMiniApp/0.1"},
        follow_redirects=True,
    )
    logger.info("HTTP-клиент готов. BingX base URL: %s", config.BINGX_BASE_URL)
    try:
        yield
    finally:
        await _client.aclose()
        await _ext_client.aclose()
        _client = None
        _ext_client = None


app = FastAPI(title="Trading Mini App", version="0.1.0", lifespan=lifespan)

# CORS для всех origins.
# allow_credentials=False — обязательное условие при wildcard "*"
# (браузеры запрещают cookies/credentials вместе с allow_origins=["*"]).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BingXError)
async def _bingx_error_handler(request, exc: BingXError) -> JSONResponse:
    """Любую BingXError превращаем в чистый JSON {"error": ...} с нужным статусом."""
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message})


# --- Вспомогательные функции ---------------------------------------------------

def _to_float(value) -> float | None:
    """Безопасно конвертирует строковое значение BingX в float (или None)."""
    if isinstance(value, str):
        value = value.strip().rstrip("%")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(data: dict, *names: str) -> float | None:
    """Return the first numeric value found in a dict for a list of possible API fields."""
    for name in names:
        value = _to_float(data.get(name))
        if value is not None:
            return value
    return None


def _parse_candle(item) -> dict | None:
    """Normalize a BingX kline item from either object or array format."""
    if isinstance(item, dict):
        time_value = item.get("time") or item.get("openTime") or item.get("t")
        return {
            "time": time_value,
            "open": _first_float(item, "open", "o"),
            "high": _first_float(item, "high", "h"),
            "low": _first_float(item, "low", "l"),
            "close": _first_float(item, "close", "c"),
            "volume": _first_float(item, "volume", "vol", "baseVolume", "quoteVolume"),
        }
    if isinstance(item, (list, tuple)) and len(item) >= 6:
        return {
            "time": item[0],
            "open": _to_float(item[1]),
            "high": _to_float(item[2]),
            "low": _to_float(item[3]),
            "close": _to_float(item[4]),
            "volume": _to_float(item[5]),
        }
    return None


def _parse_levels(levels) -> list:
    """Уровни стакана BingX → [[цена, объём], ...] (до 20 шт.)."""
    result = []
    for level in (levels or [])[:20]:
        if len(level) >= 2:
            result.append([_to_float(level[0]), _to_float(level[1])])
    return result


def _get_anthropic() -> anthropic.AsyncAnthropic:
    """Ленивая инициализация async-клиента Anthropic (singleton)."""
    global _anthropic
    if _anthropic is None:
        _anthropic = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _anthropic


async def bingx_get(path: str, params: dict) -> dict | list:
    """GET к публичному API BingX. Возвращает поле data или бросает BingXError.

    - сеть/таймаут/невалидный JSON → 502 Upstream error
    - code != 0 или пустой data (монета не найдена) → 404 Symbol not found
    """
    if _client is None:  # запрос вне жизненного цикла приложения
        raise BingXError("Service not ready", status_code=503)

    try:
        resp = await _client.get(path, params=params)
        resp.raise_for_status()
        payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.error("BingX request failed: GET %s %s — %s", path, params, exc)
        raise BingXError("Upstream error", status_code=502)

    if payload.get("code") not in (0, "0"):
        logger.error(
            "BingX error: GET %s %s — code=%s msg=%s",
            path, params, payload.get("code"), payload.get("msg"),
        )
        raise BingXError("Symbol not found", status_code=404)

    data = payload.get("data")
    if not data:
        logger.error("BingX empty data: GET %s %s — %s", path, params, payload)
        raise BingXError("Symbol not found", status_code=404)

    return data


# --- Индикаторы и заглушки -----------------------------------------------------

def _ema(values: list, period: int) -> list:
    """EMA; None пока не накоплен период. Сид — SMA первых `period` значений."""
    out: list = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def _sma(values: list, period: int) -> list:
    """Простое скользящее среднее; None до накопления периода."""
    out: list = [None] * len(values)
    if len(values) < period:
        return out
    running = sum(values[:period])
    out[period - 1] = running / period
    for i in range(period, len(values)):
        running += values[i] - values[i - period]
        out[i] = running / period
    return out


def _rsi(closes: list, period: int = 14) -> list:
    """RSI по Уайлдеру. None до первого рассчитанного значения."""
    out: list = [None] * len(closes)
    if len(closes) <= period:
        return out

    gains = losses = 0.0
    for i in range(1, period + 1):
        ch = closes[i] - closes[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period

    def _val(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    out[period] = _val(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        ch = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(ch, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-ch, 0.0)) / period
        out[i] = _val(avg_gain, avg_loss)
    return out


def _series(times: list, arr: list, decimals: int = 4, last: int = 100) -> list:
    """[{time, value}] только для непустых значений, последние `last` штук."""
    pts = [
        {"time": times[i], "value": round(arr[i], decimals)}
        for i in range(len(arr))
        if arr[i] is not None
    ]
    return pts[-last:]


def _mock_liquidations() -> dict:
    """Заглушка ликвидаций: 24 почасовых метки за сутки, нулевые суммы."""
    hour = int(time.time()) // 3600 * 3600
    longs = [[(hour - i * 3600) * 1000, 0] for i in range(23, -1, -1)]
    shorts = [[(hour - i * 3600) * 1000, 0] for i in range(23, -1, -1)]
    return {"longs": longs, "shorts": shorts, "total24h": 0, "longsDominance": 50}


# --- Системные эндпоинты -------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    """Проверка живости сервиса."""
    return {"status": "ok"}


# --- Рыночные данные BingX -----------------------------------------------------

@app.get("/api/ticker/{symbol}")
async def ticker(symbol: str) -> dict:
    """Тикер за 24ч: цена, изменение %, максимум, минимум, объём."""
    pair = f"{symbol.upper()}-USDT"
    data = await bingx_get("/openApi/swap/v2/quote/ticker", {"symbol": pair})
    return {
        "symbol": symbol.upper(),
        "price": _first_float(data, "lastPrice", "last", "close"),
        "priceChangePercent": _first_float(data, "priceChangePercent", "priceChangeRate"),
        "high": _first_float(data, "highPrice", "high"),
        "low": _first_float(data, "lowPrice", "low"),
        "volume": _first_float(data, "quoteVolume", "volume", "baseVolume"),
    }


@app.get("/api/orderbook/{symbol}")
async def orderbook(symbol: str) -> dict:
    """Стакан: топ-20 заявок на покупку (bids) и продажу (asks). Каждая — [цена, объём]."""
    pair = f"{symbol.upper()}-USDT"
    data = await bingx_get(
        "/openApi/swap/v2/quote/depth", {"symbol": pair, "limit": 20}
    )
    return {
        "symbol": symbol.upper(),
        "bids": _parse_levels(data.get("bids")),
        "asks": _parse_levels(data.get("asks")),
    }


@app.get("/api/funding/{symbol}")
async def funding(symbol: str) -> dict:
    """Фандинг: текущая ставка (в %) и время следующего расчёта."""
    pair = f"{symbol.upper()}-USDT"
    data = await bingx_get("/openApi/swap/v2/quote/premiumIndex", {"symbol": pair})
    # BingX отдаёт долю (напр. 0.000076); переводим в проценты.
    rate = _to_float(data.get("lastFundingRate"))
    return {
        "symbol": symbol.upper(),
        "fundingRate": round(rate * 100, 6) if rate is not None else None,
        "nextFundingTime": data.get("nextFundingTime"),
    }


@app.get("/api/klines/{symbol}")
async def klines(
    symbol: str,
    interval: str = "1h",
    limit: int = Query(100, ge=1, le=1440),
) -> list:
    """Свечи: массив [{time, open, high, low, close, volume}]."""
    pair = f"{symbol.upper()}-USDT"
    data = await bingx_get(
        "/openApi/swap/v3/quote/klines",
        {"symbol": pair, "interval": interval, "limit": limit},
    )

    candles = []
    for item in data:
        candle = _parse_candle(item)
        if candle is not None:
            candles.append(candle)
            # запасной вариант на случай массивного формата: [time, o, h, l, c, v]
    return candles


# --- AI-анализ (Anthropic Claude) ----------------------------------------------

class AnalyzeRequest(BaseModel):
    symbol: str
    price: float | None = None
    priceChange: float | None = None
    fundingRate: float | None = None
    high24h: float | None = None
    low24h: float | None = None
    volume24h: float | None = None


@app.post("/api/analyze")
async def analyze(body: AnalyzeRequest):
    """AI-анализ монеты по присланным метрикам (Claude Haiku 4.5)."""
    if not config.ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY не задан — AI-анализ недоступен")
        return JSONResponse(status_code=503, content={"error": "AI недоступен"})

    def fmt(v):
        return "n/a" if v is None else v

    prompt = (
        f"Дай краткий анализ монеты {body.symbol} на основе данных:\n\n"
        f"- Текущая цена: {fmt(body.price)} USDT\n"
        f"- Изменение за 24ч: {fmt(body.priceChange)}%\n"
        f"- Максимум 24ч: {fmt(body.high24h)}\n"
        f"- Минимум 24ч: {fmt(body.low24h)}\n"
        f"- Объём 24ч: {fmt(body.volume24h)} USDT\n"
        f"- Funding Rate: {fmt(body.fundingRate)}%\n\n"
        "Дай анализ в формате:\n"
        "**Тренд:** (бычий/медвежий/боковик) — одно предложение почему\n"
        "**Funding:** (что означает текущий фандинг для позиций)\n"
        "**Ключевые уровни:** поддержка и сопротивление на основе high/low\n"
        "**Вывод:** 2-3 предложения — на что обратить внимание прямо сейчас"
    )

    try:
        client = _get_anthropic()
        message = await client.messages.create(
            model=ANALYZE_MODEL,
            max_tokens=1024,
            system=(
                "Ты опытный крипто-трейдер. Отвечай только на русском. "
                "Будь конкретным и кратким."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in message.content if b.type == "text")
        return {"analysis": text}
    except Exception as exc:  # сеть / авторизация / лимиты → AI недоступен
        logger.error("Anthropic API error: %s", exc)
        return JSONResponse(status_code=503, content={"error": "AI недоступен"})


# --- Новости / Ликвидации / Индикаторы -----------------------------------------

@app.get("/api/news/{symbol}")
async def news(symbol: str) -> list:
    """Новости по монете: CryptoPanic → CryptoCompare → [] (оба недоступны)."""
    if _ext_client is None:
        return []

    sym = symbol.upper()

    # 1) CryptoPanic (бесплатный публичный токен)
    try:
        resp = await _ext_client.get(
            "https://cryptopanic.com/api/v1/posts/",
            params={"auth_token": "public", "currencies": sym,
                    "kind": "news", "limit": 10},
        )
        ctype = resp.headers.get("content-type", "")
        if resp.status_code == 200 and "application/json" in ctype:
            results = resp.json().get("results") or []
            items = []
            for it in results[:10]:
                votes = it.get("votes") or {}
                items.append({
                    "title": it.get("title"),
                    "url": it.get("url"),
                    "source": (it.get("source") or {}).get("title"),
                    "published_at": it.get("published_at"),
                    "votes": {
                        "positive": votes.get("positive", 0) or 0,
                        "negative": votes.get("negative", 0) or 0,
                    },
                })
            if items:
                return items
    except Exception as exc:
        logger.error("CryptoPanic недоступен: %s", exc)

    # 2) Резерв — CryptoCompare (published_on → published_at, ISO)
    try:
        resp = await _ext_client.get(
            "https://min-api.cryptocompare.com/data/v2/news/",
            params={"categories": sym, "limit": 10},
        )
        if resp.status_code == 200:
            data = resp.json().get("Data")
            if isinstance(data, list) and data:
                items = []
                for it in data[:10]:
                    ts = it.get("published_on")
                    items.append({
                        "title": it.get("title"),
                        "url": it.get("url"),
                        "source": (it.get("source_info") or {}).get("name")
                                  or it.get("source"),
                        "published_at": (
                            datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                            if isinstance(ts, (int, float)) else None
                        ),
                        "votes": {"positive": 0, "negative": 0},
                    })
                return items
    except Exception as exc:
        logger.error("CryptoCompare недоступен: %s", exc)

    return []


@app.get("/api/liquidations/{symbol}")
async def liquidations(symbol: str) -> dict:
    """Ликвидации (Coinglass). При недоступности — мок нужной структуры."""
    if _ext_client is None or not config.COINGLASS_API_KEY:
        return _mock_liquidations()

    sym = symbol.upper()
    try:
        resp = await _ext_client.get(
            "https://open-api.coinglass.com/public/v2/liquidation_chart",
            params={"symbol": sym, "timeType": 1},
            headers={"coinglassSecret": config.COINGLASS_API_KEY},
        )
        if resp.status_code == 200:
            payload = resp.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                dates = data.get("dateList") or data.get("dates") or []
                long_vals = (data.get("longLiquidationList")
                             or data.get("longLiquidation")
                             or data.get("buyVolList") or [])
                short_vals = (data.get("shortLiquidationList")
                              or data.get("shortLiquidation")
                              or data.get("sellVolList") or [])
                longs = [[dates[i], _to_float(long_vals[i]) or 0]
                         for i in range(min(len(dates), len(long_vals)))]
                shorts = [[dates[i], _to_float(short_vals[i]) or 0]
                          for i in range(min(len(dates), len(short_vals)))]
                if longs or shorts:
                    long_sum = sum(v for _, v in longs)
                    short_sum = sum(v for _, v in shorts)
                    total = long_sum + short_sum
                    dom = round(long_sum / total * 100, 1) if total > 0 else 50
                    return {
                        "longs": longs,
                        "shorts": shorts,
                        "total24h": round(total, 2),
                        "longsDominance": dom,
                    }
    except Exception as exc:
        logger.error("Coinglass недоступен: %s", exc)

    return _mock_liquidations()


@app.get("/api/indicators/{symbol}")
async def indicators(symbol: str, interval: str = "1h") -> dict:
    """RSI(14), EMA20, EMA50, Volume SMA20 по 200 свечам BingX (последние 100)."""
    pair = f"{symbol.upper()}-USDT"
    data = await bingx_get(
        "/openApi/swap/v3/quote/klines",
        {"symbol": pair, "interval": interval, "limit": 200},
    )

    # Свечи BingX приходят по убыванию времени — сортируем по возрастанию.
    rows = []
    for it in data:
        candle = _parse_candle(it)
        if candle is not None:
            rows.append((candle.get("time"),
                         candle.get("close"),
                         candle.get("volume")))
    rows = [r for r in rows if r[0] is not None and r[1] is not None]
    rows.sort(key=lambda r: r[0])

    times = [r[0] for r in rows]
    closes = [r[1] for r in rows]
    volumes = [r[2] if r[2] is not None else 0.0 for r in rows]

    rsi = _rsi(closes, 14)
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    vol_sma = _sma(volumes, 20)

    def _last(arr):
        for v in reversed(arr):
            if v is not None:
                return v
        return None

    last_ema20, last_ema50 = _last(ema20), _last(ema50)
    last_rsi, last_vol_sma = _last(rsi), _last(vol_sma)
    # Последняя свеча ещё формируется → для объёма берём последнюю ЗАКРЫТУЮ,
    # иначе в начале периода ratio проседает почти до нуля.
    last_vol = volumes[-2] if len(volumes) >= 2 else (volumes[-1] if volumes else None)
    vol_ratio = (round(last_vol / last_vol_sma, 2)
                 if last_vol is not None and last_vol_sma else None)

    return {
        "rsi": _series(times, rsi, decimals=2),
        "ema20": _series(times, ema20, decimals=6),
        "ema50": _series(times, ema50, decimals=6),
        "volumeSma20": _series(times, vol_sma, decimals=2),
        "current": {
            "rsi": round(last_rsi, 2) if last_rsi is not None else None,
            "ema20": round(last_ema20, 6) if last_ema20 is not None else None,
            "ema50": round(last_ema50, 6) if last_ema50 is not None else None,
            "trend": ("bullish" if (last_ema20 is not None
                                    and last_ema50 is not None
                                    and last_ema20 > last_ema50) else "bearish"),
            "volume": round(last_vol, 2) if last_vol is not None else None,
            "volumeRatio": vol_ratio,
        },
    }


# --- Фронтенд ------------------------------------------------------------------

# Статика фронтенда на /static (CSS/JS/изображения из папки frontend/, на будущее).
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def index() -> FileResponse:
    """Раздаём фронтенд (Mini App) на корневом маршруте."""
    if not INDEX_FILE.exists():
        return JSONResponse(
            status_code=500,
            content={"error": f"index.html не найден по пути {INDEX_FILE}"},
        )
    return FileResponse(INDEX_FILE)


if __name__ == "__main__":
    import uvicorn

    # Локальный запуск из папки backend: python main.py
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
