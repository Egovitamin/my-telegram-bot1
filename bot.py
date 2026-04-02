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

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]
URL = os.environ["RENDER_EXTERNAL_URL"]
PORT = int(os.getenv("PORT", 8000))

# ---------- СПИСОК ПОЛЕЙ (ПО ВАШЕМУ ШАБЛОНУ) ----------
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
    ("t1", "Телосложение: астеник (да/нет) — если да, напишите 'да'"),
    ("t2", "Телосложение: нормостеник (да/нет)"),
    ("t3", "Телосложение: гиперстеник (да/нет)"),
    ("bmi", "📊 Индекс массы тела (число)"),
    ("obesity", "🍔 Ожирение (если есть – степень)"),
    ("skin", "🩻 Кожные покровы и слизистые (обычные/бледные/гиперемированы)"),
    ("moist", "💧 Влажность кожи (нормальная/снижена/потливость)"),
    ("thyroid", "🦋 Щитовидная железа (норма/увеличена)"),
    ("turgor", "🤚 Тургор кожи (нормальный/снижен)"),
    ("temp", "🌡️ Температура тела"),
    ("nodes", "🪢 Периферические лимфоузлы (не увеличены/увеличены)"),
    ("throat", "👄 Зев (не гиперемирован/гиперемирован)"),
    ("m1", "Mallampati класс 1 (да/нет)"),
    ("m2", "Mallampati класс 2 (да/нет)"),
    ("m3", "Mallampati класс 3 (да/нет)"),
    ("m4", "Mallampati класс 4 (да/нет)"),
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
    ("a1", "ASA I (да/нет)"),
    ("a2", "ASA II (да/нет)"),
    ("a3", "ASA III (да/нет)"),
    ("a4", "ASA IV (да/нет)"),
    ("a5", "ASA V (да/нет)"),
    ("aE", "ASA E (да/нет)"),
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["step"] = 0
    await update.message.reply_text(
        "👨‍⚕️ **Заполнение осмотра анестезиолога**\n\n"
        "Я задам несколько вопросов. Отвечайте текстом.\n"
        "Для отмены введите /cancel\n\n"
        f"{FIELDS[0][1]}:",
        parse_mode="Markdown"
    )
    return STATE_LIST[0]

async def handle_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    data = context.user_data
    template_path = "template.docx"

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

    # Замена в таблицах (на всякий случай)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for key, value in data.items():
                    placeholder = f"{{{{{key}}}}}"
                    if placeholder in cell.text:
                        cell.text = cell.text.replace(placeholder, str(value))

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        doc.save(tmp.name)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=f"осмотр_{data.get('fio', 'patient')}.docx",
            caption="📄 Осмотр анестезиолога готов."
        )

    os.unlink(tmp_path)
    await update.message.reply_text("Для нового осмотра нажмите /start")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Заполнение отменено. Чтобы начать заново, введите /start")
    return ConversationHandler.END

async def setup_webhook(application):
    webhook_url = f"{URL}/telegram"
    await application.bot.set_webhook(url=webhook_url, allowed_updates=Update.ALL_TYPES)
    logging.info(f"Webhook set to {webhook_url}")

async def main():
    application = Application.builder().token(TOKEN).updater(None).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={state: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_field)] for state in STATE_LIST},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))

    await setup_webhook(application)

    async def telegram_webhook(request: Request) -> Response:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return Response()

    async def health_check(request: Request) -> PlainTextResponse:
        return PlainTextResponse("OK")

    starlette_app = Starlette(routes=[
    Route("/", health_check, methods=["GET"]),   # <-- добавить эту строку
    Route("/telegram", telegram_webhook, methods=["POST"]),
    Route("/healthcheck", health_check, methods=["GET"]),
    ])

    config = uvicorn.Config(starlette_app, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
