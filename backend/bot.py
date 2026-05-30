"""Telegram-бот для Trading Mini App (python-telegram-bot v21+, async).

Запуск (из папки backend):
    python bot.py
"""

import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.ext import Application, CommandHandler, ContextTypes

import config

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /start — приветствие и кнопка открытия терминала."""
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📈 Открыть терминал",
                    web_app=WebAppInfo(url=config.WEBAPP_URL),
                )
            ]
        ]
    )
    await update.message.reply_text(
        "👋 Привет! Это торговый терминал в Telegram.\n\n"
        "Анализируй монеты, смотри график, стакан и AI-аналитику —\n"
        "всё прямо здесь. Нажми кнопку ниже, чтобы открыть.",
        reply_markup=keyboard,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда /help — краткая справка."""
    await update.message.reply_text(
        "ℹ️ Справка\n\n"
        "/start — открыть торговый терминал\n"
        "/help — показать эту справку\n\n"
        "Внутри терминала: введи тикер (BTC, ETH, SOL…) и нажми «Анализировать».",
    )


def main() -> None:
    """Точка входа бота: long polling."""
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN не задан. Заполни .env (см. .env.example)."
        )

    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    logger.info("Бот запущен. Ожидание сообщений...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
