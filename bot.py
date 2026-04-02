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

# ---------- КАЛЬКУЛЯТОР МНОАР (ИНТЕГРИРОВАН) ----------
# Состояния для МНОАР (продолжение основного диалога)
MNOAR_STATE_AGE, MNOAR_STATE_CARDIO, MNOAR_STATE_LUNG, MNOAR_STATE_OP = range(100, 104)

async def mnoar_start(update, context):
    await update.message.reply_text(
        "🧮 **Калькулятор МНОАР**\n\n1️⃣ Возраст:\n- до 60 → 0 баллов\n- 60–70 → 1 балл\n- старше 70 → 2 балла\n\nСколько лет пациенту?",
        parse_mode="Markdown"
    )
    return MNOAR_STATE_AGE

async def mnoar_age(update, context):
    try:
        age = int(update.message.text.strip())
        points = 0 if age < 60 else 1 if age <= 70 else 2
        context.user_data['mnoar_points'] = points
        await update.message.reply_text(
            f"✅ {points} баллов.\n\n2️⃣ Сердечно-сосудистые заболевания:\n- нет → 0\n- компенсированные → 1\n- декомпенсированные → 3\n\nВыберите вариант:",
            reply_markup=make_keyboard(["нет", "компенсированные", "декомпенсированные"])
        )
        return MNOAR_STATE_CARDIO
    except ValueError:
        await update.message.reply_text("❌ Введите число (возраст):")
        return MNOAR_STATE_AGE

async def mnoar_cardio(update, context):
    ans = update.message.text.strip().lower()
    points = 1 if "компенсир" in ans else 3 if "декомпенсир" in ans else 0
    context.user_data['mnoar_points'] += points
    await update.message.reply_text(
        f"✅ +{points} (всего {context.user_data['mnoar_points']})\n\n3️⃣ Заболевания лёгких:\n- нет → 0\n- ХОБЛ/астма → 1\n- дыхательная недостаточность → 3\n\nВыберите:",
        reply_markup=make_keyboard(["нет", "ХОБЛ/астма", "дыхательная недостаточность"])
    )
    return MNOAR_STATE_LUNG

async def mnoar_lung(update, context):
    ans = update.message.text.strip().lower()
    points = 1 if "хобл" in ans or "астма" in ans else 3 if "дыхательная" in ans else 0
    context.user_data['mnoar_points'] += points
    await update.message.reply_text(
        f"✅ +{points} (всего {context.user_data['mnoar_points']})\n\n4️⃣ Характер операции:\n- малая → 0\n- средняя → 1\n- большая → 2\n- экстренная → 3\n\nВыберите:",
        reply_markup=make_keyboard(["малая", "средняя", "большая", "экстренная"])
    )
    return MNOAR_STATE_OP

async def mnoar_op(update, context):
    ans = update.message.text.strip().lower()
    points = 0 if "малая" in ans else 1 if "средняя" in ans else 2 if "большая" in ans else 3 if "экстренная" in ans else 0
    total = context.user_data['mnoar_points'] + points
    risk = "низкий" if total <= 2 else "средний" if total <= 5 else "высокий"
    result = f"{total} баллов – {risk} риск"
    context.user_data['mnoar_result'] = result
    context.user_data['mnoar'] = result  # сохраняем в основное поле
    await update.message.reply_text(f"✅ Итог МНОАР: {result}", reply_markup=ReplyKeyboardMarkup([], resize_keyboard=True))
    # Возвращаемся к основному диалогу
    step = context.user_data.get("step", 0)
    if step < len(FIELDS):
        next_field = FIELDS[step]
        kb = make_keyboard(next_field[2], "choice" in next_field[3])
        await update.message.reply_text(next_field[1], reply_markup=kb)
        return STATE_LIST[step]
    else:
        return await generate_document(update, context)

# ---------- ОСНОВНОЙ ОПРОС ----------
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
    ("history", "📋 Анамнез заболевания", ["обследован амбулаторно, определены показания к операции", "госпитализирован срочно, обследован для операции"], "choice_with_custom"),
    ("concomitant", "🩺 Сопутствующие заболевания (можно несколько)", ["сахарный диабет 1 типа", "сахарный диабет 2 типа", "гипертоническая болезнь", "гипертиреоз", "гипотиреоз", "ОИМ", "ОНМК"], "choice_with_custom_multiple"),
    ("meds", "💊 Постоянный приём лекарств", None, "text"),
    ("allergy", "🌿 Аллергологический анамнез", ["нет", "есть (указать аллерген и проявление)"], "choice_with_custom"),
    ("blood", "🩸 Переливания крови", ["нет", "да, без осложнений", "да, с осложнениями"], "choice_with_custom"),
    ("neuro", "🧠 Нейроинфекции, ЧМТ", ["нет", "да"], "choice_with_custom"),
    ("inf", "🦠 Инфекционные заболевания (ВИЧ, гепатиты)", ["нет", "ВИЧ", "гепатит B", "гепатит C", "другое"], "choice_with_custom"),
    ("ops", "🔪 Оперативные вмешательства в прошлом", ["нет", "да (какие?)"], "choice_with_custom"),
    ("narc_tol", "💉 Переносимость наркозов", ["б/о", "тошнота", "головокружение", "долгое пробуждение"], "choice_with_custom_multiple"),
    ("st_gen", "😐 Общее состояние", ["удовлетворительное", "средней тяжести", "тяжелое"], "choice_with_custom"),
    ("psycho", "🧠 Сознание", ["ясное", "спутанное", "оглушение"], "choice_with_custom"),
    ("body_type", "🏋️ Телосложение", ["астеник", "нормостеник", "гиперстеник"], "choice_with_custom"),
    # Поле "obesity" будет рассчитано автоматически, не задаём вопрос
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
    ("lab", "🧪 Лаборатория", ["в пределах референсных значений"], "choice_with_custom"),
    ("ecg", "📈 ЭКГ", ["норма", "возрастные изменения"], "choice_with_custom"),
    ("asa", "ASA", ["I", "II", "III", "IV", "V", "E"], "choice_with_custom"),
    ("mnoar", "📋 МНОАР (калькулятор)", None, "mnoar_calc"),  # специальный тип
    ("op_vol", "📐 Объём операции", None, "text"),
    ("anes_type", "💉 Тип анестезии", ["тотальная", "сочетанная", "комбинированная", "в/венная", "ингаляционная", "эпидуральная", "субарахноидальная", "проводниковая"], "choice_with_custom"),
    ("add_test", "🔬 Дообследование", None, "text"),
    ("prep", "🛁 Предоперационная подготовка (кроме клизмы)", ["согласно внутреннему протоколу"], "choice_with_custom"),
    ("p_date", "📅 Дата премедикации", None, "text"),
    ("sib_dose", "💊 Сибазон (доза в мл)", None, "number"),
    ("time_before_op", "⏱️ За сколько минут до операции", None, "number"),
    ("prom_dose", "💉 Промедол 2% (доза в мл)", None, "number"),
    ("doc_name", "✍️ Фамилия врача", None, "text"),
]

STATE_LIST = list(range(len(FIELDS)))

# Функция для авто-расчёта степени ожирения по ИМТ
def get_obesity_grade(bmi):
    try:
        bmi_val = float(bmi)
        if bmi_val < 18.5:
            return "дефицит массы тела"
        elif bmi_val < 25:
            return "норма"
        elif bmi_val < 30:
            return "ожирение 1 степени"
        elif bmi_val < 35:
            return "ожирение 2 степени"
        elif bmi_val < 40:
            return "ожирение 3 степени"
        else:
            return "ожирение 4 степени"
    except:
        return ""

async def start(update, context):
    context.user_data.clear()
    context.user_data["step"] = 0
    q = FIELDS[0][1]
    kb = make_keyboard(FIELDS[0][2], "choice" in FIELDS[0][3])
    await update.message.reply_text("👨‍⚕️ **Осмотр анестезиолога**\n/cancel для отмены\n\n" + q, parse_mode="Markdown", reply_markup=kb)
    return STATE_LIST[0]

async def handle_field(update, context):
    step = context.user_data.get("step", 0)
    if step >= len(FIELDS):
        return await generate_document(update, context)

    field_name, question, options, input_type = FIELDS[step]
    answer = update.message.text.strip()

    # Свой вариант
    if answer == "✏️ Свой вариант":
        await update.message.reply_text("Введите свой вариант:")
        return STATE_LIST[step]

    # Множественный выбор
    if input_type == "choice_with_custom_multiple":
        multi_key = f"multi_{field_name}"
        if multi_key not in context.user_data:
            context.user_data[multi_key] = []
        if answer not in ["Готово", "закончить"]:
            context.user_data[multi_key].append(answer)
            await update.message.reply_text(f"✅ Добавлено: {answer}\nМожно добавить ещё или 'Готово'", reply_markup=make_keyboard(options + ["Готово"], False))
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

    # Калькулятор МНОАР
    if input_type == "mnoar_calc":
        return await mnoar_start(update, context)

    # Валидация числа
    if input_type == "number":
        try:
            float(answer)
        except:
            await update.message.reply_text("❌ Введите число:")
            return STATE_LIST[step]

    # Проверка выбора из кнопок
    if "choice" in input_type and options and answer not in options:
        await update.message.reply_text(f"❌ Выберите из кнопок: {', '.join(options)}")
        return STATE_LIST[step]

    context.user_data[field_name] = answer

    # Авто-расчёт ИМТ и степени ожирения
    if field_name == "w" and "h" in context.user_data and "bmi" not in context.user_data:
        try:
            h = float(context.user_data["h"]) / 100
            w = float(answer)
            bmi = round(w / (h*h), 1)
            context.user_data["bmi"] = str(bmi)
            obesity = get_obesity_grade(bmi)
            context.user_data["obesity"] = obesity
            logging.info(f"ИМТ: {bmi}, Ожирение: {obesity}")
        except Exception as e:
            logging.error(f"Ошибка расчёта ИМТ: {e}")
    elif field_name == "h" and "w" in context.user_data and "bmi" not in context.user_data:
        try:
            h = float(answer) / 100
            w = float(context.user_data["w"])
            bmi = round(w / (h*h), 1)
            context.user_data["bmi"] = str(bmi)
            obesity = get_obesity_grade(bmi)
            context.user_data["obesity"] = obesity
        except:
            pass

    step += 1
    context.user_data["step"] = step
    if step >= len(FIELDS):
        await update.message.reply_text("✅ Формирую документ...")
        return await generate_document(update, context)
    else:
        nf = FIELDS[step]
        kb = make_keyboard(nf[2], "choice" in nf[3])
        await update.message.reply_text(nf[1], reply_markup=kb)
        return STATE_LIST[step]

async def generate_document(update, context):
    data = context.user_data
    if not os.path.exists("template.docx"):
        await update.message.reply_text("❌ Файл template.docx не найден!")
        return ConversationHandler.END
    doc = Document("template.docx")
    for para in doc.paragraphs:
        for k, v in data.items():
            para.text = para.text.replace(f"{{{{{k}}}}}", str(v))
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for k, v in data.items():
                    cell.text = cell.text.replace(f"{{{{{k}}}}}", str(v))
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        doc.save(tmp.name)
        path = tmp.name
    with open(path, "rb") as f:
        await update.message.reply_document(f, filename=f"осмотр_{data.get('fio','patient')}.docx", caption="📄 Осмотр готов!")
    os.unlink(path)
    await update.message.reply_text("/start для нового осмотра", reply_markup=ReplyKeyboardMarkup([], resize_keyboard=True))
    return ConversationHandler.END

async def cancel(update, context):
    await update.message.reply_text("Отменено. /start", reply_markup=ReplyKeyboardMarkup([], resize_keyboard=True))
    return ConversationHandler.END

# ---------- ЗАПУСК ----------
async def setup_webhook(app):
    await app.bot.set_webhook(url=f"{URL}/telegram", allowed_updates=Update.ALL_TYPES)
    logging.info(f"Webhook set to {URL}/telegram")

async def main():
    app = Application.builder().token(TOKEN).updater(None).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={i: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_field)] for i in STATE_LIST},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("start", start))

    # Регистрируем состояния МНОАР как часть основного диалога (они уже обрабатываются в handle_field, но нужно, чтобы переходы работали)
    # Для корректной работы добавим временные обработчики для состояний МНОАР
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\d+$'), mnoar_age), group=1)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(нет|компенсированные|декомпенсированные)'), mnoar_cardio), group=1)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(нет|ХОБЛ/астма|дыхательная недостаточность)'), mnoar_lung), group=1)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'(малая|средняя|большая|экстренная)'), mnoar_op), group=1)

    await setup_webhook(app)
    await app.initialize()
    await app.start()

    async def webhook(req: Request) -> Response:
        upd = Update.de_json(await req.json(), app.bot)
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
