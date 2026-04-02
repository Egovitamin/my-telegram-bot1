import os
import asyncio
import logging
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
import uvicorn

# --- Настройки и переменные окружения ---
# Включаем логирование, чтобы видеть сообщения об ошибках
logging.basicConfig(level=logging.INFO)
# Токен вашего бота, который вы получили от BotFather (хранится в секретах Render)
TOKEN = os.environ["BOT_TOKEN"]
# Render сам создаст эту переменную с адресом вашего сервиса
URL = os.environ["RENDER_EXTERNAL_URL"]
# Render ожидает, что приложение будет слушать порт, переданный в этой переменной
PORT = int(os.getenv("PORT", 8000))

# --- Обработчики команд бота ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение по команде /start"""
    await update.message.reply_text("Привет! Я бот и работаю на Render.com!")

# --- Основная функция ---
async def main():
    # Создаем приложение бота
    application = Application.builder().token(TOKEN).updater(None).build()
    # Регистрируем обработчик команды /start
    application.add_handler(CommandHandler("start", start))

    # Настраиваем вебхук: Telegram будет отправлять обновления по этому адресу
    await application.bot.set_webhook(url=f"{URL}/telegram", allowed_updates=Update.ALL_TYPES)

    # --- Создаем веб-сервер для приема вебхуков ---
    # Асинхронная функция для обработки POST-запросов от Telegram
    async def telegram_webhook(request: Request) -> Response:
        # Получаем данные из запроса и передаем их приложению бота
        await application.update_queue.put(Update.de_json(await request.json(), application.bot))
        return Response()

    # Асинхронная функция для проверки работоспособности бота (healthcheck)
    async def health_check(_: Request) -> PlainTextResponse:
        return PlainTextResponse("OK")

    # Создаем само веб-приложение на Starlette
    starlette_app = Starlette(routes=[
        Route("/telegram", telegram_webhook, methods=["POST"]),
        Route("/healthcheck", health_check, methods=["GET"]),
    ])

    # Настраиваем сервер uvicorn для запуска веб-приложения
    web_server = uvicorn.Server(uvicorn.Config(starlette_app, host="0.0.0.0", port=PORT, log_level="info"))

    # Запускаем приложение бота и веб-сервер параллельно
    async with application:
        await application.start()
        await web_server.serve()
        await application.stop()

# Точка входа в программу
if __name__ == "__main__":
    asyncio.run(main())