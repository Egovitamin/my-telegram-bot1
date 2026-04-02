import os
import asyncio
import logging
import tempfile
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ConversationHandler, MessageHandler, filters, ContextTypes
from docx import Document
import uvicorn

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["BOT_TOKEN"]
URL = os.environ["RENDER_EXTERNAL_URL"]
PORT = int(os.getenv("PORT", 8000))

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def make_keyboard(options, include_custom=True):
    if not options:
        return None
    buttons = [[KeyboardButton(opt)] for opt in options]
    if include_custom:
        buttons.append([KeyboardButton("✏️ Свой вариант")])
    return ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True)

# ---------- КАЛЬКУЛЯТОР МНОАР (возвращает результат через user_data) ----------
# Состояния для калькулятора
MNOAR_AGE, MNOAR_CARDIO, MNOAR_LUNG, MNOAR_OP = range(10, 14)

async def mnoar_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запускает калькулятор МНОАР"""
    await update.message.reply_text(
        "🧮 **Калькулятор МНОАР**\n\n"
        "1️⃣ Возраст:\n- до 60 лет → 0 баллов\n- 60–70 лет → 1 балл\n- старше 70 → 2 балла\n\n"
        "Введите возраст (лет):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([], resize_keyboard=True)
    )
    return MNOAR_AGE

async def mnoar_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text.strip())
        if age < 60:
            points = 0
        elif age <= 70:
            points = 1
        else:
            points = 2
        context.user_data['mnoar_points'] = points
        await update.message.reply_text(
            f"✅ Возраст {age} → {points} баллов.\n\n"
            "2️⃣ Сердечно-сосудистые заболевания:\n"
            "- нет → 0 баллов\n- компенсированные → 1 балл\n- декомпенсированные → 3 балла\n\n"
            "Выберите вариант:",
            reply_markup=make_keyboard(["нет", "компенсированные", "декомпенсированные"])
        )
        return MNOAR_CARDIO
    except ValueError:
        await update.message.reply_text("❌ Введите число (возраст):")
        return MNOAR_AGE

async def mnoar_cardio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.message.text.strip().lower()
    if "компенсир" in ans:
        points = 1
    elif "декомпенсир" in ans:
        points = 3
    else:
        points = 0
    context.user_data['mnoar_points'] += points
    await update.message.reply_text(
        f"✅ Добавлено {points} баллов. Сумма: {context.user_data['mnoar_points']}\n\n"
        "3️⃣ Заболевания лёгких:\n"
        "- нет → 0 баллов\n- ХОБЛ/бронхиальная астма → 1 балл\n- дыхательная недостаточность → 3 балла\n\n"
        "Выберите вариант:",
        reply_markup=make_keyboard(["нет", "ХОБЛ/астма", "дыхательная недостаточность"])
    )
    return MNOAR_LUNG

async def mnoar_lung(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.message.text.strip().lower()
    if "хобл" in ans or "астма" in ans:
        points = 1
    elif "дыхательная" in ans:
        points = 3
    else:
        points = 0
    context.user_data['mnoar_points'] += points
    await update.message.reply_text(
        f"✅ Добавлено {points} баллов. Сумма: {context.user_data['mnoar_points']}\n\n"
        "4️⃣ Характер операции:\n"
        "- малая (до 30 мин) → 0 баллов\n- средняя (30-120 мин) → 1 балл\n- большая (>120 мин) → 2 балла\n- экстренная → 3 балла\n\n"
        "Выберите вариант:",
        reply_markup=make_keyboard(["малая", "средняя", "большая", "экстренная"])
    )
    return MNOAR_OP

async def mnoar_op(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.message.text.strip().lower()
    if "малая" in ans:
        points = 0
    elif "средняя" in ans:
        points = 1
    elif "большая" in ans:
        points = 2
    elif "экстренная" in ans:
        points = 3
    else:
        points = 0
    total = context.user_data['mnoar_points'] + points
    if total <= 2:
        risk = "низкий риск"
    elif total <= 5:
        risk = "средний риск"
    else:
        risk = "высокий риск"
    result = f"{total} баллов – {risk}"
    context.user_data['mnoar_result'] = result
    # Сохраняем результат в основное поле
    context.user_data['mnoar'] = result
    await update.message.reply_text(
        f"✅ **Результат МНОАР:** {result}\n\nВозвращаемся к основному опросу.",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([], resize_keyboard=True)
    )
    # Завершаем калькулятор и возвращаем управление основному диалогу
    return ConversationHandler.END

async def mnoar_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Калькулятор МНОАР отменён. Продолжаем опрос.", reply_markup=ReplyKeyboardMarkup([], resize_keyboard=True))
    return ConversationHandler.END

# ---------- ОСНОВНОЙ ОПРОС ----------
# Определяем поля. Тип 'mnoar_calc' означает, что нужно запустить калькулятор и результат подставить в это поле
FIELDS = [
    ("date", "📅 Дата (например, 12.04.2026)", None, "text"),
    ("time", "⏰ Время (например, 10:30)", None, "text"),
    ("fio", "👤 ФИО пациента", None, "text"),
    ("age", "📆 Возраст (лет)", None, "number"),
    ("h", "📏 Рост (см)", None, "number"),
    ("w", "⚖️ Вес (кг)", None, "number"),
    ("admission_order", "🏥 Порядок поступления", ["плановый", "срочный"], "choice_with_custom"),
    ("diagnosis", "📌 Диагноз (основной)", None, "text"),
    ("complaints", "💬 Жалобы", ["активно нет", "болевой синдром в пояснице", "болевой синдром с иррадиацией"], "choice_with_custom"),
    ("history", "📋 Анамнез заболевания", ["дообследован амбулаторно, показания к операции", "госпитализирован срочно, обследован"], "choice_with_custom"),
    ("concomitant", "🩺 Сопутствующие заболевания", ["сахарный диабет 1 типа", "сахарный диабет 2 типа", "гипертоническая болезнь", "гипертиреоз", "гипотиреоз"], "choice_with_custom_multiple"),
    ("meds", "💊 Постоянный приём лекарств", None, "text"),
    ("allergy", "🌿 Аллергологический анамнез", ["нет", "есть (указать аллерген)"], "choice_with_custom"),
    ("blood", "🩸 Переливания крови", ["нет", "да, без осложнений", "да, с осложнениями"], "choice_with_custom"),
    ("neuro", "🧠 Нейроинфекции, ЧМТ", ["нет", "да"], "choice_with_custom"),
    ("inf", "🦠 Инфекционные заболевания (ВИЧ, гепатиты)", None, "text"),
    ("ops", "🔪 Оперативные вмешательства в прошлом", ["нет", "да (какие?)"], "choice_with_custom"),
    ("narc_tol", "💉 Переносимость наркозов", ["б/о", "тошнота", "головокружение", "долгое пробуждение"], "choice_with_custom_multiple"),
    ("specs", "📌 Особенности", None, "text"),
    ("st_gen", "😐 Общее состояние", ["удовлетворительное", "средней тяжести", "тяжелое"], "choice_with_custom"),
    ("psycho", "🧠 Сознание", ["ясное", "спутанное", "оглушение"], "choice_with_custom"),
    ("body_type", "🏋️ Телосложение", ["астеник", "нормостеник", "гиперстеник"], "choice_with_custom"),
    ("obesity", "🍔 Ожирение (степень)", None, "text"),
    ("skin", "🩻 Кожные покровы", ["обычной окраски", "бледные", "гиперемированы"], "choice_with_custom"),
    ("moist", "💧 Влажность кожи", ["нормальная", "снижена", "потливость"], "choice_with_custom"),
    ("thyroid", "🦋 Щитовидная железа", ["не увеличена", "увеличена"], "choice_with_custom"),
    ("turgor", "🤚 Тургор кожи", ["нормальный", "снижен"], "choice_with_custom"),
    ("temp", "🌡️ Температура тела", None, "number"),
    ("nodes", "🪢 Лимфоузлы", ["не увеличены", "увеличены"], "choice_with_custom"),
    ("throat", "👄 Зев", ["не гиперемирован", "гиперемирован"], "choice_with_custom"),
    ("mallampaty", "😮 Mallampati", ["1", "2", "3", "4"], "choice_with_custom"),
    ("teeth", "🦷 Зубы/протезы", ["санированы", "не санированы, протезов нет", "есть съемные протезы"], "choice_with_custom"),
    ("edema", "💦 Отёки", ["нет", "есть (где?)"], "choice_with_custom"),
    ("breath", "🌬️ Дыхание", ["везикулярное", "бронхиальное"], "choice_with_custom"),
    ("rr", "📈 ЧДД (в мин)", None, "number"),
    ("wheeze", "🎵 Хрипы", ["нет", "сухие", "влажные", "сухие и влажные"], "choice_with_custom"),
    ("h_sounds", "❤️ Тоны сердца", ["ясные, ритмичные", "приглушены, ритмичные", "глухие, аритмичные"], "choice_with_custom"),
    ("ps", "💓 Пульс (уд/мин)", None, "number"),
    ("p_def", "📉 Дефицит пульса", ["нет", "есть"], "choice_with_custom"),
    ("ad_s", "🩸 АД систолическое", None, "number"),
    ("ad_d", "🩸 АД диастолическое", None, "number"),
    ("spo2", "🫁 SpO2 (%)", None, "number"),
    ("tongue", "👅 Язык", ["влажный, не обложен", "сухой, обложен"], "choice_with_custom"),
    ("abd", "🤰 Живот", ["мягкий, безболезненный", "напряжённый, болезненный"], "choice_with_custom"),
    ("perist", "🔊 Перистальтика", ["выслушивается, нормальная", "ослаблена", "усилена"], "choice_with_custom"),
    ("liver", "🧬 Печень", ["не увеличена", "увеличена"], "choice_with_custom"),
    ("ur", "🚽 Мочеиспускание", ["свободное", "затруднённое"], "choice_with_custom"),
    ("stool", "💩 Стул", ["норма", "жидкий", "задержка (дней)"], "choice_with_custom"),
    ("hvn", "🦵 ХВН ног", ["нет", "есть (степень)"], "choice_with_custom"),
    ("lab", "🧪 Лаборатория", None, "text"),
    ("ecg", "📈 ЭКГ", None, "text"),
    ("asa", "ASA", ["I", "II", "III", "IV", "V", "E"], "choice_with_custom"),
    ("mnoar", "📋 МНОАР (запустится калькулятор)", None, "mnoar_calc"),  # специальный тип
    ("op_vol", "📐 Объём операции", None, "text"),
    ("anes_type", "💉 Тип анестезии", ["тотальная", "сочетанная", "комбинированная", "в/венная", "ингаляционная", "эпидуральная", "субарахноидальная", "проводниковая"], "choice_with_custom"),
    ("add_test", "🔬 Дообследование", None, "text"),
    ("prep", "🛁 Предоперационная подготовка (кроме клизмы)", None, "text"),
    ("p_date", "📅 Дата премедикации", None, "text"),
    ("sib_dose", "💊 Сибазон (доза в мл)", None, "number"),
    ("time_before_op", "⏱️ За сколько минут до операции", None, "number"),
    ("prom_dose", "💉 Промедол 2% (доза в мл)", None, "number"),
    ("doc_name", "✍️ Фамилия врача", None, "text"),
]

STATE_LIST = list(range(len(FIELDS)))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["step"] = 0
    # Сохраняем текущий основной диалог, чтобы потом вернуться
    context.user_data["main_conversation"] = True
    q = FIELDS[0][1]
    kb = make_keyboard(FIELDS[0][2], "choice" in FIELDS[0][3])
    await update.message.reply_text(
        "👨‍⚕️ **Осмотр анестезиолога**\n/cancel для отмены\n\n" + q,
        parse_mode="Markdown",
        reply_markup=kb
    )
    return STATE_LIST[0]

async def handle_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data.get("step", 0)
    if step >= len(FIELDS):
        return await generate_document(update, context)

    field_name, question, options, input_type = FIELDS[step]
    answer = update.message.text.strip()

    # Если это ответ на "Свой вариант"
    if answer == "✏️ Свой вариант":
        await update.message.reply_text("Введите свой вариант текстом:")
        return STATE_LIST[step]

    # Множественный выбор
    if input_type == "choice_with_custom_multiple":
        multi_key = f"multi_{field_name}"
        if multi_key not in context.user_data:
            context.user_data[multi_key] = []
        if answer not in ["Готово", "закончить"]:
            context.user_data[multi_key].append(answer)
            await update.message.reply_text(
                f"✅ Добавлено: {answer}\nМожно добавить ещё или напишите 'Готово'",
                reply_markup=make_keyboard(options + ["Готово"], False)
            )
            return STATE_LIST[step]
        else:
            context.user_data[field_name] = ", ".join(context.user_data[multi_key])
            del context.user_data[multi_key]
            step += 1
            context.user_data["step"] = step
            if step >= len(FIELDS):
                await update.message.reply_text("✅ Формирую документ...")
                return await generate_document(update, context)
            next_f = FIELDS[step]
            kb = make_keyboard(next_f[2], "choice" in next_f[3])
            await update.message.reply_text(next_f[1], reply_markup=kb)
            return STATE_LIST[step]

    # Если поле требует калькулятора МНОАР
    if input_type == "mnoar_calc":
        # Запускаем калькулятор, но не увеличиваем шаг
        context.user_data["pending_field"] = field_name
        await update.message.reply_text("Запускаю калькулятор МНОАР...", reply_markup=ReplyKeyboardMarkup([], resize_keyboard=True))
        return await mnoar_start(update, context)

    # Валидация числа
    if input_type == "number":
        try:
            float(answer)
        except ValueError:
            await update.message.reply_text("❌ Введите число (например, 70):")
            return STATE_LIST[step]

    # Проверка выбора из кнопок (если не "свой вариант")
    if "choice" in input_type and options and answer not in options:
        await update.message.reply_text(f"❌ Выберите вариант из кнопок: {', '.join(options)}")
        return STATE_LIST[step]

    # Сохраняем ответ
    context.user_data[field_name] = answer

    # Автоматический расчёт ИМТ после ввода веса
    if field_name == "w" and "h" in context.user_data:
        try:
            h_cm = float(context.user_data["h"])
            w_kg = float(answer)
            h_m = h_cm / 100.0
            bmi = round(w_kg / (h_m * h_m), 1)
            context.user_data["bmi"] = str(bmi)
            logging.info(f"Рассчитан ИМТ: {bmi}")
        except Exception as e:
            logging.error(f"Ошибка расчёта ИМТ: {e}")

    step += 1
    context.user_data["step"] = step

    if step >= len(FIELDS):
        await update.message.reply_text("✅ Все данные собраны. Формирую документ...")
        return await generate_document(update, context)
    else:
        next_f = FIELDS[step]
        kb = make_keyboard(next_f[2], "choice" in next_f[3])
        await update.message.reply_text(next_f[1], reply_markup=kb)
        return STATE_LIST[step]

async def generate_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    if not os.path.exists("template.docx"):
        await update.message.reply_text("❌ Файл template.docx не найден!")
        return ConversationHandler.END

    doc = Document("template.docx")
    # Замена в параграфах
    for para in doc.paragraphs:
        for k, v in data.items():
            placeholder = f"{{{{{k}}}}}"
            if placeholder in para.text:
                para.text = para.text.replace(placeholder, str(v))
    # Замена в таблицах
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for k, v in data.items():
                    placeholder = f"{{{{{k}}}}}"
                    if placeholder in cell.text:
                        cell.text = cell.text.replace(placeholder, str(v))

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        doc.save(tmp.name)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=f"осмотр_{data.get('fio', 'patient')}.docx",
            caption="📄 Осмотр анестезиолога готов!"
        )
    os.unlink(tmp_path)
    await update.message.reply_text("Для нового осмотра нажмите /start", reply_markup=ReplyKeyboardMarkup([], resize_keyboard=True))
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Заполнение отменено. /start для нового осмотра", reply_markup=ReplyKeyboardMarkup([], resize_keyboard=True))
    return ConversationHandler.END

# ---------- ОБРАБОТЧИК ВОЗВРАТА ИЗ КАЛЬКУЛЯТОРА ----------
async def after_mnoar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вызывается после завершения калькулятора, чтобы продолжить основной диалог"""
    # Калькулятор уже сохранил результат в context.user_data['mnoar']
    # Теперь нужно продолжить с того же шага, на котором остановились
    step = context.user_data.get("step", 0)
    # Увеличиваем шаг, так как поле mnoar уже обработано
    step += 1
    context.user_data["step"] = step
    if step >= len(FIELDS):
        await update.message.reply_text("✅ Все данные собраны. Формирую документ...")
        return await generate_document(update, context)
    else:
        next_f = FIELDS[step]
        kb = make_keyboard(next_f[2], "choice" in next_f[3])
        await update.message.reply_text(next_f[1], reply_markup=kb)
        return STATE_LIST[step]

# ---------- ЗАПУСК ----------
async def setup_webhook(app):
    await app.bot.set_webhook(url=f"{URL}/telegram", allowed_updates=Update.ALL_TYPES)
    logging.info(f"Webhook set to {URL}/telegram")

async def main():
    app = Application.builder().token(TOKEN).updater(None).build()

    # Основной диалог
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={i: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_field)] for i in STATE_LIST},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)

    # Диалог калькулятора МНОАР
    mnoar_conv = ConversationHandler(
        entry_points=[],  # entry_points пуст, запускается только из основного диалога
        states={
            MNOAR_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, mnoar_age)],
            MNOAR_CARDIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, mnoar_cardio)],
            MNOAR_LUNG: [MessageHandler(filters.TEXT & ~filters.COMMAND, mnoar_lung)],
            MNOAR_OP: [MessageHandler(filters.TEXT & ~filters.COMMAND, mnoar_op)],
        },
        fallbacks=[CommandHandler("cancel_mnoar", mnoar_cancel)],
    )
    app.add_handler(mnoar_conv)

    # Обработчик возврата после калькулятора (можно использовать как fallback, но проще добавить обработчик в конец)
    # Вместо этого мы после завершения калькулятора вызовем after_mnoar, но пока оставим так.

    await setup_webhook(app)
    await app.initialize()
    await app.start()

    async def webhook(req: Request) -> Response:
        data = await req.json()
        upd = Update.de_json(data, app.bot)
        await app.process_update(upd)
        return Response()

    star = Starlette(routes=[
        Route("/", lambda r: PlainTextResponse("OK"), methods=["GET"]),
        Route("/telegram", webhook, methods=["POST"]),
        Route("/healthcheck", lambda r: PlainTextResponse("OK"), methods=["GET"]),
    ])
    cfg = uvicorn.Config(star, host="0.0.0.0", port=PORT, log_level="info")
    server = uvicorn.Server(cfg)
    await server.serve()
    await app.stop()

if __name__ == "__main__":
    asyncio.run(main())
