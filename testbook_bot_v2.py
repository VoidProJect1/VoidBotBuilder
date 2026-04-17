#!/usr/bin/env python3
"""
📚 TestBook Pro Bot v2 — Telegram Exam Preparation Bot
Improvements:
  • Near-perfect PDF MCQ extraction (multi-strategy, handles all layouts)
  • Questions sent as Telegram native Quiz polls (inline 4-option format)
  • Cleaner UI — unnecessary messages → Reply keyboard buttons
  • Better answer feedback & progress tracking
"""

import telebot
from telebot.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    Poll
)
import sqlite3
import json
import re
import time
import threading
import os
import io
import random
import unicodedata
from datetime import datetime

try:
    import pdfplumber
    PDFPLUMBER_OK = True
except ImportError:
    PDFPLUMBER_OK = False

try:
    import fitz  # PyMuPDF — better text extraction
    PYMUPDF_OK = True
except ImportError:
    PYMUPDF_OK = False

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN = "8780139812:AAGaUTndxedBe-N9eXb9Q7_pvq0sn96YoxQ"
ADMIN_ID  = 5479881365
DB_PATH   = "testbook.db"

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
        time_per_question INTEGER DEFAULT 60,
        poll_msg_ids TEXT DEFAULT '{}'
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
    CREATE TABLE IF NOT EXISTS poll_map (
        poll_id TEXT PRIMARY KEY,
        session_id INTEGER,
        q_index INTEGER,
        q_db_id INTEGER,
        chat_id INTEGER,
        user_id INTEGER,
        session_type TEXT DEFAULT 'quiz'
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
def is_admin(uid): return uid == ADMIN_ID

def register_user(user):
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO users(id,username,full_name) VALUES(?,?,?)",
            (user.id, user.username, user.full_name)
        )

def get_admin_state(uid):
    with db() as conn:
        row = conn.execute("SELECT state,data FROM admin_states WHERE user_id=?", (uid,)).fetchone()
        if row: return row["state"], json.loads(row["data"])
    return None, {}

def set_admin_state(uid, state, data=None):
    if data is None: data = {}
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO admin_states(user_id,state,data) VALUES(?,?,?)",
            (uid, state, json.dumps(data))
        )

def clear_admin_state(uid):
    with db() as conn:
        conn.execute("DELETE FROM admin_states WHERE user_id=?", (uid,))

# ─────────────────────────────────────────────
#  ██████╗ ██████╗ ███████╗    ███████╗██╗  ██╗████████╗██████╗  █████╗  ██████╗████████╗
#  PDF EXTRACTION — NEAR-PERFECT MULTI-STRATEGY ENGINE
# ─────────────────────────────────────────────

def _clean(s):
    """Normalize unicode, remove junk characters."""
    if not s: return ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)
    s = re.sub(r'[ \t]+', ' ', s)
    return s.strip()

def _extract_text_pdfplumber(file_bytes):
    """Extract text using pdfplumber with layout analysis."""
    if not PDFPLUMBER_OK: return ""
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                # Try layout-aware extraction first
                words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=False)
                if words:
                    # Reconstruct lines from word positions
                    lines = {}
                    for w in words:
                        y = round(w['top'] / 5) * 5  # group by ~5px rows
                        lines.setdefault(y, []).append(w)
                    for y in sorted(lines):
                        row = sorted(lines[y], key=lambda w: w['x0'])
                        text += ' '.join(w['text'] for w in row) + '\n'
                else:
                    t = page.extract_text()
                    if t: text += t + '\n'
                text += '\n'
    except Exception as e:
        print(f"pdfplumber error: {e}")
    return text

def _extract_text_pymupdf(file_bytes):
    """Extract text using PyMuPDF (fitz) — handles complex layouts."""
    if not PYMUPDF_OK: return ""
    text = ""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            # Use dict mode for better structure
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
            for b in blocks:
                if b.get("type") == 0:  # text block
                    for line in b.get("lines", []):
                        line_text = ""
                        for span in line.get("spans", []):
                            line_text += span.get("text", "")
                        text += line_text + "\n"
            text += "\n"
        doc.close()
    except Exception as e:
        print(f"PyMuPDF error: {e}")
    return text

def _extract_text_raw(file_bytes):
    """Raw pdfplumber text without layout (fallback)."""
    if not PDFPLUMBER_OK: return ""
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t: text += t + "\n\n"
    except: pass
    return text

def extract_all_text(file_bytes):
    """Try all extractors and pick the longest/best result."""
    candidates = []
    for fn in [_extract_text_pymupdf, _extract_text_pdfplumber, _extract_text_raw]:
        t = fn(file_bytes)
        if t.strip():
            candidates.append(t)
    if not candidates:
        return ""
    # Pick the one with most newlines (most structured)
    return max(candidates, key=lambda t: t.count('\n'))

# ── Option letter normalizer ────────────────────────────────────────────────
_OPT_RE = re.compile(
    r'^[\s\(\[]*([ABCDabcd1234①②③④])[)\]\.:\s]+(.+)',
    re.DOTALL
)
_OPT_NUM = {'1':'A','2':'B','3':'C','4':'D',
            '①':'A','②':'B','③':'C','④':'D'}

def _parse_option_line(line):
    m = _OPT_RE.match(line.strip())
    if not m: return None, None
    k = m.group(1).upper()
    k = _OPT_NUM.get(k, k)
    return k, _clean(m.group(2))

# ── Answer line detector ────────────────────────────────────────────────────
_ANS_RE = re.compile(
    r'(?:ans(?:wer)?|correct\s*(?:ans(?:wer)?)?|key|उत्तर)[:\.\s]*'
    r'[\(\[]?([ABCDabcd1234①②③④])[\)\]]?',
    re.IGNORECASE
)

def _find_answer(text):
    m = _ANS_RE.search(text)
    if m:
        k = m.group(1).upper()
        return _OPT_NUM.get(k, k)
    return None

# ── Question line detector ──────────────────────────────────────────────────
_Q_LINE_RE = re.compile(
    r'^[\s]*(?:Q\.?\s*)?(\d{1,3})[\.)\s]\s*(.{10,})',
    re.IGNORECASE
)

# ── Main Block Parser ───────────────────────────────────────────────────────
def parse_block_to_mcq(lines):
    """Given a list of lines belonging to one question, extract MCQ dict."""
    if not lines: return None

    # First line = question (strip number prefix)
    q_text = re.sub(r'^[\s]*(?:Q\.?\s*)?\d+[\.)\s]+', '', lines[0], flags=re.IGNORECASE)
    q_text = _clean(q_text)

    # Some PDFs split question across multiple lines before options start
    opts = {}
    answer = None
    explanation = ""
    q_extra = []

    i = 1
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        k, v = _parse_option_line(line)
        if k and k in 'ABCD':
            # Handle multi-line options
            opts[k] = v
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if not next_line: break
                nk, _ = _parse_option_line(next_line)
                if nk and nk in 'ABCD': break
                if _ANS_RE.search(next_line): break
                opts[k] += ' ' + _clean(next_line)
                i += 1
        elif _ANS_RE.search(line):
            answer = _find_answer(line)
            # explanation on same line?
            exp_m = re.search(r'(?:expl?(?:anation)?|solution|sol)[:\.\s]+(.+)', line, re.IGNORECASE)
            if exp_m: explanation = _clean(exp_m.group(1))
            i += 1
        elif re.match(r'^(?:expl?(?:anation)?|solution|sol)[:\.\s]', line, re.IGNORECASE):
            explanation = _clean(re.sub(r'^(?:expl?(?:anation)?|solution|sol)[:\.\s]*', '', line, flags=re.IGNORECASE))
            i += 1
        else:
            # Might be continuation of question text if no opts yet
            if len(opts) == 0:
                q_extra.append(_clean(line))
            i += 1

    if q_extra:
        q_text += ' ' + ' '.join(q_extra)

    # Validate: need all 4 options
    for k in 'ABCD':
        if k not in opts or not opts[k]:
            return None

    if not answer:
        answer = 'A'  # default — better than nothing

    return {
        "question": q_text[:1000],
        "option_a": opts['A'][:200],
        "option_b": opts['B'][:200],
        "option_c": opts['C'][:200],
        "option_d": opts['D'][:200],
        "correct": answer,
        "explanation": explanation[:500]
    }

def split_into_blocks(text):
    """
    Split full PDF text into per-question blocks using aggressive pattern matching.
    Handles: Q1., Q.1, 1., 1), Question 1:, etc.
    """
    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')

    # Pattern to detect a new question start
    q_start = re.compile(
        r'^[\s]*(?:Q\.?\s*)?(\d{1,3})[\.)\s]\s*(?!\s*[ABCDabcd]\s)',
        re.IGNORECASE
    )

    blocks = []
    current = []
    current_num = None

    for line in lines:
        stripped = line.strip()
        m = q_start.match(stripped)
        if m and len(stripped) > 10:
            num = int(m.group(1))
            # Must be sequential-ish to avoid false positives like "(1)" in option text
            if current_num is None or (num == current_num + 1) or (num > current_num and num <= current_num + 5):
                if current:
                    blocks.append(current)
                current = [stripped]
                current_num = num
                continue
        if current:
            current.append(stripped)

    if current:
        blocks.append(current)

    return blocks

def extract_mcqs_from_pdf(file_bytes):
    """
    Master function: extract all MCQs from PDF bytes.
    Returns (list_of_mcq_dicts, error_str_or_None)
    """
    # Step 1: Extract text
    text = extract_all_text(file_bytes)

    if not text.strip():
        return [], "❌ No readable text found in PDF. It may be scanned/image-based."

    # Step 2: Pre-clean the text
    # Remove page headers/footers (lines with only numbers or short strings)
    lines_cleaned = []
    for line in text.split('\n'):
        s = line.strip()
        # Skip page numbers, headers that are just numbers or very short
        if re.match(r'^\d{1,3}$', s): continue
        lines_cleaned.append(line)
    text = '\n'.join(lines_cleaned)

    # Step 3: Split into question blocks and parse
    blocks = split_into_blocks(text)
    questions = []

    for block_lines in blocks:
        # Filter empty lines within block
        block_lines = [l for l in block_lines if l.strip()]
        if len(block_lines) < 5: continue  # too short to be a real MCQ
        q = parse_block_to_mcq(block_lines)
        if q:
            questions.append(q)

    # Step 4: If block-split got few results, try line-wise aggressive parser
    if len(questions) < 3:
        questions2 = parse_linewise_aggressive(text)
        if len(questions2) > len(questions):
            questions = questions2

    # Step 5: Deduplicate by question text
    seen_q = set()
    unique = []
    for q in questions:
        key = q['question'][:80].lower()
        if key not in seen_q:
            seen_q.add(key)
            unique.append(q)

    return unique, None

def parse_linewise_aggressive(text):
    """
    Line-wise parser: more aggressive, handles poorly formatted PDFs.
    Scans line by line looking for question + option patterns.
    """
    questions = []
    lines = [_clean(l) for l in text.split('\n') if _clean(l)]
    i = 0

    while i < len(lines):
        # Detect question line
        q_m = re.match(r'^(?:Q\.?\s*)?(\d{1,3})[\.)\s]\s*(.{10,})', lines[i], re.IGNORECASE)
        if not q_m:
            i += 1
            continue

        q_text = _clean(q_m.group(2))
        j = i + 1
        opts = {}

        # Absorb continuation of question (lines before first option)
        while j < len(lines) and len(opts) < 1:
            k, v = _parse_option_line(lines[j])
            if k and k in 'ABCD':
                opts[k] = v
                j += 1
                break
            elif re.match(r'^(?:Q\.?\s*)?\d+[\.)\s]', lines[j]):
                break  # next question started — no options found
            else:
                q_text += ' ' + lines[j]
                j += 1

        # Collect remaining options
        while j < len(lines) and len(opts) < 4:
            k, v = _parse_option_line(lines[j])
            if k and k in 'ABCD':
                opts[k] = v
                j += 1
            elif re.match(r'^(?:Q\.?\s*)?\d+[\.)\s]', lines[j]) and len(lines[j]) > 10:
                break
            elif _ANS_RE.search(lines[j]):
                break
            else:
                # Could be multi-line option continuation
                if opts:
                    last_key = sorted(opts.keys())[-1]
                    opts[last_key] += ' ' + lines[j]
                j += 1

        # Look for answer line (within next 3 lines)
        answer = None
        exp = ""
        for k in range(j, min(j+4, len(lines))):
            a = _find_answer(lines[k])
            if a:
                answer = a
                # Check for explanation on same or next line
                exp_m = re.search(r'(?:expl?|sol)[:\s]+(.+)', lines[k], re.IGNORECASE)
                if exp_m: exp = _clean(exp_m.group(1))
                j = k + 1
                break

        if len(opts) >= 4 and all(k in opts for k in 'ABCD'):
            if not answer: answer = 'A'
            questions.append({
                "question": q_text[:1000],
                "option_a": opts['A'][:200],
                "option_b": opts['B'][:200],
                "option_c": opts['C'][:200],
                "option_d": opts['D'][:200],
                "correct": answer,
                "explanation": exp
            })
            i = j
        else:
            i += 1

    return questions

# ─────────────────────────────────────────────
#  KEYBOARDS
# ─────────────────────────────────────────────
def main_menu_kb(uid):
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
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
        InlineKeyboardButton("◀️ Back to Exams", callback_data="back_exams")
    )
    return kb

def admin_main_kb():
    """Admin panel — clean 2-column inline layout."""
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("➕ Add Exam", callback_data="admin_add_exam"),
        InlineKeyboardButton("📋 Manage Exams", callback_data="admin_manage_exams"),
        InlineKeyboardButton("➕ Add Section", callback_data="admin_add_section"),
        InlineKeyboardButton("📤 Upload Quiz PDF", callback_data="admin_upload_quiz_pdf"),
        InlineKeyboardButton("📤 Practice PDF", callback_data="admin_upload_practice_pdf"),
        InlineKeyboardButton("⚙️ Quiz Settings", callback_data="admin_quiz_settings"),
        InlineKeyboardButton("📎 Add Resource", callback_data="admin_add_resource"),
        InlineKeyboardButton("💬 Set Support Group", callback_data="admin_set_group"),
        InlineKeyboardButton("👥 User Stats", callback_data="admin_stats"),
        InlineKeyboardButton("🔧 Manage Qs", callback_data="admin_manage_questions"),
    )
    return kb

# ─────────────────────────────────────────────
#  QUIZ FLOW — TELEGRAM NATIVE QUIZ POLLS
# ─────────────────────────────────────────────
def send_quiz_poll(chat_id, session_id, idx):
    """Send question as Telegram native quiz poll (4 inline options)."""
    with db() as conn:
        sess = conn.execute("SELECT * FROM quiz_sessions WHERE id=?", (session_id,)).fetchone()
        if not sess or sess["status"] != "active":
            try: bot.send_message(chat_id, "❌ Session expired or already finished.")
            except: pass
            return

        q_ids = json.loads(sess["question_ids"])
        if idx >= len(q_ids):
            end_quiz(chat_id, session_id)
            return

        q = conn.execute("SELECT * FROM questions WHERE id=?", (q_ids[idx],)).fetchone()
        if not q:
            # skip broken question
            send_quiz_poll(chat_id, session_id, idx + 1)
            return

    total = len(q_ids)
    bar = '▓' * (idx + 1) + '░' * (total - idx - 1)
    bar = bar[:20]

    # Progress header message
    header = (
        f"❓ <b>Q {idx+1} / {total}</b>  <code>{bar}</code>\n"
        f"⏱ {sess['time_per_question']}s per question"
    )
    bot.send_message(chat_id, header)

    # Correct answer index (0-based) for Telegram quiz
    opt_map = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
    correct_idx = opt_map.get(q['correct'].upper(), 0)

    options = [q['option_a'], q['option_b'], q['option_c'], q['option_d']]
    # Telegram poll option max = 100 chars
    options = [o[:100] for o in options]
    question_text = q['question'][:300]

    explanation = q['explanation'] or ""
    explanation = explanation[:200] if explanation else f"✅ Correct: ({q['correct']}) {options[correct_idx]}"

    try:
        poll_msg = bot.send_poll(
            chat_id=chat_id,
            question=question_text,
            options=options,
            type="quiz",
            correct_option_id=correct_idx,
            explanation=explanation[:200] if explanation else None,
            is_anonymous=False,
            open_period=sess['time_per_question'],
        )

        # Store poll mapping
        with db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO poll_map
                (poll_id, session_id, q_index, q_db_id, chat_id, user_id, session_type)
                VALUES(?,?,?,?,?,?,?)
            """, (poll_msg.poll.id, session_id, idx, q_ids[idx],
                  chat_id, sess['user_id'], 'quiz'))

            # Store poll message id for tracking
            pmids = json.loads(sess['poll_msg_ids'] or '{}')
            pmids[str(idx)] = poll_msg.message_id
            conn.execute("UPDATE quiz_sessions SET poll_msg_ids=? WHERE id=?",
                         (json.dumps(pmids), session_id))

    except Exception as e:
        # Fallback to inline buttons if poll fails
        print(f"Poll send failed: {e}, using fallback")
        _send_quiz_fallback(chat_id, session_id, idx, q)
        return

    # Schedule auto-advance after timer expires
    def auto_advance():
        time.sleep(sess['time_per_question'] + 2)
        with db() as conn:
            s = conn.execute("SELECT * FROM quiz_sessions WHERE id=?", (session_id,)).fetchone()
            if not s or s['status'] != 'active': return
            answers = json.loads(s['answers'])
            key = str(q_ids[idx])
            if key not in answers:
                answers[key] = "SKIP"
                conn.execute("UPDATE quiz_sessions SET answers=?,current_index=? WHERE id=?",
                             (json.dumps(answers), idx + 1, session_id))
        send_quiz_poll(chat_id, session_id, idx + 1)

    t = threading.Thread(target=auto_advance, daemon=True)
    t.start()

def _send_quiz_fallback(chat_id, session_id, idx, q):
    """Fallback: inline keyboard buttons when poll API fails."""
    with db() as conn:
        sess = conn.execute("SELECT question_ids FROM quiz_sessions WHERE id=?", (session_id,)).fetchone()
    q_ids = json.loads(sess['question_ids'])
    total = len(q_ids)

    text = (
        f"<b>{q['question']}</b>\n\n"
        f"🅐 {q['option_a']}\n"
        f"🅑 {q['option_b']}\n"
        f"🅒 {q['option_c']}\n"
        f"🅓 {q['option_d']}"
    )
    kb = InlineKeyboardMarkup(row_width=4)
    kb.add(
        InlineKeyboardButton("A", callback_data=f"ans_{session_id}_{idx}_A"),
        InlineKeyboardButton("B", callback_data=f"ans_{session_id}_{idx}_B"),
        InlineKeyboardButton("C", callback_data=f"ans_{session_id}_{idx}_C"),
        InlineKeyboardButton("D", callback_data=f"ans_{session_id}_{idx}_D"),
    )
    kb.add(InlineKeyboardButton("⏭ Skip", callback_data=f"ans_{session_id}_{idx}_SKIP"))
    bot.send_message(chat_id, text, reply_markup=kb)

@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    """Handle user's answer to a quiz poll."""
    poll_id = poll_answer.poll_id
    user_id = poll_answer.user.id
    chosen = poll_answer.option_ids  # list of chosen indices

    with db() as conn:
        pm = conn.execute(
            "SELECT * FROM poll_map WHERE poll_id=? AND user_id=?", (poll_id, user_id)
        ).fetchone()

    if not pm:
        return

    session_id = pm['session_id']
    idx = pm['q_index']
    q_db_id = pm['q_db_id']
    chat_id = pm['chat_id']

    with db() as conn:
        sess = conn.execute("SELECT * FROM quiz_sessions WHERE id=?", (session_id,)).fetchone()
        if not sess or sess['status'] != 'active':
            return

        q_ids = json.loads(sess['question_ids'])
        answers = json.loads(sess['answers'])
        key = str(q_db_id)

        if key in answers:
            return  # already answered

        if not chosen:
            answer_letter = "SKIP"
        else:
            opt_letters = ['A', 'B', 'C', 'D']
            answer_letter = opt_letters[chosen[0]] if chosen[0] < 4 else 'A'

        answers[key] = answer_letter
        conn.execute("UPDATE quiz_sessions SET answers=?,current_index=? WHERE id=?",
                     (json.dumps(answers), idx + 1, session_id))

        # Mark as seen
        conn.execute("""
            INSERT OR REPLACE INTO user_question_history(user_id, question_id, session_type)
            VALUES(?,?,'quiz')
        """, (user_id, q_db_id))

    # Advance to next question
    time.sleep(1.5)
    send_quiz_poll(chat_id, session_id, idx + 1)

def handle_quiz_answer(chat_id, user_id, session_id, idx, answer):
    """Handle fallback inline button answer."""
    with db() as conn:
        sess = conn.execute("SELECT * FROM quiz_sessions WHERE id=?", (session_id,)).fetchone()
        if not sess or sess["status"] != "active": return

        q_ids = json.loads(sess["question_ids"])
        answers = json.loads(sess["answers"])
        key = str(q_ids[idx])

        if key in answers: return

        q = conn.execute("SELECT * FROM questions WHERE id=?", (q_ids[idx],)).fetchone()
        answers[key] = answer
        conn.execute("UPDATE quiz_sessions SET answers=?,current_index=? WHERE id=?",
                     (json.dumps(answers), idx + 1, session_id))
        conn.execute("""
            INSERT OR REPLACE INTO user_question_history(user_id,question_id,session_type)
            VALUES(?,?,'quiz')
        """, (user_id, q_ids[idx]))

    correct = answer == q["correct"]
    if answer == "SKIP":
        result = "⏭ <b>Skipped!</b>"
    elif correct:
        result = f"✅ <b>Correct!</b> +{sess['positive_marks']} marks"
    else:
        result = (f"❌ <b>Wrong!</b> -{sess['negative_marks']} marks\n"
                  f"✅ Correct: <b>({q['correct']}) {q['option_' + q['correct'].lower()]}</b>")

    if q["explanation"] and answer != "SKIP":
        result += f"\n\n💡 <i>{q['explanation']}</i>"

    bot.send_message(chat_id, result)
    time.sleep(0.8)
    send_quiz_poll(chat_id, session_id, idx + 1)

def start_quiz(chat_id, user_id, exam_id, section_id):
    with db() as conn:
        if section_id:
            qs = conn.execute(
                "SELECT * FROM quiz_settings WHERE exam_id=? AND section_id=? LIMIT 1",
                (exam_id, section_id)
            ).fetchone()
        else:
            qs = None

        if not qs:
            qs = conn.execute(
                "SELECT * FROM quiz_settings WHERE exam_id=? AND section_id IS NULL LIMIT 1",
                (exam_id,)
            ).fetchone()

        pos  = qs["positive_marks"]   if qs else 1.0
        neg  = qs["negative_marks"]   if qs else 0.25
        tpq  = qs["time_per_question"] if qs else 60
        total = qs["total_questions"]  if qs else 20

        seen = conn.execute(
            "SELECT question_id FROM user_question_history WHERE user_id=? AND session_type='quiz'",
            (user_id,)
        ).fetchall()
        seen_ids = {r["question_id"] for r in seen}

        if section_id:
            all_qs = conn.execute(
                "SELECT id FROM questions WHERE exam_id=? AND section_id=?", (exam_id, section_id)
            ).fetchall()
        else:
            all_qs = conn.execute(
                "SELECT id FROM questions WHERE exam_id=?", (exam_id,)
            ).fetchall()

        all_ids = [r["id"] for r in all_qs]
        fresh   = [i for i in all_ids if i not in seen_ids]

        if len(fresh) < 5:
            conn.execute(
                "DELETE FROM user_question_history WHERE user_id=? AND session_type='quiz'",
                (user_id,)
            )
            fresh = all_ids

        if not fresh:
            bot.send_message(chat_id,
                "❌ <b>No questions available yet!</b>\n"
                "Admin needs to add questions for this exam.",
                reply_markup=back_btn(f"exam_open_{exam_id}"))
            return

        selected = random.sample(fresh, min(total, len(fresh)))

        conn.execute("""
            INSERT INTO quiz_sessions
            (user_id,exam_id,section_id,question_ids,start_time,positive_marks,negative_marks,time_per_question)
            VALUES(?,?,?,?,?,?,?,?)
        """, (user_id, exam_id, section_id, json.dumps(selected),
              datetime.now().isoformat(), pos, neg, tpq))
        session_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    bot.send_message(
        chat_id,
        f"🚀 <b>Quiz Starting!</b>\n\n"
        f"📊 {len(selected)} questions\n"
        f"✅ +{pos} correct  ❌ -{neg} wrong\n"
        f"⏱ {tpq}s per question\n\n"
        f"<i>Answer each poll question before the timer runs out!</i>"
    )
    time.sleep(1)
    send_quiz_poll(chat_id, session_id, 0)

def end_quiz(chat_id, session_id):
    with db() as conn:
        sess = conn.execute("SELECT * FROM quiz_sessions WHERE id=?", (session_id,)).fetchone()
        if not sess: return

        q_ids   = json.loads(sess["question_ids"])
        answers = json.loads(sess["answers"])
        pos     = sess["positive_marks"]
        neg     = sess["negative_marks"]

        score = 0
        correct = wrong = skipped = 0
        for qid in q_ids:
            ans = answers.get(str(qid), "SKIP")
            q = conn.execute("SELECT correct FROM questions WHERE id=?", (qid,)).fetchone()
            if not q: continue
            if ans == "SKIP":
                skipped += 1
            elif ans == q["correct"]:
                score += pos; correct += 1
            else:
                score -= neg; wrong += 1

        score = max(0, score)
        total = len(q_ids)
        pct   = (correct / total * 100) if total else 0

        conn.execute("""
            UPDATE quiz_sessions SET score=?,end_time=?,status='completed' WHERE id=?
        """, (score, datetime.now().isoformat(), session_id))

    badge = (
        "🏆 Excellent!" if pct >= 80 else
        "👍 Good Job!"  if pct >= 60 else
        "📖 Keep Practicing" if pct >= 40 else
        "💪 Don't Give Up!"
    )
    bar = "🟩" * int(pct // 10) + "🟥" * (10 - int(pct // 10))

    text = (
        f"🎉 <b>Quiz Completed!</b>\n\n"
        f"{badge}\n\n"
        f"{bar}\n"
        f"📊 <b>Score:</b> {score:.1f} / {total * pos:.1f}\n"
        f"📈 <b>{pct:.1f}%</b>\n\n"
        f"✅ Correct: <b>{correct}</b>  "
        f"❌ Wrong: <b>{wrong}</b>  "
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
#  USER FLOW
# ─────────────────────────────────────────────
def show_exams(chat_id, msg_id=None):
    with db() as conn:
        exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()

    if not exams:
        text = "📭 <b>No exams available yet!</b>\nCheck back later. 🙏"
        if msg_id:
            try: bot.edit_message_text(text, chat_id, msg_id)
            except: bot.send_message(chat_id, text)
        else:
            bot.send_message(chat_id, text)
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for e in exams:
        kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}", callback_data=f"exam_open_{e['id']}"))

    text = "📚 <b>Available Exams</b>\n\nChoose your exam to get started! 🎯"
    if msg_id:
        try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        except: bot.send_message(chat_id, text, reply_markup=kb)
    else:
        bot.send_message(chat_id, text, reply_markup=kb)

def show_exam_detail(chat_id, exam_id, msg_id=None):
    with db() as conn:
        e       = conn.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
        sections = conn.execute("SELECT * FROM sections WHERE exam_id=?", (exam_id,)).fetchall()
        q_count  = conn.execute("SELECT COUNT(*) as c FROM questions WHERE exam_id=?", (exam_id,)).fetchone()["c"]
        p_count  = conn.execute("SELECT COUNT(*) as c FROM practice_sets WHERE exam_id=?", (exam_id,)).fetchone()["c"]

    if not e:
        bot.send_message(chat_id, "❌ Exam not found!"); return

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

def show_test_sections(chat_id, exam_id, msg_id=None):
    with db() as conn:
        sections = conn.execute("SELECT * FROM sections WHERE exam_id=?", (exam_id,)).fetchall()
        qs       = conn.execute(
            "SELECT * FROM quiz_settings WHERE exam_id=? AND section_id IS NULL LIMIT 1", (exam_id,)
        ).fetchone()

    marks = f"✅ +{qs['positive_marks']}  ❌ -{qs['negative_marks']}" if qs else "✅ +1  ❌ -0.25"
    time_q = f"⏱ {qs['time_per_question']}s/q" if qs else "⏱ 60s/q"

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("🎯 Full Exam Test", callback_data=f"start_quiz_{exam_id}_0"))
    for s in sections:
        kb.add(InlineKeyboardButton(f"{s['icon']} {s['name']}", callback_data=f"start_quiz_{exam_id}_{s['id']}"))
    kb.add(InlineKeyboardButton("◀️ Back", callback_data=f"exam_open_{exam_id}"))

    text = f"📝 <b>Select Test Section</b>\n\n{marks} · {time_q}\n\nChoose a section or full exam:"
    if msg_id:
        try: bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
        except: bot.send_message(chat_id, text, reply_markup=kb)
    else:
        bot.send_message(chat_id, text, reply_markup=kb)

def show_practice_sets(chat_id, exam_id, msg_id=None):
    with db() as conn:
        sets = conn.execute(
            "SELECT * FROM practice_sets WHERE exam_id=? ORDER BY id DESC", (exam_id,)
        ).fetchall()

    if not sets:
        text = "📭 <b>No practice sets yet!</b>"
        _edit_or_send(chat_id, msg_id, text, back_btn(f"exam_open_{exam_id}"))
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for s in sets:
        with db() as conn:
            cnt = conn.execute(
                "SELECT COUNT(*) as c FROM practice_questions WHERE practice_id=?", (s["id"],)
            ).fetchone()["c"]
        kb.add(InlineKeyboardButton(
            f"📝 {s['name']} ({cnt} Qs)",
            callback_data=f"practice_start_{exam_id}_{s['id']}"
        ))
    kb.add(InlineKeyboardButton("◀️ Back", callback_data=f"exam_open_{exam_id}"))

    _edit_or_send(chat_id, msg_id, "📖 <b>Practice Sets</b>\n\nChoose a set to start:", kb)

def _edit_or_send(chat_id, msg_id, text, kb=None):
    if msg_id:
        try:
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb)
            return
        except: pass
    bot.send_message(chat_id, text, reply_markup=kb)

def start_practice(chat_id, user_id, exam_id, practice_id, page=0):
    PER_PAGE = 10
    with db() as conn:
        seen = conn.execute(
            "SELECT question_id FROM user_question_history WHERE user_id=? AND session_type='practice'",
            (user_id,)
        ).fetchall()
        seen_ids = {r["question_id"] for r in seen}

        all_qs = conn.execute(
            "SELECT * FROM practice_questions WHERE practice_id=?", (practice_id,)
        ).fetchall()

        fresh = [q for q in all_qs if q["id"] not in seen_ids]
        if not fresh:
            conn.execute(
                "DELETE FROM user_question_history WHERE user_id=? AND session_type='practice'",
                (user_id,)
            )
            fresh = list(all_qs)

    if not fresh:
        bot.send_message(chat_id, "❌ No questions in this practice set!"); return

    batch      = fresh[page * PER_PAGE:(page + 1) * PER_PAGE]
    total_pages = (len(fresh) + PER_PAGE - 1) // PER_PAGE

    for q in batch:
        # Use native quiz poll for practice too
        opt_map = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
        correct_idx = opt_map.get(q['correct'].upper(), 0)
        options = [q['option_a'][:100], q['option_b'][:100], q['option_c'][:100], q['option_d'][:100]]
        exp = q['explanation'] or f"✅ Answer: ({q['correct']}) {options[correct_idx]}"

        try:
            bot.send_poll(
                chat_id=chat_id,
                question=q['question'][:300],
                options=options,
                type="quiz",
                correct_option_id=correct_idx,
                explanation=exp[:200],
                is_anonymous=False,
            )
        except Exception:
            # Fallback
            text = (
                f"📌 <b>Practice</b>\n\n<b>{q['question']}</b>\n\n"
                f"🅐 {q['option_a']}\n🅑 {q['option_b']}\n🅒 {q['option_c']}\n🅓 {q['option_d']}"
            )
            kb = InlineKeyboardMarkup(row_width=4)
            kb.add(
                InlineKeyboardButton("A", callback_data=f"pans_{practice_id}_{q['id']}_A_{page}"),
                InlineKeyboardButton("B", callback_data=f"pans_{practice_id}_{q['id']}_B_{page}"),
                InlineKeyboardButton("C", callback_data=f"pans_{practice_id}_{q['id']}_C_{page}"),
                InlineKeyboardButton("D", callback_data=f"pans_{practice_id}_{q['id']}_D_{page}"),
            )
            bot.send_message(chat_id, text, reply_markup=kb)

        with db() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO user_question_history(user_id,question_id,session_type)
                VALUES(?,?,'practice')
            """, (user_id, q["id"]))

    # Navigation
    kb2 = InlineKeyboardMarkup(row_width=1)
    if page + 1 < total_pages:
        remaining = len(fresh) - (page + 1) * PER_PAGE
        kb2.add(InlineKeyboardButton(
            f"▶️ Next 10 Questions ({remaining} remaining)",
            callback_data=f"practice_next_{exam_id}_{practice_id}_{page+1}"
        ))
    kb2.add(InlineKeyboardButton("◀️ Back to Practice Sets", callback_data=f"exam_practice_{exam_id}"))

    msg = f"📊 <b>Showing {len(batch)} of {len(fresh)} questions</b>"
    if page + 1 >= total_pages:
        msg += "\n✅ All questions shown! Great job!"

    bot.send_message(chat_id, msg, reply_markup=kb2)

def handle_practice_answer(chat_id, practice_id, q_id, answer, page):
    with db() as conn:
        q = conn.execute("SELECT * FROM practice_questions WHERE id=?", (q_id,)).fetchone()
    if not q: return
    correct = answer == q["correct"]
    result = (
        f"{'✅' if correct else '❌'} <b>{'Correct!' if correct else 'Wrong!'}</b>\n"
        f"✅ Answer: <b>({q['correct']}) {q['option_' + q['correct'].lower()]}</b>"
    )
    if q["explanation"]:
        result += f"\n💡 <i>{q['explanation']}</i>"
    bot.send_message(chat_id, result)

def show_resources(chat_id, exam_id, msg_id=None):
    with db() as conn:
        resources = conn.execute(
            "SELECT * FROM resources WHERE exam_id=? ORDER BY id DESC", (exam_id,)
        ).fetchall()

    if not resources:
        _edit_or_send(chat_id, msg_id, "📭 <b>No resources available yet!</b>",
                      back_btn(f"exam_open_{exam_id}"))
        return

    kb = InlineKeyboardMarkup(row_width=1)
    for r in resources:
        icon = "📄" if r["file_type"] == "pdf" else "🖼" if r["file_type"] == "photo" else "🔗"
        kb.add(InlineKeyboardButton(f"{icon} {r['title']}", callback_data=f"res_get_{r['id']}"))
    kb.add(InlineKeyboardButton("◀️ Back", callback_data=f"exam_open_{exam_id}"))

    text = f"📂 <b>Study Resources</b>\n\nTap any resource to download:"
    _edit_or_send(chat_id, msg_id, text, kb)

# ─────────────────────────────────────────────
#  ADMIN PANEL
# ─────────────────────────────────────────────
def show_admin_panel(chat_id, msg_id=None):
    with db() as conn:
        exams     = conn.execute("SELECT COUNT(*) as c FROM exams").fetchone()["c"]
        questions = conn.execute("SELECT COUNT(*) as c FROM questions").fetchone()["c"]
        users     = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]

    text = (
        f"⚙️ <b>Admin Panel</b>\n\n"
        f"📚 Exams: <b>{exams}</b>  ❓ Qs: <b>{questions}</b>  👥 Users: <b>{users}</b>\n\n"
        f"What would you like to do?"
    )
    _edit_or_send(chat_id, msg_id, text, admin_main_kb())

# ─────────────────────────────────────────────
#  COMMAND HANDLERS
# ─────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    register_user(msg.from_user)
    name = msg.from_user.first_name or "Student"
    text = (
        f"🎓 <b>Welcome to TestBook Pro, {name}!</b>\n\n"
        f"Your ultimate Telegram exam prep companion!\n\n"
        f"🔹 Timed mock tests with quiz polls\n"
        f"🔹 Practice with previous year papers\n"
        f"🔹 Download study resources\n"
        f"🔹 Track your progress & leaderboard\n\n"
        f"Tap <b>📚 Exams</b> to get started! 👇"
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu_kb(msg.from_user.id))

@bot.message_handler(commands=['admin'])
def cmd_admin(msg):
    if not is_admin(msg.from_user.id):
        bot.send_message(msg.chat.id, "❌ Access denied!"); return
    show_admin_panel(msg.chat.id)

@bot.message_handler(commands=['help'])
def cmd_help(msg):
    text = (
        "ℹ️ <b>TestBook Pro — Help</b>\n\n"
        "📚 <b>Exams</b> — Browse all available exams\n"
        "📝 <b>Take Test</b> — Timed MCQ quiz polls\n"
        "📖 <b>Practice</b> — Practice question sets\n"
        "📂 <b>Resources</b> — Download study material\n"
        "💬 <b>Help Group</b> — Exam-specific groups\n"
        "📊 <b>My Progress</b> — View test history\n"
        "🏆 <b>Leaderboard</b> — Top performers\n\n"
        "⭐ Questions never repeat in same session!\n"
        "⭐ Negative marking applies to wrong answers\n"
        "⭐ Polls auto-skip when timer expires"
    )
    bot.send_message(msg.chat.id, text, reply_markup=main_menu_kb(msg.from_user.id))

@bot.message_handler(func=lambda m: m.text == "📚 Exams")
def btn_exams(msg):
    register_user(msg.from_user)
    show_exams(msg.chat.id)

@bot.message_handler(func=lambda m: m.text == "⚙️ Admin Panel")
def btn_admin(msg):
    if not is_admin(msg.from_user.id):
        bot.send_message(msg.chat.id, "❌ Access denied!"); return
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
        bot.send_message(msg.chat.id, "📊 <b>No tests taken yet!</b>\nStart a test to see your progress! 🚀")
        return

    text = "📊 <b>Your Recent Tests</b>\n\n"
    for s in sessions:
        q_ids = json.loads(s["question_ids"])
        total = len(q_ids)
        pct = (s["score"] / (total * s["positive_marks"]) * 100) if total else 0
        bar = "🟩" * int(pct // 20) + "⬜" * (5 - int(pct // 20))
        text += (
            f"{s['exam_icon'] or '📘'} <b>{s['exam_name'] or 'Test'}</b>\n"
            f"   {bar} {pct:.0f}% — Score: {s['score']:.1f}\n\n"
        )
    bot.send_message(msg.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "🏆 Leaderboard")
def btn_leaderboard(msg):
    with db() as conn:
        rows = conn.execute("""
            SELECT u.full_name, u.username, SUM(qs.score) as total_score, COUNT(qs.id) as tests
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

    medals = ["🥇","🥈","🥉"] + ["🏅"] * 7
    text = "🏆 <b>Top Performers</b>\n\n"
    for i, r in enumerate(rows):
        name = r["full_name"] or r["username"] or "Student"
        text += f"{medals[i]} <b>{name}</b> — {r['total_score']:.0f} pts ({r['tests']} tests)\n"
    bot.send_message(msg.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "ℹ️ Help")
def btn_help(msg):
    cmd_help(msg)

# ─────────────────────────────────────────────
#  ADMIN TEXT / FILE INPUT HANDLER
# ─────────────────────────────────────────────
@bot.message_handler(content_types=['text', 'document', 'photo'])
def handle_text(msg):
    uid = msg.from_user.id
    if not is_admin(uid): return

    state, data = get_admin_state(uid)
    if not state: return

    chat = msg.chat.id

    # ── ADD EXAM ──
    if state == "add_exam_name":
        data["name"] = msg.text
        set_admin_state(uid, "add_exam_icon", data)
        bot.send_message(chat, "📌 Enter exam icon emoji (e.g. 📘) or type <code>skip</code>:")

    elif state == "add_exam_icon":
        data["icon"] = msg.text if msg.text.lower() != "skip" else "📘"
        set_admin_state(uid, "add_exam_desc", data)
        bot.send_message(chat, "📝 Enter exam description or type <code>skip</code>:")

    elif state == "add_exam_desc":
        data["description"] = msg.text if msg.text.lower() != "skip" else ""
        with db() as conn:
            conn.execute("INSERT INTO exams(name,icon,description) VALUES(?,?,?)",
                         (data["name"], data["icon"], data["description"]))
        clear_admin_state(uid)
        bot.send_message(chat, f"✅ Exam <b>{data['name']}</b> created!", reply_markup=admin_main_kb())

    # ── ADD SECTION ──
    elif state == "add_section_name":
        data["sec_name"] = msg.text
        set_admin_state(uid, "add_section_icon", data)
        bot.send_message(chat, "📌 Section icon emoji or type <code>skip</code>:")

    elif state == "add_section_icon":
        data["sec_icon"] = msg.text if msg.text.lower() != "skip" else "📂"
        with db() as conn:
            conn.execute("INSERT INTO sections(exam_id,name,icon) VALUES(?,?,?)",
                         (data["exam_id"], data["sec_name"], data["sec_icon"]))
        clear_admin_state(uid)
        bot.send_message(chat, f"✅ Section <b>{data['sec_name']}</b> added!", reply_markup=admin_main_kb())

    # ── QUIZ SETTINGS ──
    elif state == "qs_positive":
        try:
            data["positive"] = float(msg.text)
            set_admin_state(uid, "qs_negative", data)
            bot.send_message(chat, "❌ Enter negative marks per wrong answer (e.g. 0.25):")
        except:
            bot.send_message(chat, "⚠️ Enter a valid number:")

    elif state == "qs_negative":
        try:
            data["negative"] = float(msg.text)
            set_admin_state(uid, "qs_time", data)
            bot.send_message(chat, "⏱ Time per question in seconds (e.g. 60):")
        except:
            bot.send_message(chat, "⚠️ Enter a valid number:")

    elif state == "qs_time":
        try:
            data["time"] = int(msg.text)
            set_admin_state(uid, "qs_total", data)
            bot.send_message(chat, "🔢 Total questions per test (e.g. 20):")
        except:
            bot.send_message(chat, "⚠️ Enter a valid integer:")

    elif state == "qs_total":
        try:
            data["total"] = int(msg.text)
            with db() as conn:
                conn.execute("DELETE FROM quiz_settings WHERE exam_id=? AND section_id IS NULL",
                             (data["exam_id"],))
                conn.execute("""
                    INSERT INTO quiz_settings(exam_id,positive_marks,negative_marks,time_per_question,total_questions)
                    VALUES(?,?,?,?,?)
                """, (data["exam_id"], data["positive"], data["negative"], data["time"], data["total"]))
            clear_admin_state(uid)
            bot.send_message(chat,
                f"✅ <b>Settings Saved!</b>\n"
                f"✅ +{data['positive']}  ❌ -{data['negative']}  ⏱ {data['time']}s  🔢 {data['total']}q",
                reply_markup=admin_main_kb())
        except:
            bot.send_message(chat, "⚠️ Enter a valid integer:")

    # ── SUPPORT GROUP ──
    elif state == "set_group":
        with db() as conn:
            conn.execute("UPDATE exams SET support_group=? WHERE id=?",
                         (msg.text.strip(), data["exam_id"]))
        clear_admin_state(uid)
        bot.send_message(chat, "✅ Support group link saved!", reply_markup=admin_main_kb())

    # ── RESOURCE ──
    elif state == "add_resource_title":
        data["res_title"] = msg.text
        set_admin_state(uid, "add_resource_file", data)
        bot.send_message(chat, "📤 Send the file (PDF/photo) or a URL:")

    elif state == "add_resource_file":
        file_id = file_type = url = None
        if msg.document:
            file_id, file_type = msg.document.file_id, "pdf"
        elif msg.photo:
            file_id, file_type = msg.photo[-1].file_id, "photo"
        elif msg.text and msg.text.startswith("http"):
            url, file_type = msg.text, "url"
        else:
            bot.send_message(chat, "⚠️ Send a file or URL:"); return

        with db() as conn:
            conn.execute("""
                INSERT INTO resources(exam_id,section_id,title,file_id,file_type,url)
                VALUES(?,?,?,?,?,?)
            """, (data["exam_id"], data.get("section_id"), data["res_title"], file_id, file_type, url))
        clear_admin_state(uid)
        bot.send_message(chat, "✅ Resource added!", reply_markup=admin_main_kb())

    # ── PDF UPLOAD ──
    elif state == "upload_quiz_pdf":
        if not msg.document:
            bot.send_message(chat, "⚠️ Please send a PDF file:"); return
        process_pdf_upload(msg, data, "quiz")

    elif state == "upload_practice_pdf_name":
        data["practice_name"] = msg.text
        set_admin_state(uid, "upload_practice_pdf", data)
        bot.send_message(chat, "📤 Now send the Practice Set PDF file:")

    elif state == "upload_practice_pdf":
        if not msg.document:
            bot.send_message(chat, "⚠️ Please send a PDF file:"); return
        process_pdf_upload(msg, data, "practice")

def process_pdf_upload(msg, data, upload_type):
    uid  = msg.from_user.id
    chat = msg.chat.id

    prog_msg = bot.send_message(
        chat,
        "⏳ <b>Analyzing PDF...</b>\n\n"
        "🔍 Extracting questions using multi-strategy parser...\n"
        "⚙️ This may take a moment for large PDFs."
    )

    try:
        file_info  = bot.get_file(msg.document.file_id)
        file_bytes = bot.download_file(file_info.file_path)

        try:
            bot.edit_message_text(
                "⏳ <b>Processing PDF...</b>\n🔄 Text extracted, parsing MCQs...",
                chat, prog_msg.message_id
            )
        except: pass

        questions, error = extract_mcqs_from_pdf(file_bytes)

        try:
            bot.delete_message(chat, prog_msg.message_id)
        except: pass

        if error:
            bot.send_message(chat, f"❌ {error}", reply_markup=admin_main_kb())
            clear_admin_state(uid); return

        if not questions:
            bot.send_message(chat,
                "❌ <b>No MCQs found!</b>\n\n"
                "Supported formats:\n"
                "• <code>1. Question text\n(A) Option A\n(B) Option B\n(C) Option C\n(D) Option D\nAns: A</code>\n\n"
                "• <code>Q1. Question\nA. Option\nB. Option\nC. Option\nD. Option\nAnswer: B</code>\n\n"
                "Make sure PDF has selectable text (not scanned image).",
                reply_markup=admin_main_kb()
            )
            clear_admin_state(uid); return

        with db() as conn:
            if upload_type == "quiz":
                exam_id    = data["exam_id"]
                section_id = data.get("section_id")
                for q in questions:
                    conn.execute("""
                        INSERT INTO questions
                        (exam_id,section_id,question,option_a,option_b,option_c,option_d,correct,explanation,source)
                        VALUES(?,?,?,?,?,?,?,?,?,'pdf')
                    """, (exam_id, section_id, q["question"], q["option_a"], q["option_b"],
                          q["option_c"], q["option_d"], q["correct"], q["explanation"]))

                bot.send_message(chat,
                    f"✅ <b>PDF Processed Successfully!</b>\n\n"
                    f"📊 Extracted: <b>{len(questions)}</b> questions\n"
                    f"💾 Saved to: Quiz Bank ✅\n\n"
                    f"Questions are ready for tests! 🎉",
                    reply_markup=admin_main_kb())

            elif upload_type == "practice":
                exam_id    = data["exam_id"]
                section_id = data.get("section_id")
                name       = data.get("practice_name", "Practice Set")
                conn.execute("INSERT INTO practice_sets(exam_id,section_id,name) VALUES(?,?,?)",
                             (exam_id, section_id, name))
                pset_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                for q in questions:
                    conn.execute("""
                        INSERT INTO practice_questions
                        (practice_id,question,option_a,option_b,option_c,option_d,correct,explanation)
                        VALUES(?,?,?,?,?,?,?,?)
                    """, (pset_id, q["question"], q["option_a"], q["option_b"],
                          q["option_c"], q["option_d"], q["correct"], q["explanation"]))

                bot.send_message(chat,
                    f"✅ <b>Practice Set Created!</b>\n\n"
                    f"📝 Name: <b>{name}</b>\n"
                    f"📊 Questions: <b>{len(questions)}</b>\n\n"
                    f"Users can now practice! 🎉",
                    reply_markup=admin_main_kb())

        clear_admin_state(uid)

    except Exception as e:
        try: bot.delete_message(chat, prog_msg.message_id)
        except: pass
        bot.send_message(chat, f"❌ Error: {str(e)}", reply_markup=admin_main_kb())
        clear_admin_state(uid)

# ─────────────────────────────────────────────
#  CALLBACK HANDLER
# ─────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(c):
    uid  = c.from_user.id
    chat = c.message.chat.id
    mid  = c.message.message_id
    d    = c.data
    bot.answer_callback_query(c.id)

    # Navigation
    if d in ("back_exams", "home"):
        show_exams(chat, mid)

    elif d.startswith("exam_open_"):
        show_exam_detail(chat, int(d.split("_")[-1]), mid)

    elif d.startswith("exam_test_"):
        show_test_sections(chat, int(d.split("_")[-1]), mid)

    elif d.startswith("exam_practice_"):
        show_practice_sets(chat, int(d.split("_")[-1]), mid)

    elif d.startswith("exam_resources_"):
        show_resources(chat, int(d.split("_")[-1]), mid)

    elif d.startswith("exam_group_"):
        exam_id = int(d.split("_")[-1])
        with db() as conn:
            e = conn.execute("SELECT support_group,name FROM exams WHERE id=?", (exam_id,)).fetchone()
        if e and e["support_group"]:
            kb = InlineKeyboardMarkup()
            kb.add(InlineKeyboardButton(f"💬 Join {e['name']} Group", url=e["support_group"]))
            kb.add(InlineKeyboardButton("◀️ Back", callback_data=f"exam_open_{exam_id}"))
            _edit_or_send(chat, mid,
                "💬 <b>Join the Help Group</b>\n\nGet help, discuss doubts, share notes!", kb)
        else:
            bot.send_message(chat, "❌ No support group linked yet.")

    elif d.startswith("start_quiz_"):
        parts    = d.split("_")
        exam_id  = int(parts[2])
        sec_id   = int(parts[3]) if parts[3] != "0" else None
        start_quiz(chat, uid, exam_id, sec_id)

    elif d.startswith("ans_"):
        parts = d.split("_")
        sess_id = int(parts[1])
        idx     = int(parts[2])
        answer  = parts[3]
        try: bot.edit_message_reply_markup(chat, mid, reply_markup=None)
        except: pass
        handle_quiz_answer(chat, uid, sess_id, idx, answer)

    elif d.startswith("practice_start_"):
        parts = d.split("_")
        start_practice(chat, uid, int(parts[2]), int(parts[3]), 0)

    elif d.startswith("practice_next_"):
        parts = d.split("_")
        start_practice(chat, uid, int(parts[2]), int(parts[3]), int(parts[4]))

    elif d.startswith("pans_"):
        parts = d.split("_")
        try: bot.edit_message_reply_markup(chat, mid, reply_markup=None)
        except: pass
        handle_practice_answer(chat, int(parts[1]), int(parts[2]), parts[3], int(parts[4]))

    elif d.startswith("res_get_"):
        res_id = int(d.split("_")[-1])
        with db() as conn:
            r = conn.execute("SELECT * FROM resources WHERE id=?", (res_id,)).fetchone()
        if not r:
            bot.send_message(chat, "❌ Resource not found!"); return
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
            bot.send_message(chat, "📭 No exams yet!", reply_markup=back_btn("admin_panel")); return
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}",
                                        callback_data=f"admin_exam_detail_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        _edit_or_send(chat, mid, "📋 <b>Manage Exams</b>\n\nSelect an exam:", kb)

    elif d.startswith("admin_exam_detail_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        with db() as conn:
            e     = conn.execute("SELECT * FROM exams WHERE id=?", (exam_id,)).fetchone()
            q_cnt = conn.execute("SELECT COUNT(*) as c FROM questions WHERE exam_id=?", (exam_id,)).fetchone()["c"]
            s_cnt = conn.execute("SELECT COUNT(*) as c FROM sections WHERE exam_id=?", (exam_id,)).fetchone()["c"]
            p_cnt = conn.execute("SELECT COUNT(*) as c FROM practice_sets WHERE exam_id=?", (exam_id,)).fetchone()["c"]
        text = (
            f"{e['icon']} <b>{e['name']}</b>\n\n"
            f"📂 Sections: {s_cnt}  ❓ Qs: {q_cnt}  📝 Sets: {p_cnt}"
        )
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📤 Upload Quiz PDF",     callback_data=f"admin_upq_{exam_id}"),
            InlineKeyboardButton("📤 Upload Practice PDF", callback_data=f"admin_upp_{exam_id}"),
            InlineKeyboardButton("⚙️ Quiz Settings",       callback_data=f"admin_qset_{exam_id}"),
            InlineKeyboardButton("💬 Set Group",           callback_data=f"admin_sgroup_{exam_id}"),
            InlineKeyboardButton("📎 Add Resource",        callback_data=f"admin_ares_{exam_id}"),
            InlineKeyboardButton("❌ Delete Exam",         callback_data=f"admin_del_exam_{exam_id}"),
            InlineKeyboardButton("◀️ Back",               callback_data="admin_manage_exams")
        )
        _edit_or_send(chat, mid, text, kb)

    elif d.startswith("admin_del_exam_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ Yes, Delete", callback_data=f"admin_confirm_del_{exam_id}"),
            InlineKeyboardButton("❌ Cancel",      callback_data=f"admin_exam_detail_{exam_id}")
        )
        _edit_or_send(chat, mid, "⚠️ <b>Delete this exam and ALL its data?</b>", kb)

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
        _edit_or_send(chat, mid, "✅ Exam deleted successfully.", back_btn("admin_manage_exams"))

    elif d.startswith("admin_upq_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "upload_quiz_pdf", {"exam_id": exam_id})
        bot.send_message(chat,
            "📤 <b>Upload Quiz PDF</b>\n\n"
            "Send the PDF file with MCQ questions.\n\n"
            "<b>Supported formats:</b>\n"
            "<code>1. Question text\n(A) Option\n(B) Option\n(C) Option\n(D) Option\nAns: A</code>")

    elif d.startswith("admin_upp_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "upload_practice_pdf_name", {"exam_id": exam_id})
        bot.send_message(chat, "📝 Enter a name for this Practice Set (e.g. <i>Biology Practice 1</i>):")

    elif d.startswith("admin_qset_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "qs_positive", {"exam_id": exam_id})
        bot.send_message(chat, "✅ Enter <b>positive marks</b> per correct answer (e.g. 1 or 2):")

    elif d.startswith("admin_sgroup_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "set_group", {"exam_id": exam_id})
        bot.send_message(chat, "💬 Enter Telegram group/channel link (e.g. https://t.me/...):")

    elif d.startswith("admin_ares_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "add_resource_title", {"exam_id": exam_id})
        bot.send_message(chat, "📎 Enter resource title (e.g. <i>Biology Notes PDF</i>):")

    elif d == "admin_add_section" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        if not exams:
            bot.send_message(chat, "❌ Create an exam first!"); return
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}",
                                        callback_data=f"admin_sec_exam_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        _edit_or_send(chat, mid, "📂 Select exam to add section:", kb)

    elif d.startswith("admin_sec_exam_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        set_admin_state(uid, "add_section_name", {"exam_id": exam_id})
        bot.send_message(chat, "📂 Enter <b>Section Name</b> (e.g. Biology, English, GS):")

    elif d == "admin_upload_quiz_pdf" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        if not exams:
            bot.send_message(chat, "❌ Create an exam first!"); return
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}",
                                        callback_data=f"admin_upq_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        _edit_or_send(chat, mid, "📤 Select exam for Quiz PDF upload:", kb)

    elif d == "admin_upload_practice_pdf" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        if not exams:
            bot.send_message(chat, "❌ Create an exam first!"); return
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}",
                                        callback_data=f"admin_upp_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        _edit_or_send(chat, mid, "📤 Select exam for Practice PDF upload:", kb)

    elif d == "admin_quiz_settings" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}",
                                        callback_data=f"admin_qset_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        _edit_or_send(chat, mid, "⚙️ Select exam to configure:", kb)

    elif d == "admin_set_group" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}",
                                        callback_data=f"admin_sgroup_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        _edit_or_send(chat, mid, "💬 Select exam to set support group:", kb)

    elif d == "admin_add_resource" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']}",
                                        callback_data=f"admin_ares_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        _edit_or_send(chat, mid, "📎 Select exam for resource:", kb)

    elif d == "admin_stats" and is_admin(uid):
        with db() as conn:
            users      = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
            total_tests = conn.execute("SELECT COUNT(*) as c FROM quiz_sessions WHERE status='completed'").fetchone()["c"]
            total_q    = conn.execute("SELECT COUNT(*) as c FROM questions").fetchone()["c"]
            today      = datetime.now().strftime("%Y-%m-%d")
            today_u    = conn.execute(
                "SELECT COUNT(*) as c FROM users WHERE joined_at LIKE ?", (f"{today}%",)
            ).fetchone()["c"]
        text = (
            f"📊 <b>Bot Statistics</b>\n\n"
            f"👥 Total Users: <b>{users}</b>\n"
            f"🆕 New Today: <b>{today_u}</b>\n"
            f"📝 Total Tests: <b>{total_tests}</b>\n"
            f"❓ Total Questions: <b>{total_q}</b>"
        )
        _edit_or_send(chat, mid, text, back_btn("admin_panel"))

    elif d == "admin_manage_questions" and is_admin(uid):
        with db() as conn:
            exams = conn.execute("SELECT * FROM exams ORDER BY id DESC").fetchall()
        kb = InlineKeyboardMarkup(row_width=1)
        for e in exams:
            with db() as conn2:
                q_cnt = conn2.execute(
                    "SELECT COUNT(*) as c FROM questions WHERE exam_id=?", (e["id"],)
                ).fetchone()["c"]
            kb.add(InlineKeyboardButton(f"{e['icon']} {e['name']} ({q_cnt} Qs)",
                                        callback_data=f"admin_qlist_{e['id']}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_panel"))
        _edit_or_send(chat, mid, "🔧 <b>Manage Questions</b>\nSelect exam:", kb)

    elif d.startswith("admin_qlist_") and is_admin(uid):
        exam_id = int(d.split("_")[-1])
        with db() as conn:
            qs = conn.execute(
                "SELECT id,question FROM questions WHERE exam_id=? ORDER BY id DESC LIMIT 20",
                (exam_id,)
            ).fetchall()
        if not qs:
            bot.send_message(chat, "📭 No questions yet!", reply_markup=back_btn("admin_manage_questions")); return
        kb = InlineKeyboardMarkup(row_width=1)
        for q in qs:
            short = q["question"][:45] + "…" if len(q["question"]) > 45 else q["question"]
            kb.add(InlineKeyboardButton(f"❌ {short}", callback_data=f"admin_delq_{q['id']}_{exam_id}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_manage_questions"))
        _edit_or_send(chat, mid, "🔧 Tap to delete a question:", kb)

    elif d.startswith("admin_delq_") and is_admin(uid):
        parts   = d.split("_")
        q_id    = int(parts[2])
        exam_id = int(parts[3])
        with db() as conn:
            conn.execute("DELETE FROM questions WHERE id=?", (q_id,))
        bot.answer_callback_query(c.id, "✅ Question deleted!")
        with db() as conn:
            qs = conn.execute(
                "SELECT id,question FROM questions WHERE exam_id=? ORDER BY id DESC LIMIT 20",
                (exam_id,)
            ).fetchall()
        kb = InlineKeyboardMarkup(row_width=1)
        for q in qs:
            short = q["question"][:45] + "…" if len(q["question"]) > 45 else q["question"]
            kb.add(InlineKeyboardButton(f"❌ {short}", callback_data=f"admin_delq_{q['id']}_{exam_id}"))
        kb.add(InlineKeyboardButton("◀️ Back", callback_data="admin_manage_questions"))
        try: bot.edit_message_reply_markup(chat, mid, reply_markup=kb)
        except: pass

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Initializing TestBook Pro Bot v2...")
    init_db()
    print("✅ Database ready!")
    print("🤖 Bot is running... Press Ctrl+C to stop")
    bot.infinity_polling(timeout=30, long_polling_timeout=30)
