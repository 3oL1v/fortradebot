# Trading Mini App

Telegram Mini App для крипто-трейдинга: поиск монеты, цена, график, стакан, funding, индикаторы, новости, ликвидации и AI-анализ.

## Стек

- Backend: Python, FastAPI, httpx
- Frontend: один статический `HTML/CSS/JS` файл
- Telegram bot: `python-telegram-bot`
- Рыночные данные: публичные endpoints BingX USDT-M Perpetual
- AI-анализ: Anthropic Claude

## Структура

```text
.
├── backend/
│   ├── main.py            # FastAPI API + раздача frontend
│   ├── bot.py             # Telegram bot (/start, /help)
│   ├── config.py          # Настройки из переменных окружения
│   └── requirements.txt   # Python зависимости
├── frontend/
│   └── index.html         # Mini App
├── tests/
│   └── test_market_helpers.py
├── .env.example
├── Procfile
├── nixpacks.toml
├── runtime.txt
└── start.sh
```

## Установка

```bash
python -m venv venv

# Windows PowerShell
venv\Scripts\Activate.ps1

# Linux/macOS
# source venv/bin/activate

pip install -r backend/requirements.txt
copy .env.example .env
```

Заполните `.env` перед запуском бота и AI-функций.

## Переменные окружения

| Переменная | Описание |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram bot от `@BotFather`. |
| `WEBAPP_URL` | HTTPS URL Mini App для Telegram WebApp-кнопки. |
| `ANTHROPIC_API_KEY` | Опционально. Нужен для `/api/analyze`. |
| `BINGX_API_KEY` / `BINGX_API_SECRET` | Зарезервированы под будущие приватные методы. Публичным market endpoints сейчас не нужны. |
| `BINGX_BASE_URL` | Опционально. По умолчанию `https://open-api.bingx.com`. |
| `COINGLASS_API_KEY` | Опционально. Без ключа `/api/liquidations/{symbol}` возвращает mock-структуру с нулями. |
| `HOST` / `PORT` | Настройки запуска сервера. |

## Запуск backend

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Локальные URL:

- Mini App: `http://localhost:8000/`
- Health check: `http://localhost:8000/health`

## Запуск Telegram bot

```bash
cd backend
python bot.py
```

Команды:

- `/start` - приветствие и кнопка открытия Mini App через `WEBAPP_URL`
- `/help` - краткая справка

Telegram WebApp-кнопка требует HTTPS. Для локальной разработки поднимите туннель к `localhost:8000`, например через `ngrok` или `cloudflared`, и укажите полученный URL в `WEBAPP_URL`.

## API

- `GET /health`
- `GET /api/ticker/{symbol}`
- `GET /api/orderbook/{symbol}`
- `GET /api/funding/{symbol}`
- `GET /api/klines/{symbol}?interval=1h&limit=100`
- `GET /api/indicators/{symbol}?interval=1h`
- `GET /api/news/{symbol}`
- `GET /api/liquidations/{symbol}`
- `POST /api/analyze`

`symbol` передается без `USDT`, например `BTC`, `ETH`, `SOL`.

## Проверки

```bash
python -m py_compile backend/main.py backend/bot.py backend/config.py
python -m unittest discover -s tests
```

## Статус

Это рабочий каркас Mini App с реальными публичными market endpoints BingX. AI-анализ требует `ANTHROPIC_API_KEY`. Реальные ликвидации требуют `COINGLASS_API_KEY`; без него возвращается стабильная mock-структура, чтобы frontend не ломался.
