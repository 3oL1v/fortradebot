"""Конфигурация приложения: загрузка настроек из переменных окружения."""

import os

from dotenv import load_dotenv

# Загружаем .env из корня проекта (на уровень выше папки backend),
# а также из текущей директории — на случай запуска из разных мест.
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# --- Секреты и внешние сервисы -------------------------------------------------

TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
BINGX_API_KEY: str = os.getenv("BINGX_API_KEY", "")
BINGX_API_SECRET: str = os.getenv("BINGX_API_SECRET", "")
COINGLASS_API_KEY: str = os.getenv("COINGLASS_API_KEY", "")

# Базовый URL публичного API BingX
BINGX_BASE_URL: str = os.getenv("BINGX_BASE_URL", "https://open-api.bingx.com")

# URL фронтенда (Mini App). Telegram требует HTTPS для WebApp-кнопки.
WEBAPP_URL: str = os.getenv("WEBAPP_URL", "http://localhost:8000")


# --- Параметры сервера ---------------------------------------------------------

HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.environ.get("PORT", 8000))

# Окружение деплоя (на Railway задайте ENVIRONMENT=production).
ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "development")
IS_PRODUCTION: bool = ENVIRONMENT == "production"


def validate() -> list[str]:
    """Возвращает список незаполненных обязательных переменных (для диагностики)."""
    missing = []
    for name in ("TELEGRAM_BOT_TOKEN", "WEBAPP_URL"):
        if not globals().get(name):
            missing.append(name)
    return missing
