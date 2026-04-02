import os
import asyncio
import logging
import tempfile
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from telegram import Update
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters, ContextTypes
from docx import Document
import uvicorn

# ---------- Настройки ----------
logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]
URL = os.environ["RENDER_EXTERNAL_URL"]
PORT = int(os.getenv("PORT", 8000))

# ---------- Список полей (вопросов) ----------
FIELDS = [
    ("date", "📅 Дата (например, 12.04.2026)"),
    ("time", "⏰ Время (например, 10:30)"),
    ("fio", "👤 ФИО пациента"),
    ("age", "📆 Возраст (полных лет)"),
    ("h", "📏 Рост (см)"),
    ("w", "⚖️ Вес (кг)"),
    ("diagnosis", "🏥 Порядок поступления и диагноз (Плановый/Неотложный/Экстренный, повод)"),
    ("complaints", "💬 Жалобы"),
    ("history", "📋 Анамнез заболевания"),
    ("concomitant", "🩺 Сопутствующие заболевания"),
    ("meds", "💊 Постоянный приём лекарств"),
    ("allergy", "🌿 Аллергологический анамнез"),
    ("blood", "🩸 Переливания крови (да/нет, осложнения)"),
    ("neuro", "🧠 Нейроинфекции, ЧМТ"),
    ("inf", "🦠 Инфекционные заболевания"),
    ("ops", "🔪 Оперативные вмешательства"),
    ("narc_tol", "💉 Переносимость наркозов"),
    ("specs", "📌 Особенности (любые)"),
    ("st_gen", "😐 Общее состояние"),
    ("psycho", "🧠 Сознание"),
    ("body_type", "🏋️ Телосложение (астеник/нормостеник/гиперстеник)"),
    ("bmi", "📊 Индекс массы тела (число)"),
    ("obesity", "🍔 Ожирение (если есть – степень)"),
    ("skin", "🩻 Кожные покровы и слизистые"),
    ("moist", "💧 Влажность кожи (нормальная/снижена/потливость)"),
    ("thyroid", "🦋 Щитовидная железа (норма/увеличена)"),
    ("turgor", "🤚 Тургор кожи (нормальный/снижен)"),
    ("temp", "🌡️ Температура тела"),
    ("nodes", "🪢 Периферические лимфоузлы (не увеличены/увеличены)"),
    ("throat", "👄 Зев (не гиперемирован/гиперемирован)"),
    ("mallampaty", "😮 Mallampaty (1,2,3,4)"),
    ("teeth", "🦷 Зубы (санированы/нет, съёмные протезы – есть/нет)"),
    ("edema", "💦 Периферические отёки, пастозность (есть/нет, где)"),
    ("breath", "🌬️ Дыхание (везикулярное/бронхиальное)"),
    ("rr", "📈 ЧДД (в мин)"),
    ("wheeze", "🎵 Хрипы (нет/сухие/влажные, локализация)"),
    ("h_sounds", "❤️ Сердечные тоны (ясные/приглушены/глухие, ритмичные/аритмичные)"),
    ("ps", "💓 Пульс (Ps, уд/мин)"),
    ("p_def", "📉 Дефицит пульса (если есть)"),
    ("ad_s", "🩸 АД систолическое"),
    ("ad_d", "🩸 АД диастолическое"),
    ("spo2", "🫁 SpO2 (%)"),
    ("tongue", "👅 Язык (влажный/сухой, обложен/не обложен)"),
    ("abd", "🤰 Живот (мягкий/напряжённый, безболезненный/болезненный)"),
    ("perist", "🔊 Перистальтика (выслушивается/нет, нормальная/усилена/ослаблена)"),
    ("liver", "🧬 Печень (не увеличена/увеличена, край)"),
    ("ur", "🚽 Мочеиспускание (свободное/затруднённое, без особенностей)"),
    ("stool", "💩 Стул (норма/жидкий/задержка, дней)"),
    ("hvn", "🦵 ХВН сосудов ног (нет/есть, степень)"),
    ("lab", "🧪 Критические данные лабораторного обследования"),
    ("ecg", "📈 ЭКГ (описание)"),
    ("asa", "📊 ASA (I, II, III, IV, V, E)"),
    ("mnoar", "📋 МНОАР (баллы)"),
    ("op_vol", "📐 Объём операции (ожидаемый)"),
    ("anes_type", "💉 Тип обезболивания (тотальная/сочетанная/комбинированная/в/венная/ингаляционная/эпидуральная/субарахноидальная/проводниковая)"),
    ("add_test", "🔬 Дообследование (что назначено)"),
    ("prep", "🛁 Предоперационная подготовка (кроме клизмы)"),
    ("p_date", "📅 Дата премедикации (например, 12.04.2026)"),
    ("sib_dose", "💊 Сибазон (доза в мл, 0,5% раствор)"),
    ("time_before_op", "⏱️ За сколько минут до операции премедикация в/в или в/м"),
    ("prom_dose", "💉 Промедол 2% (доза в мл)"),
    ("doc_name", "✍️ Фамилия врача анестезиолога")
]

STATE_LIST = list(range(len(FIELDS)))

# ---------- Обработчики бота ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинаем опрос с первого вопроса"""
    context.user_data.clear()
    context.user_data["step"] = 0
    await update.message.reply_text(
        "👨‍⚕️ **Заполнение осмотра анестезиолога**\n"
        "Я задам несколько вопросов. Отвечайте текстом.\n"
        "Для отмены введите /cancel\n\n"
        f"{FIELDS[0][1]}:",
        parse_mode="Markdown"
    )
    return STATE_LIST[0]

async def handle_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответ на текущий вопрос и переходит к следующему"""
    step = context.user_data.get("step", 0)
    if step >= len(FIELDS):
        return await generate_document(update, context)

    field_name, question = FIELDS[step]
    answer = update.message.text.strip()
    if not answer:
        await update.message.reply_text("❌ Поле не может быть пустым. Пожалуйста, введите значение:")
        return STATE_LIST[step]

    context.user_data[field_name] = answer
    step += 1
    context.user_data["step"] = step

    if step >= len(FIELDS):
        await update.message.reply_text("✅ Все данные собраны. Формирую документ...")
        return await generate_document(update, context)
    else:
        await update.message.reply_text(FIELDS[step][1])
        return STATE_LIST[step]

async def generate_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Заменяет метки в template.docx и отправляет файл"""
    data = context.user_data
    template_path = "template.docx"  # файл должен лежать в корне репозитория

    if not os.path.exists(template_path):
        await update.message.reply_text("❌ Ошибка: файл шаблона template.docx не найден на сервере.")
        return ConversationHandler.END

    doc = Document(template_path)

    # Замена в параграфах
    for paragraph in doc.paragraphs:
        for key, value in data.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in paragraph.text:
                paragraph.text = paragraph.text.replace(placeholder, str(value))

    # Замена в таблицах
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for key, value in data.items():
                    placeholder = f"{{{{{key}}}}}"
                    if placeholder in cell.text:
                        cell.text = cell.text.replace(placeholder, str(value))

    # Сохраняем во временный файл
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        doc.save(tmp.name)
        tmp_path = tmp.name

    # Отправляем файл
    with open(tmp_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=f"осмотр_{data.get('fio', 'patient')}.docx",
            caption="📄 Осмотр анестезиолога готов."
        )

    os.unlink(tmp_path)  # удаляем временный файл
    await update.message.reply_text("Для нового осмотра нажмите /start")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Заполнение отменено. Чтобы начать заново, введите /start")
    return ConversationHandler.END

# ---------- Настройка вебхуков и веб-сервера ----------
async def setup_webhook(application):
    """Устанавливает вебхук при старте"""
    webhook_url = f"{URL}/telegram"
    await application.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)
    logging.info(f"Webhook set to {webhook_url}")

async def main():
    # Создаём приложение бота
    application = Application.builder().token(TOKEN).updater(None).build()

    # Регистрируем обработчики
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={state: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_field)] for state in STATE_LIST},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))

    # Устанавливаем вебхук
    await setup_webhook(application)

    # Создаём Starlette приложение для приёма вебхуков
    async def telegram_webhook(request: Request) -> Response:
        """Принимает POST-запросы от Telegram"""
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return Response()

    async def health_check(request: Request) -> PlainTextResponse:
        return PlainTextResponse("OK")

    starlette_app = Starlette(routes=[
        Route("/telegram", telegram_webhook, methods=["POST"]),
        Route("/healthcheck", health_check, methods=["GET"]),
    ])

    # Запускаем веб-сервер
    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
