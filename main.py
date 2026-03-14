from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot is running"

def run():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run)
    t.start()
    
import asyncio
import random
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

BOT_TOKEN = "8535631318:AAHbjowo_pWZSitrpdNiA-W8quxZ_sYgOeI"

dp = Dispatcher()

# ==========================
# СЕССИИ
# ==========================

user_sessions = {}
current_group = {}  # user_id -> group2/group3/group4


# ==========================
# БАЗА
# ==========================

def db(user_id: int):
    group = current_group.get(user_id, "group3")
    return sqlite3.connect(f"{group}.db")


def init_results_table():
    con = sqlite3.connect("results.db")
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        total INTEGER,
        correct INTEGER,
        mode TEXT,
        created_at TEXT
    )
    """)
    con.commit()
    con.close()


init_results_table()

def init_favorites_table():
    con = sqlite3.connect("favorites.db")
    cur = con.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        question_id INTEGER,
        group_name TEXT
    )
    """)

    con.commit()
    con.close()


init_favorites_table()


# ==========================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================

def format_question(qid, text, opts):
    lines = [f"📘 Вопрос №{qid}\n", text.strip(), ""]
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    seen = set()
    filtered = []

    for opt in opts:
        opt_text = opt[2].strip()
        if opt_text not in seen:
            seen.add(opt_text)
            filtered.append(opt)

    for i, (_, _, opt_text, _) in enumerate(filtered):
        lines.append(f"{letters[i]}) {opt_text}")

    return "\n".join(lines)


def build_keyboard(qid, opts):
    kb = InlineKeyboardBuilder()
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    seen = set()
    filtered = []

    for opt in opts:
        opt_text = opt[2].strip()
        if opt_text not in seen:
            seen.add(opt_text)
            filtered.append(opt)

    for i in range(len(filtered)):
        kb.button(text=letters[i], callback_data=f"ans:{qid}:{i}")

    kb.adjust(4)

    kb.button(text="⭐ В избранное", callback_data=f"fav:{qid}")
    kb.button(text="⛔ Завершить тест", callback_data="finish_test")
    kb.adjust(2)

    return kb.as_markup()


def get_random_question(user_id, exclude_ids):
    con = db(user_id)
    cur = con.cursor()

    if exclude_ids:
        placeholders = ",".join("?" * len(exclude_ids))
        cur.execute(
            f"SELECT id, text, rationale FROM questions WHERE id NOT IN ({placeholders}) ORDER BY RANDOM() LIMIT 1",
            exclude_ids
        )
    else:
        cur.execute(
            "SELECT id, text, rationale FROM questions ORDER BY RANDOM() LIMIT 1"
        )

    q = cur.fetchone()
    if not q:
        con.close()
        return None

    qid, text, rationale = q

    cur.execute("""
        SELECT id, pos, text, is_correct
        FROM options
        WHERE question_id=?
        ORDER BY pos
    """, (qid,))
    opts = cur.fetchall()

    con.close()
    return qid, text, rationale, opts


def get_ordered_question(user_id, offset):
    con = db(user_id)
    cur = con.cursor()

    cur.execute("""
        SELECT id, text, rationale
        FROM questions
        ORDER BY id
        LIMIT 1 OFFSET ?
    """, (offset,))

    q = cur.fetchone()
    if not q:
        con.close()
        return None

    qid, text, rationale = q

    cur.execute("""
        SELECT id, pos, text, is_correct
        FROM options
        WHERE question_id=?
        ORDER BY pos
    """, (qid,))
    opts = cur.fetchall()

    con.close()
    return qid, text, rationale, opts


# ==========================
# START
# ==========================

@dp.message(CommandStart())
async def start(message: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="Группа II", callback_data="group_2")
    kb.button(text="Группа III", callback_data="group_3")
    kb.button(text="Группа IV", callback_data="group_4")
    kb.adjust(1)

    await message.answer(
        "Выберите группу по электробезопасности:",
        reply_markup=kb.as_markup()
    )

@dp.message(Command("restart"))
async def restart(message: Message):
    user_id = message.from_user.id

    if user_id in user_sessions:
        del user_sessions[user_id]

    if user_id in current_group:
        del current_group[user_id]

    kb = InlineKeyboardBuilder()
    kb.button(text="Группа II", callback_data="group_2")
    kb.button(text="Группа III", callback_data="group_3")
    kb.button(text="Группа IV", callback_data="group_4")
    kb.adjust(1)

    await message.answer(
        "🔄 Тест перезапущен.\n\nВыберите группу по электробезопасности:",
        reply_markup=kb.as_markup()
    )

# ==========================
# ИЗБРАННЫЕ ВОПРОСЫ
# ==========================

@dp.message(Command("favorite"))
async def show_favorites(message: Message):

    user_id = message.from_user.id

    # завершить активный тест
    if user_id in user_sessions:
        user_sessions[user_id]["finished"] = True

    con = sqlite3.connect("favorites.db")
    cur = con.cursor()

    cur.execute(
        "SELECT question_id, group_name FROM favorites WHERE user_id=?",
        (user_id,)
    )

    rows = cur.fetchall()
    con.close()

    if not rows:
        await message.answer("⭐ У вас пока нет избранных вопросов")
        return

    text = "⭐ Ваши избранные вопросы:\n\n"

    for qid, group in rows[:10]:

        db = sqlite3.connect(f"{group}.db")
        cur = db.cursor()

        cur.execute(
            "SELECT text FROM questions WHERE id=?",
            (qid,)
        )

        q = cur.fetchone()
        db.close()

        if q:
            group_name = group.replace("group", "Группа ")
            text += f"📘 {group_name} | Вопрос №{qid}\n"
            text += f"{q[0][:200]}...\n\n"

    await message.answer(text)

    # заново показываем выбор группы
    kb = InlineKeyboardBuilder()
    kb.button(text="Группа II", callback_data="group_2")
    kb.button(text="Группа III", callback_data="group_3")
    kb.button(text="Группа IV", callback_data="group_4")
    kb.adjust(1)

    await message.answer(
        "Выберите группу для нового теста:",
        reply_markup=kb.as_markup()
    )

# ==========================
# ВЫБОР ГРУППЫ
# ==========================

@dp.callback_query(F.data.startswith("group_"))
async def choose_group(call: CallbackQuery):
    user_id = call.from_user.id
    group = call.data.split("_")[1]

    current_group[user_id] = f"group{group}"

    user_sessions[user_id] = {
        "mode": None,
        "used_ids": [],
        "current_index": 0,
        "correct": 0,
        "total": 0,
        "last_question_id": None,
        "wrong_questions": [],
        "finished": False
    }

    kb = InlineKeyboardBuilder()
    kb.button(text="20 вопросов (случайно)", callback_data="mode_random")
    kb.button(text="Тест по порядку", callback_data="mode_ordered")
    kb.button(text="📖 Повторить избранные", callback_data="mode_favorites")
    kb.adjust(1)

    await call.message.answer(
        f"Вы выбрали группу {group}\n\nВыберите режим тестирования:",
        reply_markup=kb.as_markup()
    )

    await call.answer()


# ==========================
# ВЫБОР РЕЖИМА
# ==========================

@dp.callback_query(F.data.startswith("mode_"))
async def choose_mode(call: CallbackQuery):
    user_id = call.from_user.id
    session = user_sessions.get(user_id)

    if not session:
        return

    mode = call.data.split("_")[1]
    session["mode"] = mode

    await call.answer()
    await send_next_question(call.message, user_id)

# ==========================
# ПОВТОР ОШИБОК
# ==========================

@dp.callback_query(F.data == "repeat_wrong")
async def repeat_wrong_questions(call: CallbackQuery):

    user_id = call.from_user.id
    session = user_sessions.get(user_id)

    if not session or not session["wrong_questions"]:
        await call.answer("Нет ошибок для повторения")
        return

    session["mode"] = "wrong"
    session["wrong_index"] = 0
    session["total"] = 0
    session["correct"] = 0
    session["finished"] = False

    await call.answer()
    await send_next_wrong_question(call.message, user_id)
# ==========================
# СЛЕДУЮЩИЙ ВОПРОС
# ==========================

async def send_next_question(message: Message, user_id: int):
    session = user_sessions.get(user_id)
    if not session or session["finished"]:
        return

    # режим случайных вопросов
    if session["mode"] == "random":
        if session["total"] >= 20:
            await finish_test(message, user_id)
            return

        q = get_random_question(user_id, session["used_ids"])
        if not q:
            await finish_test(message, user_id)
            return

        qid, text, rationale, opts = q
        session["used_ids"].append(qid)

    # 👇 ВСТАВИТЬ ЭТОТ БЛОК
    elif session["mode"] == "favorites":

        con = sqlite3.connect("favorites.db")
        cur = con.cursor()

        cur.execute(
            "SELECT question_id, group_name FROM favorites WHERE user_id=?",
            (user_id,)
        )

        rows = cur.fetchall()
        con.close()

        if not rows:
            await message.answer("⭐ У вас нет избранных вопросов")
            await finish_test(message, user_id)
            return

        qid, group = random.choice(rows)

        db = sqlite3.connect(f"{group}.db")
        cur = db.cursor()

        cur.execute(
            "SELECT id, text, rationale FROM questions WHERE id=?",
            (qid,)
        )

        q = cur.fetchone()

        cur.execute("""
            SELECT id, pos, text, is_correct
            FROM options
            WHERE question_id=?
            ORDER BY pos
        """, (qid,))

        opts = cur.fetchall()
        db.close()

        text = q[1]
        rationale = q[2]

    # режим по порядку
    else:
        q = get_ordered_question(user_id, session["current_index"])
        if not q:
            await finish_test(message, user_id)
            return

        qid, text, rationale, opts = q
        session["current_index"] += 1

session["last_question_id"] = qid

question_text = format_question(qid, text, opts)

if session["mode"] == "random":
    progress = f"📊 Вопрос {session['total'] + 1} / 20\n\n"
    question_text = progress + question_text

await message.answer(
    question_text,
    reply_markup=build_keyboard(qid, opts)
)

# ==========================
# ВОПРОСЫ С ОШИБКАМИ
# ==========================

async def send_next_wrong_question(message: Message, user_id: int):

    session = user_sessions.get(user_id)

    if not session:
        return

    wrong = session["wrong_questions"]
    index = session.get("wrong_index", 0)

    if index >= len(wrong):
        await finish_test(message, user_id)
        return

    qid = wrong[index]
    session["wrong_index"] += 1

    con = db(user_id)
    cur = con.cursor()

    cur.execute(
        "SELECT id, text, rationale FROM questions WHERE id=?",
        (qid,)
    )

    q = cur.fetchone()

    cur.execute(
        "SELECT id, pos, text, is_correct FROM options WHERE question_id=? ORDER BY pos",
        (qid,)
    )

    opts = cur.fetchall()
    con.close()

    session["last_question_id"] = qid

    await message.answer(
        format_question(qid, q[1], opts),
        reply_markup=build_keyboard(qid, opts)
    )

# ==========================
# ОТВЕТ
# ==========================

@dp.callback_query(F.data.startswith("ans:"))
async def on_answer(call: CallbackQuery):

    user_id = call.from_user.id
    session = user_sessions.get(user_id)

    if not session or session["finished"]:
        return

    _, qid_s, pos_s = call.data.split(":")
    qid = int(qid_s)
    pos = int(pos_s)

    if session["last_question_id"] != qid:
        await call.answer("Ответ уже засчитан")
        return

    con = db(user_id)
    cur = con.cursor()

    cur.execute(
        "SELECT is_correct FROM options WHERE question_id=? AND pos=?",
        (qid, pos)
    )
    row = cur.fetchone()

    cur.execute(
        "SELECT rationale FROM questions WHERE id=?",
        (qid,)
    )
    rationale_row = cur.fetchone()

    con.close()

    session["total"] += 1
    session["last_question_id"] = None

    if row and row[0] == 1:
        session["correct"] += 1
        result = "✅ Правильно!"
    else:
        result = "❌ Неверно"
        session["wrong_questions"].append(qid)

    if rationale_row and rationale_row[0]:
        result += f"\n\n📌 Основание:\n{rationale_row[0].strip()}"

    await call.message.answer(result)

    if session["mode"] == "wrong":
        await send_next_wrong_question(call.message, user_id)
    else:
        await send_next_question(call.message, user_id)
    
@dp.callback_query(F.data.startswith("fav:"))
async def add_favorite(call: CallbackQuery):
    user_id = call.from_user.id
    qid = int(call.data.split(":")[1])
    group = current_group.get(user_id, "group3")

    con = sqlite3.connect("favorites.db")
    cur = con.cursor()

    cur.execute(
    "SELECT 1 FROM favorites WHERE user_id=? AND question_id=?",
    (user_id, qid)
    )

    exists = cur.fetchone()

    if not exists:
        cur.execute(
        "INSERT INTO favorites (user_id, question_id, group_name) VALUES (?, ?, ?)",
        (user_id, qid, group)
    )

    con.commit()
    con.close()

    await call.answer("⭐ Вопрос добавлен в избранное")
# ==========================
# ЗАВЕРШЕНИЕ
# ==========================

@dp.callback_query(F.data == "finish_test")
async def manual_finish(call: CallbackQuery):
    await finish_test(call.message, call.from_user.id)
    await call.answer()


async def finish_test(message: Message, user_id: int):
    session = user_sessions.get(user_id)
    if not session:
        return

    session["finished"] = True

    total = session["total"]
    correct = session["correct"]
    percent = round((correct / total) * 100) if total else 0

    con = sqlite3.connect("results.db")
    cur = con.cursor()

    cur.execute("""
        INSERT INTO results (user_id, total, correct, mode, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        user_id,
        total,
        correct,
        session["mode"],
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    con.commit()
    con.close()

    text = (
        f"🏁 Тест завершён\n\n"
        f"Всего вопросов: {total}\n"
        f"Правильных: {correct}\n"
        f"Ошибок: {total - correct}\n\n"
        f"📊 Результат: {percent}%"
    )

    kb = InlineKeyboardBuilder()

    if session["wrong_questions"]:
        kb.button(text="🔁 Повторить ошибки", callback_data="repeat_wrong")

    kb.button(text="📚 Новый тест", callback_data="restart_test")
    kb.adjust(1)

    await message.answer(text, reply_markup=kb.as_markup())

# ==========================
# НОВЫЙ ТЕСТ
# ==========================

@dp.callback_query(F.data == "restart_test")
async def restart_test(call: CallbackQuery):

    user_id = call.from_user.id

    if user_id in user_sessions:
        del user_sessions[user_id]

    if user_id in current_group:
        del current_group[user_id]

    kb = InlineKeyboardBuilder()
    kb.button(text="Группа II", callback_data="group_2")
    kb.button(text="Группа III", callback_data="group_3")
    kb.button(text="Группа IV", callback_data="group_4")
    kb.adjust(1)

    await call.message.answer(
        "Выберите группу по электробезопасности:",
        reply_markup=kb.as_markup()
    )

    await call.answer()
# ==========================
# MAIN
# ==========================

async def main():
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    keep_alive()
    asyncio.run(main())






