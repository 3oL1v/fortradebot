# CryptoTerminal — заметки для Claude

Telegram Mini App: торговый аналитический терминал (мониторинг рынка, не торговый бот — ордера не выставляет, позиций/алертов нет).

## Стек и структура
- **Backend:** Python + FastAPI — `backend/main.py` (API + раздача фронта), `backend/bot.py` (Telegram-бот), `backend/config.py` (env).
- **Frontend:** один файл `frontend/index.html` (ванильный HTML/CSS/JS, без сборки). Графики — TradingView Lightweight Charts (CDN, **v5** → используется `addSeries(LightweightCharts.LineSeries/CandlestickSeries, ...)` с фолбэком на v4).
- **Деплой:** Railway/Nixpacks — `Procfile`, `nixpacks.toml`, `runtime.txt` (py 3.11). Запуск: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`.

## Запуск локально
- Из корня: `uvicorn backend.main:app` (или `start.sh`). Превью-сервер — через `.claude/launch.json` (имя `trading`, порт 8000).
- `config` импортируется устойчиво: `try: import config / except: from backend import config` (работает и из `backend/`, и как пакет из корня).

## Эндпоинты (`/api/...`)
`/health`; `ticker/{s}`, `orderbook/{s}`, `funding/{s}`, `klines/{s}?interval&limit`, `indicators/{s}?interval` — всё BingX USDT-M (публичные, ключ не нужен); `POST /analyze` — rule-based; `news/{s}` — RSS; `liquidations/{s}` — Binance WS-воркер.

## Источники данных и их статус
- ✅ **Реально/бесплатно (BingX):** цена, стакан (с тиковой точностью + спред), фандинг, свечи, индикаторы (RSI14, EMA20/50, Volume SMA20; считаются на бэке).
- ✅ **Анализ** (`/api/analyze`): **локальный rule-based** (`_build_analysis`), без LLM/ключей. Старые Anthropic-обёртки (`import anthropic`, `_get_anthropic`, `ANALYZE_MODEL`) остались, но **не используются**.
- ✅ **Новости** (`/api/news`): бесплатные **RSS** (Cointelegraph, Decrypt, CoinDesk) — общие по рынку, не по монете.
- ⚠️ **Ликвидации:** WS-воркер Binance `!forceOrder@arr` (lifespan-задача `_liquidation_worker`, копит в `_liq` по часам). **Binance не отдаёт данные из текущей сети (гео-блок: коннект есть, маркет-дата режется).** Bybit подписку принимает (`allLiquidation.{sym}`) — потенциальная замена. Пока **скрыто** флагом.

## Фронтенд: важное
- `const FEATURES = { ai, liquidations, news }` в начале `<script>` — включает/скрывает блоки и вкладки нижней навигации. Сейчас: `liquidations:false`.
- `loadSymbol`: ядро (тикер/стакан/фандинг/свечи/индикаторы) грузится через `Promise.all` и рендерится сразу; новости/ликвидации догружаются отдельно (`loadNews`/`loadLiquidations`, с защитой от смены монеты) — чтобы медленный RSS не тормозил цену/график.
- Точность цены: `priceDecimals` (~5 значащих цифр) для заголовка; стакан — точность из самих уровней (`countDecimals`). Не хардкодить «2 знака» (ломалось на XRP).
- BingX klines идут **по убыванию времени и в мс** → сортировать по возрастанию и делить time на 1000 для LWC.
- Авто-обновление: цена 10с, стакан 5с, индикаторы 60с, секундный тик (отсчёт фандинга + «обновлено N сек назад»). Все id — в `activeIntervals`, чистятся при смене монеты.
- Нижняя навигация: scroll-spy через IntersectionObserver + подстраховка на `scroll` (rAF) — выбор активной вкладки по позиции (надёжно для коротких блоков). `scrollIntoView({behavior:"smooth"})` в headless-превью флакает, в реальном браузере ок.

## Секреты и env (Railway → Variables)
- **`.env` — реальные секреты, в `.gitignore`, НИКОГДА не коммитить** (`git add .env` запрещён). В репо только `.env.example`.
- Нужны: `TELEGRAM_BOT_TOKEN`, `BINGX_API_KEY`, `BINGX_API_SECRET`, `WEBAPP_URL` (домен Railway после деплоя), `ENVIRONMENT=production`. `PORT` Railway задаёт сам. `ANTHROPIC_API_KEY`/`COINGLASS_API_KEY` сейчас не используются.
- Правило (память): если пользователь вписал секрет туда, где его видно (код/`.env.example`/чат) — перенести в `.env` и затереть оригинал.

## Репозиторий / деплой
- GitHub: `https://github.com/3oL1v/fortradebot.git`, ветка `main`. Воркфлоу трунковый: коммит в `main` → push → Railway пересобирает.
- `.git` создан под другой учёткой Windows → может потребоваться `git config --global --add safe.directory C:/Trade`.

## TODO / открытые вопросы
- Ликвидации: переключить воркер на Bybit `allLiquidation` и проверить в волатильность, либо платный Coinglass (REST, без гео), либо тест на Railway (не-US регион).
- Новости: при наличии бесплатного токена CryptoPanic — вернуть фильтр по монете + сентимент.
- Почистить мёртвый Anthropic-код, если Claude не возвращаем.
