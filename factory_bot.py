import os
import datetime
from flask import Flask, request
import telebot
from telebot import types
from openpyxl import Workbook, load_workbook

# === Переменные окружения ===
TOKEN = os.environ.get("TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
PORT = int(os.environ.get("PORT", 10000))

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# === Глобальные переменные ===
STATE = {}
DATA = {}
PHOTO_LINK = {}
EXCEL_FILE = "orders.xlsx"

# === Вспомогательные функции ===
def ensure_excel_file():
    if not os.path.exists(EXCEL_FILE):
        wb = Workbook()
        ws = wb.active
        ws.append(["Дата", "Имя", "Username", "Фото", "Реквизиты"])
        wb.save(EXCEL_FILE)

def save_to_excel(user, photo_path, requisites):
    ensure_excel_file()
    wb = load_workbook(EXCEL_FILE)
    ws = wb.active
    ws.append([
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        user.first_name,
        f"@{user.username}" if user.username else "—",
        photo_path,
        requisites
    ])
    wb.save(EXCEL_FILE)

# === Команды ===
@bot.message_handler(commands=['start'])
def start(message):
    print(f"[LOG] /start от {message.chat.id}")
    bot.send_message(message.chat.id, "Привет! Бот работает. Пришлите фото изделия.")

@bot.message_handler(commands=['contact'])
def contact(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📲 Связаться в Telegram", url="https://t.me/xatyba"))
    bot.send_message(message.chat.id, "Менеджер на связи👇", reply_markup=markup)

@bot.message_handler(commands=['excel', 'клиенты'])
def send_excel_to_owner(message):
    if message.chat.id == OWNER_ID and os.path.exists(EXCEL_FILE):
        with open(EXCEL_FILE, 'rb') as f:
            bot.send_document(message.chat.id, f, caption="📊 Заявки в Excel")
    else:
        bot.send_message(message.chat.id, "Нет доступа или файл не найден.")

# === Фото от клиента ===
@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user = message.from_user
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded = bot.download_file(file_info.file_path)

    os.makedirs("photos", exist_ok=True)
    filename = f"photo_{user.id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.jpg"
    path = os.path.join("photos", filename)
    with open(path, 'wb') as f:
        f.write(downloaded)

    DATA[message.chat.id] = {"photo_path": path, "user": user}
    STATE[message.chat.id] = 'AWAIT_PRICE'

    bot.send_message(message.chat.id, "✅ Фото получено, передано на оценку.")

    caption = (
        f"🆕 Фото клиента:\n"
        f"👤 {user.first_name} (@{user.username or '—'})\n"
        f"ID: {user.id}\nОтветьте на это сообщение с ценой."
    )
    with open(path, 'rb') as img:
        sent = bot.send_photo(OWNER_ID, img, caption=caption)
        PHOTO_LINK[sent.message_id] = message.chat.id

# === Ответ владельца (ценник) ===
@bot.message_handler(func=lambda m: m.chat.id == OWNER_ID and m.reply_to_message)
def owner_reply(message):
    reply_id = message.reply_to_message.message_id
    client_id = PHOTO_LINK.get(reply_id)

    if not client_id:
        bot.send_message(OWNER_ID, "❌ Клиент не найден.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Устраивает", "Не устраивает")
    bot.send_message(client_id, f"💰 Цена: {message.text}. Устраивает?", reply_markup=markup)
    STATE[client_id] = 'AWAIT_CONFIRM'
    del PHOTO_LINK[reply_id]

# === Подтверждение от клиента ===
@bot.message_handler(func=lambda m: STATE.get(m.chat.id) == 'AWAIT_CONFIRM')
def confirm(message):
    if message.text.lower() == "устраивает":
        bot.send_message(message.chat.id, "📄 Пришлите реквизиты.", reply_markup=types.ReplyKeyboardRemove())
        STATE[message.chat.id] = 'AWAIT_REQUISITES'
    else:
        bot.send_message(message.chat.id, "Хорошо, на связи!", reply_markup=types.ReplyKeyboardRemove())
        STATE.pop(message.chat.id, None)
        DATA.pop(message.chat.id, None)

# === Получение реквизитов ===
@bot.message_handler(func=lambda m: STATE.get(m.chat.id) == 'AWAIT_REQUISITES')
def handle_requisites(message):
    user = message.from_user
    path = DATA.get(message.chat.id, {}).get("photo_path")
    if not path:
        bot.send_message(message.chat.id, "Ошибка. Начните заново: /start")
        return

    save_to_excel(user, path, message.text)
    with open(path, 'rb') as img:
        bot.send_photo(OWNER_ID, img, caption=f"📄 Реквизиты от @{user.username or '—'}:\n{message.text}")

    bot.send_message(message.chat.id, "✅ Спасибо! Мы свяжемся с вами.")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📲 Связаться с менеджером", url="https://t.me/xatyba"))
    bot.send_message(message.chat.id, "Если что — нажмите кнопку:", reply_markup=markup)

    STATE.pop(message.chat.id, None)
    DATA.pop(message.chat.id, None)

# === Webhook ===
@app.route("/", methods=['GET'])
def index():
    return "Bot is running", 200

@app.route("/", methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = telebot.types.Update.de_json(request.data.decode("utf-8"))
        bot.process_new_updates([update])
        return "ok", 200
    return "unsupported", 400

# === Установка Webhook ===
bot.remove_webhook()
bot.set_webhook(url="https://factory-morozov-bot.onrender.com")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
