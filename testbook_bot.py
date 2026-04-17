#!/usr/bin/env python3
"""
📚 TestBook Pro Bot - Complete Telegram Exam Preparation Bot
Author: Generated for Pydroid3
Requirements: pip install pyTelegramBotAPI pdfplumber pypdf2 python-dotenv
"""

import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
import sqlite3
import json
import re
import time
import threading
import os
import pdfplumber
import io
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN = "8780139812:AAGaUTndxedBe-N9eXb9Q7_pvq0sn96YoxQ"
ADMIN_ID   = 5479881365
DB_PATH    = "testbook.db"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ─────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        icon TEXT DEFAULT '📘',
        support_group TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        icon TEXT DEFAULT '📂',
        FOREIGN KEY(exam_id) REFERENCES exams(id)
    );

    CREATE TABLE IF NOT EXISTS quiz_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        section_id INTEGER,
        positive_marks REAL DEFAULT 1.0,
        negative_marks REAL DEFAULT 0.25,
        time_per_question INTEGER DEFAULT 60,
        total_questions INTEGER DEFAULT 20,
        FOREIGN KEY(exam_id) REFERENCES exams(id)
    );

    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        section_id INTEGER,
        question TEXT NOT NULL,
        option_a TEXT NOT NULL,
        option_b TEXT NOT NULL,
        option_c TEXT NOT NULL,
        option_d TEXT NOT NULL,
        correct TEXT NOT NULL,
        explanation TEXT,
        source TEXT DEFAULT 'manual',
        FOREIGN KEY(exam_id) REFERENCES exams(id)
    );

    CREATE TABLE IF NOT EXISTS practice_sets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        section_id INTEGER,
        name TEXT NOT NULL,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(exam_id) REFERENCES exams(id)
    );

    CREATE TABLE IF NOT EXISTS practice_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        practice_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        option_a TEXT NOT NULL,
        option_b TEXT NOT NULL,
        option_c TEXT NOT NULL,
        option_d TEXT NOT NULL,
        correct TEXT NOT NULL,
        explanation TEXT,
        FOREIGN KEY(practice_id) REFERENCES practice_sets(id)
    );

    CREATE TABLE IF NOT EXISTS resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        section_id INTEGER,
        title TEXT NOT NULL,
        file_id TEXT,
        file_type TEXT,
        url TEXT,
        FOREIGN KEY(exam_id) REFERENCES exams(id)
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        joined_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS quiz_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        exam_id INTEGER,
        section_id INTEGER,
        practice_id INTEGER,
        session_type TEXT DEFAULT 'quiz',
        question_ids TEXT,
        current_index INTEGER DEFAULT 0,
        answers TEXT DEFAULT '{}',
        score REAL DEFAULT 0,
        start_time TEXT,
        end_time TEXT,
        status TEXT DEFAULT 'active',
        positive_marks REAL DEFAULT 1.0,
        negative_marks REAL DEFAULT 0.25,
        time_per_question INTEGER DEFAULT 60
    );

    CREATE TABLE IF NOT EXISTS user_question_history (
        user_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        session_type TEXT DEFAULT 'quiz',
        asked_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(user_id, question_id, session_type)
    );

    CREATE TABLE IF NOT EXISTS admin_states (
        user_id INTEGER PRIMARY KEY,
        state TEXT,
        data TEXT DEFAULT '{}'
    );
    """)

    conn.commit()
    conn.close()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def is_admin(uid):
    return uid == ADMIN_ID

def register_user(user):
    with db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO users(id, username, full_name)
            VALUES(?,?,?)
        """, (user.id, user.username, user.full_name))

def get_admin_state(uid):
    with db() as conn:
        row = conn.execute("SELECT state, data FROM admin_states WHERE user_id=?", (uid,)).fetchone()
        if row:
            return row["state"], json.loads(row["data"])
        return None, {}

def set_admin_state(uid, state, data=None):
    if data is None:
        data = {}
    with db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO admin_states(user_id, state, data)
            VALUES(?,?,?)
        """, (uid, state, json.dumps(data)))

def clear_admin_state(uid):
    with db() as conn:
        conn.execute("DELETE FROM admin_states WHERE user_id=?", (uid,))

# ─────────────────────────────────────────────
#  PDF MCQ EXTRACTOR
# ─────────────────────────────────────────────
def extract_mcqs_from_pdf(file_bytes):
    """Smart MCQ extractor - handles multiple PDF formats"""
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception as e:
        return [], f"PDF read error: {e}"

    if not text.strip():
        return [], "❌ No readable text found in PDF. It may be scanned/image-based."

    questions = []
    # Split by question patterns: Q1., 1., Q.1, 1)
    blocks = re.split(r'\n(?=(?:Q\.?\s*\d+|(?:Question\s*)?\d+[\.\)])\s)', text, flags=re.IGNORECASE)

    for block in blocks:
        block = block.strip()
        if len(block) < 20:
            continue

        q = parse_mcq_block(block)
        if q:
            questions.append(q)

    if not questions:
        # Fallback: try line-by-line pattern
        questions = parse_mcq_linewise(text)

    return questions, None

def parse_mcq_block(block):
    """Parse a single MCQ block"""
    lines = [l.strip() for l in block.split('\n') if l.strip()]
    if not lines:
        return None

    # Extract question text (remove leading number)
    q_text = re.sub(r'^(?:Q\.?\s*)?\d+[\.\)]\s*', '', lines[0], flags=re.IGNORECASE).strip()
    if len(q_text) < 5:
        if len(lines) > 1:
            q_text += " " + lines[1]

    opts = {}
    answer = None
    exp = ""

    for line in lines[1:]:
        # Options: (A), A., A), a.
        m = re.match(r'^[\(\[]?([ABCDabcd])[\)\]\.]\s*(.+)', line)
        if m:
            key = m.group(1).upper()
            opts[key] = m.group(2).strip()
        # Answer line
        elif re.match(r'^(?:Ans(?:wer)?|Correct)[\s:\.]', line, re.IGNORECASE):
            ans_m = re.search(r'([ABCDabcd])', line)
            if ans_m:
                answer = ans_m.group(1).upper()
        elif re.match(r'^Expl(?:anation)?', line, re.IGNORECASE):
            exp = re.sub(r'^Expl(?:anation)?[:\s]*', '', line, flags=re.IGNORECASE)

    if len(opts) >= 4 and 'A' in opts and 'B' in opts and 'C' in opts and 'D' in opts:
        if not answer:
            answer = 'A'  # default if not found
        return {
            "question": q_text,
            "option_a": opts.get('A', ''),
            "option_b": opts.get('B', ''),
            "option_c": opts.get('C', ''),
            "option_d": opts.get('D', ''),
            "correct": answer,
            "explanation": exp
        }
    return None

def parse_mcq_linewise(text):
    """Fallback line-wise MCQ parser"""
    questions = []
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    i = 0
    while i < len(lines):
        # Look for question line
        q_match = re.match(r'^(?:Q\.?\s*)?\d+[\.\)]\s+(.+)', lines[i], re.IGNORECASE)
        if q_match:
            q_text = q_match.group(1)
            opts = {}
            j = i + 1
            while j < len(lines) and len(opts) < 4:
                opt = re.match(r'^[\(\[]?([ABCDabcd])[\)\]\.]\s+(.+)', lines[j])
                if opt:
                    opts[opt.group(1).upper()] = opt.group(2)
                j += 1

            answer = 'A'
            if j < len(lines):
                ans = re.search(r'(?:Ans|Answer|Correct)[:\s]+([ABCDabcd])', lines[j], re.IGNORECASE)
                if ans:
                    answer = ans.group(1).upper()
                    j += 1

            if len(opts) == 4:
                questions.append({
                    "question": q_text,
                    "option_a": opts.get('A',''),
                    "option_b": opts.get('B',''),
                    "option_c": opts.get('C',''),
                    "option_d": opts.get('D',''),
                    "correct": answer,
                    "explanation": ""
                })
            i = j
        else:
            i += 1
    return questions

# ─────────────────────────────────────────────
#  KEYBOARDS
# ─────────────────────────────────────────────
def main_menu_kb(uid):
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(KeyboardButton("📚 Exams"), KeyboardButton("🏆 Leaderboard"))
    kb.row(KeyboardButton("📊 My Progress"), KeyboardButton("ℹ️ Help"))
    if is_admin(uid):
        kb.row(KeyboardButton("⚙️ Admin Panel"))
    return kb

def back_btn(cb):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("◀️ Back", callback_data=cb))
    return kb

def exam_menu_kb(exam_id):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📝 Take Test", callback_data=f"exam_test_{exam_id}"),
        InlineKeyboardButton("📖 Practice", callback_data=f"exam_practice_{exam_id}"),
        InlineKeyboardButton("📂 Resources", callback_data=f"exam_resources_{exam_id}"),
        InlineKeyboardButton("💬 Help Group", callback_data=f"exam_group_{exam_id}"),
        InlineKeyboardButton("◀️ Back", callback_data="back_exams")
    )
    return kb

def admin_main_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ Add Exam", callback_data="admin_add_exam"),
        InlineKeyboardButton("📋 Manage Exams", callback_data="admin_manage_exams"),
        InlineKeyboardButton("➕ Add Section", callback_data="admin_add_section"),
        InlineKeyboardButton("📤 Upload Quiz PDF", callback_data="admin_upload_quiz_pdf"),
        InlineKeyboardButton("📤 Upload Practice PDF", callback_data="admin_upload_practice_pdf"),
        InlineKeyboardButton("⚙️ Quiz Settings", callback_data="admin_quiz_settings"),
        InlineKeyboardButton("📎 Add Resource", callback_data="admin_add_resource"),
        InlineKeyboardButton("💬 Set Support Group", callback_data="admin_set_group"),
        InlineKeyboardButton("👥 Users Stats", callback_data="admin_stats"),
        InlineKeyboardButton("🔧 Manage Questions", callback_data="admin_manage_questions")
    )
    return kb

# ─────────────────────────────────────────────
#  USER FLOW — EXAMS LIST
# ─────────────────────────────────────────────
def show_exams(chat_id, msg_id=None):
    with db() as conn:
        exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()

    if not exams:
        text = "📭 <b>No exams available yet!</b>\nCheck back later. 🙏"
        bot.send_message(chat_id, text, reply_markup=back_btn("home"))
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for e in exams:
        kb.add(InlineKeyboardButton(
            f"{e['icon']} {e['name']}",
            callback_data=f"exam_open_{e['id']}"
        ))

    text = "📚 <b>Available Exams</b>\n\nChoose your exam to get started! 🎯"
    if msg_id:
        try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        except: bot.send_message(chat_id, text, reply_markup=kb)
    else:
        bot.send_message(chat_id, text, reply_markup=kb)

def show_exam_detail(chat_id, exam_id, msg_id=None):
    with db() as conn:
        e = conn.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
        sections = conn.execute("SELECT * FROM sections WHERE exam_id=?", (exam_id,)).fetchall()
        q_count = conn.execute("SELECT COUNT(*) as c FROM questions WHERE exam_id=?", (exam_id,)).fetchone()["c"]
        p_count = conn.execute("SELECT COUNT(*) as c FROM practice_sets WHERE exam_id=?", (exam_id,)).fetchone()["c"]

    if not e:
        bot.send_message(chat_id, "❌ Exam not found!")
        return

    text = (
        f"{e['icon']} <b>{e['name']}</b>\n\n"
        f"📄 {e['description'] or 'Exam preparation course'}\n\n"
        f"📂 Sections: <b>{len(sections)}</b>\n"
        f"❓ Questions: <b>{q_count}</b>\n"
        f"📝 Practice Sets: <b>{p_count}</b>\n\n"
        f"Choose an option below 👇"
    )
    kb = exam_menu_kb(exam_id)
    if msg_id:
        try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        except: bot.send_message(chat_id, text, reply_markup=kb)
    else:
        bot.send_message(chat_id, text, reply_markup=kb)

# ─────────────────────────────────────────────
#  TEST / QUIZ FLOW
# ─────────────────────────────────────────────
def show_test_sections(chat_id, exam_id, msg_id=None):
    with db() as conn:
        sections = conn.execute("SELECT * FROM sections WHERE exam_id=?", (exam_id,)).fetchall()
        qs = conn.execute("SELECT * FROM quiz_settings WHERE exam_id=? AND section_id IS NULL LIMIT 1", (exam_id,)).fetchone()

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("🎯 Full Exam Test", callback_data=f"start_quiz_{exam_id}_0"))
    for s in sections:
        kb.add(InlineKeyboardButton(
            f"{s['icon']} {s['name']}",
            callback_data=f"start_quiz_{exam_id}_{s['id']}"
        ))
    kb.add(InlineKeyboardButton("◀️ Back", callback_data=f"exam_open_{exam_id}"))

    marks = f"✅ +{qs['positive_marks']} | ❌ -{qs['negative_marks']}" if qs else "✅ +1 | ❌ -0.25"
    time_q = f"⏱ {qs['time_per_question']}s/question" if qs else "⏱ 60s/question"

    text = (
        f"📝 <b>Select Test Section</b>\n\n"
        f"{marks}\n{time_q}\n\n"
        f"Choose a section or take the Full Exam:"
    )
    if msg_id:
        try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        except: bot.send_message(chat_id, text, reply_markup=kb)
    else:
        bot.send_message(chat_id, text, reply_markup=kb)

def start_quiz(chat_id, user_id, exam_id, section_id):
    with db() as conn:
        # Get settings
        if section_id:
            qs = conn.execute("SELECT * FROM quiz_settings WHERE exam_id=? AND section_id=? LIMIT 1",
                              (exam_id, section_id)).fetchone()
        if not section_id or not qs:
            qs = conn.execute("SELECT * FROM quiz_settings WHERE exam_id=? AND section_id IS NULL LIMIT 1",
                              (exam_id,)).fetchone()

        pos = qs["positive_marks"] if qs else 1.0
        neg = qs["negative_marks"] if qs else 0.25
        tpq = qs["time_per_question"] if qs else 60
        total = qs["total_questions"] if qs else 20

        # Get questions not asked before
        seen = conn.execute(
            "SELECT question_id FROM user_question_history WHERE user_id=? AND session_type='quiz'",
            (user_id,)
        ).fetchall()
        seen_ids = [r["question_id"] for r in seen]

        if section_id:
            all_qs = conn.execute(
                "SELECT id FROM questions WHERE exam_id=? AND section_id=?",
                (exam_id, section_id)
            ).fetchall()
        else:
            all_qs = conn.execute(
                "SELECT id FROM questions WHERE exam_id=?", (exam_id,)
            ).fetchall()

        all_ids = [r["id"] for r in all_qs]
        fresh = [i for i in all_ids if i not in seen_ids]

        if len(fresh) < 5:
            # Reset history if too few fresh questions
            conn.execute(
                "DELETE FROM user_question_history WHERE user_id=? AND session_type='quiz'",
                (user_id,)
            )
            fresh = all_ids

        import random
        selected = random.sample(fresh, min(total, len(fresh)))

        if not selected:
            bot.send_message(chat_id,
                "❌ <b>No questions available yet!</b>\nAdmin needs to add questions for this section.",
                reply_markup=back_btn(f"exam_open_{exam_id}"))
            return

        # Create session
        conn.execute("""
            INSERT INTO quiz_sessions
            (user_id, exam_id, section_id, question_ids, start_time, positive_marks, negative_marks, time_per_question)
            VALUES(?,?,?,?,?,?,?,?)
        """, (user_id, exam_id, section_id, json.dumps(selected),
              datetime.now().isoformat(), pos, neg, tpq))
        session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    send_quiz_question(chat_id, session_id, 0)

def send_quiz_question(chat_id, session_id, idx):
    with db() as conn:
        sess = conn.execute("SELECT * FROM quiz_sessions WHERE id=?", (session_id,)).fetchone()
        if not sess or sess["status"] != "active":
            bot.send_message(chat_id, "❌ Session expired.")
            return

        q_ids = json.loads(sess["question_ids"])
        if idx >= len(q_ids):
            end_quiz(chat_id, session_id)
            return

        q = conn.execute("SELECT * FROM questions WHERE id=?", (q_ids[idx],)).fetchone()
        if not q:
            end_quiz(chat_id, session_id)
            return

    total = len(json.loads(sess["question_ids"]))
    progress = f"{'▓' * (idx+1)}{'░' * (total - idx - 1)}"[:20]
    tpq = sess["time_per_question"]

    text = (
        f"❓ <b>Question {idx+1}/{total}</b>\n"
        f"<code>{progress}</code>\n"
        f"⏱ <b>{tpq}s</b> per question\n\n"
        f"<b>{q['question']}</b>\n"
    )

    kb = InlineKeyboardMarkup(row_width=1)
    for opt, label in [('A', q['option_a']), ('B', q['option_b']),
                       ('C', q['option_c']), ('D', q['option_d'])]:
        kb.add(InlineKeyboardButton(
            f"({opt}) {label}",
            callback_data=f"ans_{session_id}_{idx}_{opt}"
        ))
    kb.add(InlineKeyboardButton("🏳️ Skip", callback_data=f"ans_{session_id}_{idx}_SKIP"))

    msg = bot.send_message(chat_id, text, reply_markup=kb)

    # Timer warning
    def timer_warn():
        time.sleep(tpq - 10)
        try:
            bot.send_message(chat_id, f"⚠️ <b>10 seconds left!</b> for Q{idx+1}")
        except: pass
        time.sleep(10)
        # Auto-skip if no answer
        with db() as conn:
            s = conn.execute("SELECT * FROM quiz_sessions WHERE id=?", (session_id,)).fetchone()
            if s and s["status"] == "active":
                answers = json.loads(s["answers"])
                key = str(q_ids[idx])
                if key not in answers:
                    answers[key] = "SKIP"
                    conn.execute("UPDATE quiz_sessions SET answers=? WHERE id=?",
                                 (json.dumps(answers), session_id))
                    try: bot.edit_message_reply_markup(chat_id, msg.message_id, reply_markup=None)
                    except: pass
                    send_quiz_question(chat_id, session_id, idx + 1)

    t = threading.Thread(target=timer_warn, daemon=True)
    t.start()

def handle_quiz_answer(chat_id, user_id, session_id, idx, answer):
    with db() as conn:
        sess = conn.execute("SELECT * FROM quiz_sessions WHERE id=?", (session_id,)).fetchone()
        if not sess or sess["status"] != "active":
            return

        q_ids = json.loads(sess["question_ids"])
        answers = json.loads(sess["answers"])
        key = str(q_ids[idx])

        if key in answers:
            bot.answer_callback_query
            return  # Already answered

        q = conn.execute("SELECT * FROM questions WHERE id=?", (q_ids[idx],)).fetchone()
        answers[key] = answer

        # Mark question as seen
        conn.execute("""
            INSERT OR REPLACE INTO user_question_history(user_id, question_id, session_type)
            VALUES(?,?,'quiz')
        """, (user_id, q_ids[idx]))

        conn.execute("UPDATE quiz_sessions SET answers=? WHERE id=?",
                     (json.dumps(answers), session_id))

    correct = answer == q["correct"]
    if answer == "SKIP":
        result = "⏭ <b>Skipped!</b>"
    elif correct:
        result = f"✅ <b>Correct!</b> +{sess['positive_marks']} marks"
    else:
        result = f"❌ <b>Wrong!</b> -{sess['negative_marks']} marks\n✅ Correct: <b>({q['correct']}) {q['option_' + q['correct'].lower()]}</b>"

    if q["explanation"] and answer != "SKIP":
        result += f"\n\n💡 <i>{q['explanation']}</i>"

    bot.send_message(chat_id, result)
    time.sleep(1)
    send_quiz_question(chat_id, session_id, idx + 1)

def end_quiz(chat_id, session_id):
    with db() as conn:
        sess = conn.execute("SELECT * FROM quiz_sessions WHERE id=?", (session_id,)).fetchone()
        if not sess:
            return

        q_ids = json.loads(sess["question_ids"])
        answers = json.loads(sess["answers"])
        pos = sess["positive_marks"]
        neg = sess["negative_marks"]

        score = 0
        correct = wrong = skipped = 0
        for qid in q_ids:
            ans = answers.get(str(qid), "SKIP")
            q = conn.execute("SELECT correct FROM questions WHERE id=?", (qid,)).fetchone()
            if not q: continue
            if ans == "SKIP":
                skipped += 1
            elif ans == q["correct"]:
                score += pos
                correct += 1
            else:
                score -= neg
                wrong += 1

        score = max(0, score)
        total = len(q_ids)
        percentage = (correct / total * 100) if total else 0

        conn.execute("""
            UPDATE quiz_sessions SET score=?, end_time=?, status='completed'
            WHERE id=?
        """, (score, datetime.now().isoformat(), session_id))

    if percentage >= 80:
        badge = "🏆 Excellent!"
    elif percentage >= 60:
        badge = "👍 Good Job!"
    elif percentage >= 40:
        badge = "📖 Need More Practice"
    else:
        badge = "💪 Keep Trying!"

    bar = int(percentage / 10)
    progress_bar = "🟩" * bar + "🟥" * (10 - bar)

    text = (
        f"🎉 <b>Quiz Completed!</b>\n\n"
        f"{badge}\n\n"
        f"{progress_bar}\n"
        f"📊 <b>Score:</b> {score:.1f} / {total * pos:.1f}\n"
        f"📈 <b>Percentage:</b> {percentage:.1f}%\n\n"
        f"✅ Correct: <b>{correct}</b>\n"
        f"❌ Wrong: <b>{wrong}</b>\n"
        f"⏭ Skipped: <b>{skipped}</b>\n\n"
        f"Keep practicing to improve! 📚"
    )
    kb = InlineKeyboardMarkup(row_width=2)
    if sess["exam_id"]:
        kb.add(
            InlineKeyboardButton("🔁 Retry", callback_data=f"start_quiz_{sess['exam_id']}_{sess['section_id'] or 0}"),
            InlineKeyboardButton("🏠 Home", callback_data=f"exam_open_{sess['exam_id']}")
        )
    bot.send_message(chat_id, text, reply_markup=kb)

# ─────────────────────────────────────────────
#  PRACTICE SET FLOW
# ─────────────────────────────────────────────
def show_practice_sets(chat_id, exam_id, msg_id=None):
    with db() as conn:
        sets = conn.execute(
            "SELECT * FROM practice_sets WHERE exam_id=? ORDER BY id DESC", (exam_id,)
        ).fetchall()

    if not sets:
        text = "📭 <b>No practice sets yet!</b>"
        if msg_id:
            try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=back_btn(f"exam_open_{exam_id}"))
            except: bot.send_message(chat_id, text, reply_markup=back_btn(f"exam_open_{exam_id}"))
        else:
            bot.send_message(chat_id, text, reply_markup=back_btn(f"exam_open_{exam_id}"))
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for s in sets:
        cnt = 0
        with db() as conn2:
            r = conn2.execute("SELECT COUNT(*) as c FROM practice_questions WHERE practice_id=?", (s["id"],)).fetchone()
            cnt = r["c"]
        kb.add(InlineKeyboardButton(
            f"📝 {s['name']} ({cnt} Qs)",
            callback_data=f"practice_start_{exam_id}_{s['id']}"
        ))
    kb.add(InlineKeyboardButton("◀️ Back", callback_data=f"exam_open_{exam_id}"))

    text = "📖 <b>Practice Sets</b>\n\nChoose a practice set:"
    if msg_id:
        try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        except: bot.send_message(chat_id, text, reply_markup=kb)
    else:
        bot.send_message(chat_id, text, reply_markup=kb)

def start_practice(chat_id, user_id, exam_id, practice_id, page=0):
    PER_PAGE = 10
    with db() as conn:
        practice = conn.execute("SELECT * FROM practice_sets WHERE id=?", (practice_id,)).fetchone()
        # Get unseen questions
        seen = conn.execute(
            "SELECT question_id FROM user_question_history WHERE user_id=? AND session_type='practice'",
            (user_id,)
        ).fetchall()
        seen_ids = [r["question_id"] for r in seen]

        all_qs = conn.execute(
            "SELECT * FROM practice_questions WHERE practice_id=?", (practice_id,)
        ).fetchall()

        fresh = [q for q in all_qs if q["id"] not in seen_ids]
        if not fresh:
            # Reset practice history
            conn.execute(
                "DELETE FROM user_question_history WHERE user_id=? AND session_type='practice'",
                (user_id,)
            )
            fresh = list(all_qs)

    if not fresh:
        bot.send_message(chat_id, "❌ No questions in this practice set!")
        return

    batch = fresh[page * PER_PAGE:(page + 1) * PER_PAGE]
    total_pages = (len(fresh) + PER_PAGE - 1) // PER_PAGE

    for q in batch:
        text = (
            f"📌 <b>Practice Question</b>\n\n"
            f"<b>{q['question']}</b>\n\n"
            f"🅐 {q['option_a']}\n"
            f"🅑 {q['option_b']}\n"
            f"🅒 {q['option_c']}\n"
            f"🅓 {q['option_d']}\n"
        )
        kb = InlineKeyboardMarkup(row_width=4)
        kb.add(
            InlineKeyboardButton("A", callback_data=f"pans_{practice_id}_{q['id']}_A_{page}"),
            InlineKeyboardButton("B", callback_data=f"pans_{practice_id}_{q['id']}_B_{page}"),
            InlineKeyboardButton("C", callback_data=f"pans_{practice_id}_{q['id']}_C_{page}"),
            InlineKeyboardButton("D", callback_data=f"pans_{practice_id}_{q['id']}_D_{page}"),
        )
        bot.send_message(chat_id, text, reply_markup=kb)
        # Mark as seen
        with db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO user_question_history(user_id, question_id, session_type)
                VALUES(?,?,'practice')
            """, (user_id, q["id"]))

    kb2 = InlineKeyboardMarkup(row_width=2)
    if page + 1 < total_pages:
        kb2.add(InlineKeyboardButton(
            f"▶️ Next 10 Questions ({page+2}/{total_pages})",
            callback_data=f"practice_next_{exam_id}_{practice_id}_{page+1}"
        ))
    kb2.add(InlineKeyboardButton("◀️ Back to Practice Sets", callback_data=f"exam_practice_{exam_id}"))

    remaining = len(fresh) - (page + 1) * PER_PAGE
    msg = f"📊 <b>Showing {len(batch)} questions</b>"
    if remaining > 0:
        msg += f"\n🔢 {remaining} more questions available"
    else:
        msg += "\n✅ All questions covered! Great job!"

    bot.send_message(chat_id, msg, reply_markup=kb2)

def handle_practice_answer(chat_id, practice_id, q_id, answer, page):
    with db() as conn:
        q = conn.execute("SELECT * FROM practice_questions WHERE id=?", (q_id,)).fetchone()
    if not q:
        return
    correct = answer == q["correct"]
    result = (
        f"{'✅' if correct else '❌'} <b>{'Correct!' if correct else 'Wrong!'}</b>\n"
        f"✅ Answer: <b>({q['correct']}) {q['option_' + q['correct'].lower()]}</b>"
    )
    if q["explanation"]:
        result += f"\n💡 <i>{q['explanation']}</i>"
    bot.send_message(chat_id, result)

# ─────────────────────────────────────────────
#  RESOURCES
# ─────────────────────────────────────────────
def show_resources(chat_id, exam_id, msg_id=None):
    with db() as conn:
        resources = conn.execute(
            "SELECT * FROM resources WHERE exam_id=? ORDER BY id DESC", (exam_id,)
        ).fetchall()

    if not resources:
        text = "📭 <b>No resources available yet!</b>"
        if msg_id:
            try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=back_btn(f"exam_open_{exam_id}"))
            except: bot.send_message(chat_id, text, reply_markup=back_btn(f"exam_open_{exam_id}"))
        else:
            bot.send_message(chat_id, text, reply_markup=back_btn(f"exam_open_{exam_id}"))
        return

    text = f"📂 <b>Resources</b>\n\nHere are the study materials:\n\n"
    for i, r in enumerate(resources, 1):
        icon = "📄" if r["file_type"] == "pdf" else "🖼" if r["file_type"] == "photo" else "🔗"
        text += f"{icon} {i}. {r['title']}\n"

    kb = InlineKeyboardMarkup(row_width=1)
    for r in resources:
        icon = "📄" if r["file_type"] == "pdf" else "🖼" if r["file_type"] == "photo" else "🔗"
        kb.add(InlineKeyboardButton(
            f"{icon} {r['title']}",
            callback_data=f"res_get_{r['id']}"
        ))
    kb.add(InlineKeyboardButton("◀️ Back", callback_data=f"exam_open_{exam_id}"))

    if msg_id:
        try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        except: bot.send_message(chat_id, text, reply_markup=kb)
    else:
        bot.send_message(chat_id, text, reply_markup=kb)

# ─────────────────────────────────────────────
#  ADMIN FLOW
# ─────────────────────────────────────────────
def show_admin_panel(chat_id, msg_id=None):
    with db() as conn:
        exams = conn.execute("SELECT COUNT(*) as c FROM exams").fetchone()["c"]
        questions = conn.execute("SELECT COUNT(*) as c FROM questions").fetchone()["c"]
        users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]

    text = (
        f"⚙️ <b>Admin Panel</b>\n\n"
        f"📚 Exams: <b>{exams}</b>\n"
        f"❓ Questions: <b>{questions}</b>\n"
        f"👥 Users: <b>{users}</b>\n\n"
        f"What would you like to do?"
    )
    if msg_id:
        try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=admin_main_kb())
        except: bot.send_message(chat_id, text, reply_markup=admin_main_kb())
    else:
        bot.send_message(chat_id, text, reply_markup=admin_main_kb())

# ─────────────────────────────────────────────
#  HANDLERS — COMMANDS
# ─────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    register_user(msg.from_user)
    name = msg.from_user.first_name or "Student"
    text = (
        f"🎓 <b>Welcome to TestBook Pro, {name}!</b>\n\n"
        f"📚 Your ultimate exam preparation companion on Telegram!\n\n"
        f"🔹 Take timed mock tests\n"
        f"🔹 Practice with previous year papers\n"
        f"🔹 Download study resources\n"
        f"🔹 Join subject-wise help groups\n"
        f"🔹 Track your progress\n\n"
        f"Tap <b>📚 Exams</b> to get started! 👇"
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu_kb(msg.from_user.id))

@bot.message_handler(commands=['admin'])
def cmd_admin(msg):
    if not is_admin(msg.from_user.id):
        bot.send_message(msg.chat.id, "❌ Access denied!")
        return
    show_admin_panel(msg.chat.id)

@bot.message_handler(commands=['help'])
def cmd_help(msg):
    text = (
        "ℹ️ <b>TestBook Pro — Help</b>\n\n"
        "📚 <b>Exams</b> — Browse all available exams\n"
        "📝 <b>Take Test</b> — Start a timed MCQ test\n"
        "📖 <b>Practice</b> — Practice with question sets\n"
        "📂 <b>Resources</b> — Download study material PDFs\n"
        "💬 <b>Help Group</b> — Join exam-specific groups\n"
        "📊 <b>My Progress</b> — View your test history\n"
        "🏆 <b>Leaderboard</b> — See top performers\n\n"
        "⭐ Questions never repeat in the same session!\n"
        "⭐ Negative marking applies to wrong answers"
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu_kb(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "📚 Exams")
def btn_exams(msg):
    register_user(msg.from_user)
    show_exams(msg.chat.id)

@bot.message_handler(func=lambda m: m.text == "⚙️ Admin Panel")
def btn_admin(msg):
    if not is_admin(msg.from_user.id):
        bot.send_message(msg.chat.id, "❌ Access denied!")
        return
    show_admin_panel(msg.chat.id)

@bot.message_handler(func=lambda m: m.text == "📊 My Progress")
def btn_progress(msg):
    uid = msg.from_user.id
    with db() as conn:
        sessions = conn.execute("""
            SELECT qs.*, e.name as exam_name, e.icon as exam_icon
            FROM quiz_sessions qs
            LEFT JOIN exams e ON qs.exam_id = e.id
            WHERE qs.user_id=? AND qs.status='completed'
            ORDER BY qs.id DESC LIMIT 10
        """, (uid,)).fetchall()

    if not sessions:
        bot.send_message(msg.chat.id, "📊 <b>No tests taken yet!</b>\nStart a test to see your progress. 🚀")
        return

    text = "📊 <b>Your Recent Tests</b>\n\n"
    for s in sessions:
        q_ids = json.loads(s["question_ids"])
        total = len(q_ids)
        pct = (s["score"] / (total * s["positive_marks"]) * 100) if total else 0
        text += (
            f"{s['exam_icon'] or '📘'} <b>{s['exam_name'] or 'Test'}</b>\n"
            f"   Score: {s['score']:.1f} | {pct:.0f}%\n\n"
        )

    bot.send_message(msg.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "🏆 Leaderboard")
def btn_leaderboard(msg):
    with db() as conn:
        rows = conn.execute("""
            SELECT u.full_name, u.username, SUM(qs.score) as total_score,
                   COUNT(qs.id) as tests_taken
            FROM quiz_sessions qs
            JOIN users u ON qs.user_id = u.id
            WHERE qs.status='completed'
            GROUP BY qs.user_id
            ORDER BY total_score DESC
            LIMIT 10
        """).fetchall()

    if not rows:
        bot.send_message(msg.chat.id, "🏆 <b>Leaderboard is empty!</b>\nBe the first to take a test! 🚀")
        return

    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    text = "🏆 <b>Top Performers</b>\n\n"
    for i, r in enumerate(rows):
        name = r["full_name"] or r["username"] or "Student"
        text += f"{medals[i]} <b>{name}</b> — {r['total_score']:.0f} pts ({r['tests_taken']} tests)\n"

    bot.send_message(msg.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "ℹ️ Help")
def btn_help(msg):
    cmd_help(msg)

# ─────────────────────────────────────────────
#  ADMIN TEXT INPUT HANDLER
# ─────────────────────────────────────────────
@bot.message_handler(content_types=['text', 'document', 'photo'])
def handle_text(msg):
    uid = msg.from_user.id
    if not is_admin(uid):
        return

    state, data = get_admin_state(uid)
    if not state:
        return

    # ── ADD EXAM ──
    if state == "add_exam_name":
        data["name"] = msg.text
        set_admin_state(uid, "add_exam_icon", data)
        bot.send_message(msg.chat.id, "📌 Enter exam icon (emoji, e.g. 📘) or type 'skip':")
    elif state == "add_exam_icon":
        data["icon"] = msg.text if msg.text != "skip" else "📘"
        set_admin_state(uid, "add_exam_desc", data)
        bot.send_message(msg.chat.id, "📝 Enter exam description or type 'skip':")
    elif state == "add_exam_desc":
        data["description"] = msg.text if msg.text != "skip" else ""
        with db() as conn:
            conn.execute("INSERT INTO exams(name, icon, description) VALUES(?,?,?)",
                         (data["name"], data["icon"], data["description"]))
        clear_admin_state(uid)
        bot.send_message(msg.chat.id,
            f"✅ Exam <b>{data['name']}</b> created!",
            reply_markup=admin_main_kb())

    # ── ADD SECTION ──
    elif state == "add_section_select_exam":
        bot.send_message(msg.chat.id, "Please use the button to select exam.")
    elif state == "add_section_name":
        data["sec_name"] = msg.text
        set_admin_state(uid, "add_section_icon", data)
        bot.send_message(msg.chat.id, "📌 Section icon (emoji) or 'skip':")
    elif state == "add_section_icon":
        data["sec_icon"] = msg.text if msg.text != "skip" else "📂"
        with db() as conn:
            conn.execute("INSERT INTO sections(exam_id, name, icon) VALUES(?,?,?)",
                         (data["exam_id"], data["sec_name"], data["sec_icon"]))
        clear_admin_state(uid)
        bot.send_message(msg.chat.id,
            f"✅ Section <b>{data['sec_name']}</b> added!",
            reply_markup=admin_main_kb())

    # ── QUIZ SETTINGS ──
    elif state == "qs_positive":
        try:
            data["positive"] = float(msg.text)
            set_admin_state(uid, "qs_negative", data)
            bot.send_message(msg.chat.id, "❌ Enter negative marks per wrong answer (e.g. 0.25):")
        except:
            bot.send_message(msg.chat.id, "⚠️ Enter a valid number:")
    elif state == "qs_negative":
        try:
            data["negative"] = float(msg.text)
            set_admin_state(uid, "qs_time", data)
            bot.send_message(msg.chat.id, "⏱ Time per question in seconds (e.g. 60):")
        except:
            bot.send_message(msg.chat.id, "⚠️ Enter a valid number:")
    elif state == "qs_time":
        try:
            data["time"] = int(msg.text)
            set_admin_state(uid, "qs_total", data)
            bot.send_message(msg.chat.id, "🔢 Total questions per test (e.g. 20):")
        except:
            bot.send_message(msg.chat.id, "⚠️ Enter a valid integer:")
    elif state == "qs_total":
        try:
            data["total"] = int(msg.text)
            with db() as conn:
                conn.execute("DELETE FROM quiz_settings WHERE exam_id=? AND section_id IS NULL",
                             (data["exam_id"],))
                conn.execute("""
                    INSERT INTO quiz_settings(exam_id, positive_marks, negative_marks, time_per_question, total_questions)
                    VALUES(?,?,?,?,?)
                """, (data["exam_id"], data["positive"], data["negative"], data["time"], data["total"]))
            clear_admin_state(uid)
            bot.send_message(msg.chat.id,
                f"✅ Settings saved!\n✅ +{data['positive']} | ❌ -{data['negative']} | ⏱ {data['time']}s | 🔢 {data['total']}q",
                reply_markup=admin_main_kb())
        except:
            bot.send_message(msg.chat.id, "⚠️ Enter a valid integer:")

    # ── SUPPORT GROUP ──
    elif state == "set_group":
        group_link = msg.text.strip()
        with db() as conn:
            conn.execute("UPDATE exams SET support_group=? WHERE id=?",
                         (group_link, data["exam_id"]))
        clear_admin_state(uid)
        bot.send_message(msg.chat.id, "✅ Support group link saved!", reply_markup=admin_main_kb())

    # ── RESOURCE TITLE ──
    elif state == "add_resource_title":
        data["res_title"] = msg.text
        set_admin_state(uid, "add_resource_file", data)
        bot.send_message(msg.chat.id, "📤 Send the file (PDF/photo) or a link (URL):")
    elif state == "add_resource_file":
        file_id = file_type = url = None
        if msg.document:
            file_id = msg.document.file_id
            file_type = "pdf"
        elif msg.photo:
            file_id = msg.photo[-1].file_id
            file_type = "photo"
        elif msg.text and msg.text.startswith("http"):
            url = msg.text
            file_type = "url"
        else:
            bot.send_message(msg.chat.id, "⚠️ Send a file or URL:")
            return
        with db() as conn:
            conn.execute("""
                INSERT INTO resources(exam_id, section_id, title, file_id, file_type, url)
                VALUES(?,?,?,?,?,?)
            """, (data["exam_id"], data.get("section_id"), data["res_title"], file_id, file_type, url))
        clear_admin_state(uid)
        bot.send_message(msg.chat.id, "✅ Resource added!", reply_markup=admin_main_kb())

    # ── PDF UPLOAD — QUIZ ──
    elif state == "upload_quiz_pdf":
        if not msg.document:
            bot.send_message(msg.chat.id, "⚠️ Please send a PDF file:")
            return
        process_pdf_upload(msg, data, "quiz")

    elif state == "upload_practice_pdf_name":
        data["practice_name"] = msg.text
        set_admin_state(uid, "upload_practice_pdf", data)
        bot.send_message(msg.chat.id, "📤 Now send the Practice Set PDF:")
    elif state == "upload_practice_pdf":
        if not msg.document:
            bot.send_message(msg.chat.id, "⚠️ Please send a PDF file:")
            return
        process_pdf_upload(msg, data, "practice")

def process_pdf_upload(msg, data, upload_type):
    uid = msg.from_user.id
    bot.send_message(msg.chat.id,
        "⏳ <b>Analyzing PDF...</b>\nExtracting questions, please wait... 🔍")
    try:
        file_info = bot.get_file(msg.document.file_id)
        file_bytes = bot.download_file(file_info.file_path)
        questions, error = extract_mcqs_from_pdf(file_bytes)

        if error:
            bot.send_message(msg.chat.id, f"❌ {error}", reply_markup=admin_main_kb())
            clear_admin_state(uid)
            return

        if not questions:
            bot.send_message(msg.chat.id,
                "❌ <b>No MCQs found!</b>\n\nMake sure the PDF has questions in format:\n"
                "1. Question text\n(A) Option A\n(B) Option B\n...\nAns: A",
                reply_markup=admin_main_kb())
            clear_admin_state(uid)
            return

        with db() as conn:
            if upload_type == "quiz":
                exam_id = data["exam_id"]
                section_id = data.get("section_id")
                for q in questions:
                    conn.execute("""
                        INSERT INTO questions(exam_id, section_id, question, option_a, option_b,
                            option_c, option_d, correct, explanation, source)
                        VALUES(?,?,?,?,?,?,?,?,?,'pdf')
                    """, (exam_id, section_id, q["question"], q["option_a"], q["option_b"],
                          q["option_c"], q["option_d"], q["correct"], q["explanation"]))
                bot.send_message(msg.chat.id,
                    f"✅ <b>PDF Processed!</b>\n\n"
                    f"📊 Extracted: <b>{len(questions)}</b> questions\n"
                    f"💾 Saved to: Exam Quiz Bank\n\n"
                    f"Questions are now available for tests! 🎉",
                    reply_markup=admin_main_kb())

            elif upload_type == "practice":
                exam_id = data["exam_id"]
                section_id = data.get("section_id")
                name = data.get("practice_name", "Practice Set")
                conn.execute("""
                    INSERT INTO practice_sets(exam_id, section_id, name)
                    VALUES(?,?,?)
                """, (exam_id, section_id, name))
                pset_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                for q in questions:
                    conn.execute("""
                        INSERT INTO practice_questions(practice_id, question, option_a, option_b,
                            option_c, option_d, correct, explanation)
                        VALUES(?,?,?,?,?,?,?,?)
                    """, (pset_id, q["question"], q["option_a"], q["option_b"],
                          q["option_c"], q["option_d"], q["correct"], q["explanation"]))
                bot.send_message(msg.chat.id,
                    f"✅ <b>Practice Set Created!</b>\n\n"
                    f"📝 Name: <b>{name}</b>\n"
                    f"📊 Questions: <b>{len(questions)}</b>\n\n"
                    f"Users can now practice! 🎉",
                    reply_markup=admin_main_kb())

        clear_admin_state(uid)
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ Error: {str(e)}", reply_markup=admin_main_kb())
        clear_admin_state(uid)

# ─────────────────────────────────────────────
#  CALLBACK HANDLER
# ─────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(c):
    uid = c.from_user.id
    chat = c.message.chat.id
    mid  = c.message.message_id
    d    = c.data
    bot.answer_callback_query(c.id)

    # Navigation
    if d == "back_exams" or d == "home":
        show_exams(chat, mid)

    elif d.startswith("exam_open_"):
        exam_id = int(d.split("_")[-1])
        show_exam_detail(chat, exam_id, mid)

    elif d.startswith("exam_test_"):
        exam_id = int(d.split("_")[-1])
        show_test_sections(chat, exam_id, mid)

    elif d.startswith("exam_practice_"):
        exam_id = int(d.split("_")[-1])
        show_practice_sets(chat, exam_id, mid)

    elif d.startswith("exam_resources_"):
        exam_id = int(d.split("_")[-1])
        show_resources(chat, exam_id, mid)

    elif d.startswith("exam_group_"):
        exam_id = int(d.split("_")[-1])
        with db() as conn:
            e = conn.execute("SELECT support_group, name FROM exams WHERE id=?", (exam_id,)).fetchone()
        if e and e["support_group"]:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton(f"💬 Join {e['name']} Group", url=e["support_group"]))
            kb.add(InlineKeyboardButton("◀️ Back", callback_data=f"exam_open_{exam_id}"))
            try:
                bot.edit_message_text(f"💬 <b>Join the Help Group</b>\n\nGet help, discuss doubts, share notes!",
                                      chat, mid, reply_markup=kb)
            except:
                bot.send_message(chat, f"💬 Join: {e['support_group']}", reply_markup=kb)
        else:
            bot.send_message(chat, "❌ No support group linked for this exam yet.")

    # Quiz
    elif d.startswith("start_quiz_"):
        parts = d.split("_")
        exam_id = int(parts[2])
        section_id = int(parts[3]) if parts[3] != "0" else None
        start_quiz(chat, uid, exam_id, section_id)

    elif d.startswith("ans_"):
        parts = d.split("_")
        sess_id = int(parts[1])
        idx     = int(parts[2])
        answer  = parts[3]
        try: bot.edit_message_reply_markup(chat, mid, reply_markup=None)
        except: pass
        handle_quiz_answer(chat, uid, sess_id, idx, answer)

    # Practice
    elif d.startswith("practice_start_"):
        parts = d.split("_")
        exam_id = int(parts[2])
        pset_id = int(parts[3])
        start_practice(chat, uid, exam_id, pset_id, 0)

    elif d.startswith("practice_next_"):
        parts = d.split("_")
        exam_id = int(parts[2])
        pset_id = int(parts[3])
        page    = int(parts[4])
        start_practice(chat, uid, exam_id, pset_id, page)

    elif d.startswith("pans_"):
        parts = d.split("_")
        pset_id = int(parts[1])
        q_id    = int(parts[2])
        answer  = parts[3]
        page    = int(parts[4])
        try: bot.edit_message_reply_markup(chat, mid, reply_markup=None)
        except: pass
        handle_practice_answer(chat, pset_id, q_id, answer, page)

    # Resources
    elif d.startswith("res_get_"):
        res_id = int(d.split("_")[-1])
        with db() as conn:
            r = conn.execute("SELECT * FROM resources WHERE id=?", (res_id,)).fetchone()
        if not r:
            bot.send_message(chat, "❌ Resource not found!")
            return
        if r["file_type"] == "pdf" and r["file_id"]:
            bot.send_document(chat, r["file_id"], caption=f"📄 {r['title']}")
        elif r["file_type"] == "photo" and r["file_id"]:
            bot.send_photo(chat, r["file_id"], caption=f"🖼 {r['title']}")
        elif r["url"]:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton("🔗 Open Link", url=r["url"]))
            bot.send_message(chat, f"🔗 <b>{r['title']}</b>", reply_markup=kb)

    # ── ADMIN CALLBACKS ──
    elif d == "admin_panel" and is_admin(uid):
        show_admin_panel(chat, mid)

    elif d == "admin_add_exam" and is_admin(uid):
        set_admin_state(uid, "add_exam_name", {})
        bot.send_message(chat, "📝 Enter the <b>Exam Name</b> (e.g. Indian Navy MED):")

    elif d == "admin_manage_exams" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        if not exams:
            bot.send_message(chat, "📭 No exams yet!", reply_markup=back_btn("admin_panel"))
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(
                f"{e['icon']} {e['name']}",
                callback_data=f"admin_exam_detail_{e['id']}"
            ))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        try:
            bot.edit_message_text("📋 <b>Manage Exams</b>\n\nSelect an exam:", chat, mid, reply_markup=kb)
        except:
            bot.send_message(chat, "📋 <b>Manage Exams</b>", reply_markup=kb)

    elif d.startswith("admin_exam_detail_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        with db() as conn:
            e = conn.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
            q_cnt = conn.execute("SELECT COUNT(*) as c FROM questions WHERE exam_id=?", (exam_id,)).fetchone()["c"]
            s_cnt = conn.execute("SELECT COUNT(*) as c FROM sections WHERE exam_id=?", (exam_id,)).fetchone()["c"]
            p_cnt = conn.execute("SELECT COUNT(*) as c FROM practice_sets WHERE exam_id=?", (exam_id,)).fetchone()["c"]
        text = (
            f"{e['icon']} <b>{e['name']}</b>\n\n"
            f"📂 Sections: {s_cnt}\n"
            f"❓ Questions: {q_cnt}\n"
            f"📝 Practice Sets: {p_cnt}\n"
        )
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📤 Upload Quiz PDF", callback_data=f"admin_upq_{exam_id}"),
            InlineKeyboardButton("📤 Upload Practice PDF", callback_data=f"admin_upp_{exam_id}"),
            InlineKeyboardButton("⚙️ Quiz Settings", callback_data=f"admin_qset_{exam_id}"),
            InlineKeyboardButton("💬 Set Group", callback_data=f"admin_sgroup_{exam_id}"),
            InlineKeyboardButton("📎 Add Resource", callback_data=f"admin_ares_{exam_id}"),
            InlineKeyboardButton("❌ Delete Exam", callback_data=f"admin_del_exam_{exam_id}"),
            InlineKeyboardButton("◀️ Back", callback_data="admin_manage_exams")
        )
        try: bot.edit_message_text(text, chat, mid, reply_markup=kb)
        except: bot.send_message(chat, text, reply_markup=kb)

    elif d.startswith("admin_del_exam_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"admin_confirm_del_{exam_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"admin_exam_detail_{exam_id}")
        )
        try: bot.edit_message_text("⚠️ <b>Delete this exam and ALL its data?</b>", chat, mid, reply_markup=kb)
        except: bot.send_message(chat, "⚠️ Confirm delete?", reply_markup=kb)

    elif d.startswith("admin_confirm_del_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        with db() as conn:
            conn.execute("DELETE FROM questions WHERE exam_id=?", (exam_id,))
            conn.execute("DELETE FROM sections WHERE exam_id=?", (exam_id,))
            conn.execute("DELETE FROM quiz_settings WHERE exam_id=?", (exam_id,))
            conn.execute("DELETE FROM resources WHERE exam_id=?", (exam_id,))
            psets = conn.execute("SELECT id FROM practice_sets WHERE exam_id=?", (exam_id,)).fetchall()
            for ps in psets:
                conn.execute("DELETE FROM practice_questions WHERE practice_id=?", (ps["id"],))
            conn.execute("DELETE FROM practice_sets WHERE exam_id=?", (exam_id,))
            conn.execute("DELETE FROM exams WHERE id=?", (exam_id,))
        try: bot.edit_message_text("✅ Exam deleted.", chat, mid, reply_markup=back_btn("admin_manage_exams"))
        except: bot.send_message(chat, "✅ Exam deleted.")

    elif d.startswith("admin_upq_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "upload_quiz_pdf", {"exam_id": exam_id})
        bot.send_message(chat, "📤 <b>Upload Quiz PDF</b>\n\nSend the PDF file with MCQ questions.\n\n<i>Format: Q1. Question\n(A) Option\n(B) Option\n...\nAns: A</i>")

    elif d.startswith("admin_upp_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "upload_practice_pdf_name", {"exam_id": exam_id})
        bot.send_message(chat, "📝 Enter a name for this Practice Set (e.g. 'Biology Practice 1'):")

    elif d.startswith("admin_qset_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "qs_positive", {"exam_id": exam_id})
        bot.send_message(chat, "✅ Enter <b>positive marks</b> per correct answer (e.g. 1 or 2):")

    elif d.startswith("admin_sgroup_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "set_group", {"exam_id": exam_id})
        bot.send_message(chat, "💬 Enter the Telegram group/channel link (e.g. https://t.me/...):")

    elif d.startswith("admin_ares_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "add_resource_title", {"exam_id": exam_id})
        bot.send_message(chat, "📎 Enter resource title (e.g. 'Biology Notes PDF'):")

    elif d == "admin_add_section" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        if not exams:
            bot.send_message(chat, "❌ Create an exam first!")
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}", callback_data=f"admin_sec_exam_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        try: bot.edit_message_text("📂 Select exam to add section:", chat, mid, reply_markup=kb)
        except: bot.send_message(chat, "📂 Select exam:", reply_markup=kb)

    elif d.startswith("admin_sec_exam_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "add_section_name", {"exam_id": exam_id})
        bot.send_message(chat, "📂 Enter <b>Section Name</b> (e.g. Biology, English, GS):")

    elif d == "admin_upload_quiz_pdf" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        if not exams:
            bot.send_message(chat, "❌ Create an exam first!")
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}", callback_data=f"admin_upq_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        try: bot.edit_message_text("📤 Select exam for Quiz PDF upload:", chat, mid, reply_markup=kb)
        except: bot.send_message(chat, "📤 Select exam:", reply_markup=kb)

    elif d == "admin_upload_practice_pdf" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        if not exams:
            bot.send_message(chat, "❌ Create an exam first!")
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}", callback_data=f"admin_upp_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        try: bot.edit_message_text("📤 Select exam for Practice PDF upload:", chat, mid, reply_markup=kb)
        except: bot.send_message(chat, "📤 Select exam:", reply_markup=kb)

    elif d == "admin_quiz_settings" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}", callback_data=f"admin_qset_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        try: bot.edit_message_text("⚙️ Select exam to configure:", chat, mid, reply_markup=kb)
        except: bot.send_message(chat, "⚙️ Select exam:", reply_markup=kb)

    elif d == "admin_set_group" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}", callback_data=f"admin_sgroup_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        try: bot.edit_message_text("💬 Select exam to set group:", chat, mid, reply_markup=kb)
        except: bot.send_message(chat, "💬 Select exam:", reply_markup=kb)

    elif d == "admin_add_resource" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}", callback_data=f"admin_ares_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        try: bot.edit_message_text("📎 Select exam for resource:", chat, mid, reply_markup=kb)
        except: bot.send_message(chat, "📎 Select exam:", reply_markup=kb)

    elif d == "admin_stats" and is_admin(uid):
        with db() as conn:
            users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
            total_tests = conn.execute("SELECT COUNT(*) as c FROM quiz_sessions WHERE status='completed'").fetchone()["c"]
            total_q = conn.execute("SELECT COUNT(*) as c FROM questions").fetchone()["c"]
            today = datetime.now().strftime("%Y-%m-%d")
            today_users = conn.execute(
                "SELECT COUNT(*) as c FROM users WHERE joined_at LIKE ?", (f"{today}%",)
            ).fetchone()["c"]
        text = (
            f"📊 <b>Bot Statistics</b>\n\n"
            f"👥 Total Users: <b>{users}</b>\n"
            f"🆕 New Today: <b>{today_users}</b>\n"
            f"📝 Total Tests: <b>{total_tests}</b>\n"
            f"❓ Total Questions: <b>{total_q}</b>\n"
        )
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        try: bot.edit_message_text(text, chat, mid, reply_markup=kb)
        except: bot.send_message(chat, text, reply_markup=kb)

    elif d == "admin_manage_questions" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            q_cnt = 0
            with db() as conn2:
                q_cnt = conn2.execute("SELECT COUNT(*) as c FROM questions WHERE exam_id=?", (e["id"],)).fetchone()["c"]
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']} ({q_cnt} Qs)", callback_data=f"admin_qlist_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        try: bot.edit_message_text("🔧 <b>Manage Questions</b>\nSelect exam:", chat, mid, reply_markup=kb)
        except: bot.send_message(chat, "🔧 Select exam:", reply_markup=kb)

    elif d.startswith("admin_qlist_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        with db() as conn:
            qs = conn.execute(
                "SELECT id, question FROM questions WHERE exam_id=? ORDER BY id DESC LIMIT 20", (exam_id,)
            ).fetchall()
        if not qs:
            bot.send_message(chat, "📭 No questions yet!", reply_markup=back_btn("admin_manage_questions"))
            return
        text = f"❓ <b>Questions (latest 20)</b>\n\n"
        kb = InlineKeyboardMarkup(row_width=1)
        for q in qs:
            q_short = q["question"][:40] + "..." if len(q["question"]) > 40 else q["question"]
            kb.add(InlineKeyboardButton(f"❌ Del: {q_short}", callback_data=f"admin_delq_{q['id']}_{exam_id}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_manage_questions"))
        try: bot.edit_message_text(f"❓ Tap to delete a question:", chat, mid, reply_markup=kb)
        except: bot.send_message(chat, "❓ Questions:", reply_markup=kb)

    elif d.startswith("admin_delq_") and is_admin(uid):
        parts = d.split("_")
        q_id = int(parts[2])
        exam_id = int(parts[3])
        with db() as conn:
            conn.execute("DELETE FROM questions WHERE id=?", (q_id,))
        bot.answer_callback_query(c.id, "✅ Question deleted!")
        # Refresh list
        with db() as conn:
            qs = conn.execute(
                "SELECT id, question FROM questions WHERE exam_id=? ORDER BY id DESC LIMIT 20", (exam_id,)
            ).fetchall()
        kb = InlineKeyboardMarkup(row_width=1)
        for q in qs:
            q_short = q["question"][:40] + "..." if len(q["question"]) > 40 else q["question"]
            kb.add(InlineKeyboardButton(f"❌ Del: {q_short}", callback_data=f"admin_delq_{q['id']}_{exam_id}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_manage_questions"))
        try: bot.edit_message_reply_markup(chat, mid, reply_markup=kb)
        except: pass

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Initializing TestBook Pro Bot...")
    init_db()
    print("✅ Database ready!")
    print("🤖 Bot is running... Press Ctrl+C to stop")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
