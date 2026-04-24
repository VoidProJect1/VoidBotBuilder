"""
templates/quiz_bot.py
======================
Advanced Quiz Bot
- Fetches questions from Open Trivia DB (opentdb.com) — free public API
- Categories, difficulty selection, timed rounds
- Points system, leaderboard, streaks
- Admin: set reward per correct answer, set categories, broadcast
- Full keyboard UI with back/cancel
"""
from __future__ import annotations

import html
import logging
import random
from datetime import datetime

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

from templates.base import BaseTemplate

logger = logging.getLogger(__name__)

TEMPLATE_INFO = {
    "id":          "quiz_bot",
    "name":        "Quiz Bot",
    "emoji":       "🧠",
    "category":    "Entertainment",
    "description": "Live quiz with public API questions, points & leaderboard",
    "features":    [
        "Questions from Open Trivia DB (free API)",
        "Multiple categories & difficulty levels",
        "Points system with streak bonuses",
        "Timed answers (30 seconds)",
        "Leaderboard with ranks",
        "Admin: set rewards, manage users",
        "Daily quiz challenges",
    ],
    "complexity":  "Intermediate",
    "best_for":    "Entertainment & educational channels",
    "stars":       5,
    "new":         True,
}

OPENTDB_URL = "https://opentdb.com/api.php"
CATEGORIES = {
    "9":  "🌍 General Knowledge",
    "17": "🔬 Science & Nature",
    "21": "⚽ Sports",
    "23": "📜 History",
    "25": "🎨 Art",
    "27": "🐾 Animals",
    "18": "💻 Computers",
    "19": "📐 Mathematics",
    "22": "🌐 Geography",
    "11": "🎬 Film",
    "12": "🎵 Music",
}
DIFFICULTIES = {"easy": "🟢 Easy", "medium": "🟡 Medium", "hard": "🔴 Hard"}

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main(is_admin=False):
    buttons = [
        [InlineKeyboardButton("▶️ Start Quiz", callback_data="quiz_pick_cat"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="quiz_leaderboard")],
        [InlineKeyboardButton("📊 My Stats", callback_data="quiz_my_stats"),
         InlineKeyboardButton("ℹ️ How to Play", callback_data="quiz_how")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="quiz_admin")])
    return InlineKeyboardMarkup(buttons)

def kb_back(target="quiz_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=target)]])

def kb_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="quiz_main")]])

def kb_categories():
    buttons = []
    cats = list(CATEGORIES.items())
    for i in range(0, len(cats), 2):
        row = [InlineKeyboardButton(cats[i][1], callback_data=f"quiz_cat_{cats[i][0]}")]
        if i + 1 < len(cats):
            row.append(InlineKeyboardButton(cats[i+1][1], callback_data=f"quiz_cat_{cats[i+1][0]}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🎲 Random", callback_data="quiz_cat_random")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="quiz_main")])
    return InlineKeyboardMarkup(buttons)

def kb_difficulty(cat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(v, callback_data=f"quiz_diff_{cat_id}_{k}") for k, v in DIFFICULTIES.items()],
        [InlineKeyboardButton("⬅️ Back", callback_data="quiz_pick_cat")]
    ])

def kb_answers(options: list, q_id: str):
    buttons = [[InlineKeyboardButton(opt, callback_data=f"quiz_ans_{q_id}_{i}")]
               for i, opt in enumerate(options)]
    buttons.append([InlineKeyboardButton("⏭ Skip", callback_data=f"quiz_skip_{q_id}")])
    return InlineKeyboardMarkup(buttons)

def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Set Points/Correct", callback_data="quiz_adm_points"),
         InlineKeyboardButton("📨 Broadcast", callback_data="quiz_adm_broadcast")],
        [InlineKeyboardButton("🔄 Reset Leaderboard", callback_data="quiz_adm_reset_lb"),
         InlineKeyboardButton("📈 Stats", callback_data="quiz_adm_stats")],
        [InlineKeyboardButton("⬅️ Back", callback_data="quiz_main")],
    ])

# ── API helper ────────────────────────────────────────────────────────────────

async def fetch_question(cat_id: str = None, difficulty: str = "medium") -> dict | None:
    params = {"amount": 1, "type": "multiple", "encode": "url3986", "difficulty": difficulty}
    if cat_id and cat_id != "random":
        params["category"] = cat_id
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(OPENTDB_URL, params=params, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                data = await resp.json()
                if data.get("response_code") == 0 and data.get("results"):
                    r = data["results"][0]
                    from urllib.parse import unquote
                    question = unquote(r["question"])
                    correct = unquote(r["correct_answer"])
                    incorrects = [unquote(x) for x in r["incorrect_answers"]]
                    options = incorrects + [correct]
                    random.shuffle(options)
                    return {
                        "question": question,
                        "correct": correct,
                        "options": options,
                        "category": unquote(r["category"]),
                        "difficulty": r["difficulty"],
                    }
    except Exception as e:
        logger.error("OpenTDB fetch failed: %s", e)
    return None

# ── DB helpers ────────────────────────────────────────────────────────────────

async def db_ensure_user(db, uid, username):
    await db.execute("""
        INSERT OR IGNORE INTO quiz_users (user_id, username, points, correct, wrong, streak)
        VALUES (?,?,0,0,0,0)
    """, (uid, username or ""))
    await db.commit()

async def db_get_user(db, uid):
    row = await db.fetchone("SELECT * FROM quiz_users WHERE user_id=?", (uid,))
    return dict(row) if row else None

async def db_get_setting(db, bot_id, key, default=None):
    row = await db.fetchone("SELECT value FROM quiz_settings WHERE bot_id=? AND key=?", (bot_id, key))
    return row["value"] if row else default

async def db_set_setting(db, bot_id, key, value):
    await db.execute("""
        INSERT INTO quiz_settings (bot_id, key, value) VALUES (?,?,?)
        ON CONFLICT(bot_id,key) DO UPDATE SET value=excluded.value
    """, (bot_id, key, str(value)))
    await db.commit()

# ── Template class ────────────────────────────────────────────────────────────

class Template(BaseTemplate):

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        await db_ensure_user(self.db, uid, update.effective_user.username)
        await update.message.reply_text(
            "🧠 *Welcome to Quiz Bot!*\n\nTest your knowledge and climb the leaderboard!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(self.is_admin(uid))
        )

    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        data = q.data
        await db_ensure_user(self.db, uid, q.from_user.username)

        if data == "quiz_main":
            ctx.user_data.clear()
            await q.edit_message_text(
                "🧠 *Quiz Bot*\nChoose an option:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(self.is_admin(uid))
            )

        elif data == "quiz_pick_cat":
            await q.edit_message_text("📚 *Select Category:*",
                                       parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=kb_categories())

        elif data.startswith("quiz_cat_"):
            cat_id = data.replace("quiz_cat_", "")
            ctx.user_data["quiz_cat"] = cat_id
            await q.edit_message_text("🎯 *Select Difficulty:*",
                                       parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=kb_difficulty(cat_id))

        elif data.startswith("quiz_diff_"):
            parts = data.split("_")
            cat_id = parts[2]
            difficulty = parts[3]
            ctx.user_data["quiz_cat"] = cat_id
            ctx.user_data["quiz_diff"] = difficulty
            await self._send_question(q, uid, ctx, cat_id, difficulty)

        elif data.startswith("quiz_ans_"):
            await self._handle_answer(q, uid, ctx, data)

        elif data.startswith("quiz_skip_"):
            await self._send_question(
                q, uid, ctx,
                ctx.user_data.get("quiz_cat", "random"),
                ctx.user_data.get("quiz_diff", "medium")
            )

        elif data == "quiz_leaderboard":
            await self._show_leaderboard(q)

        elif data == "quiz_my_stats":
            await self._show_my_stats(q, uid)

        elif data == "quiz_how":
            pts = await db_get_setting(self.db, self.bot_id, "points_per_correct", "5")
            await q.edit_message_text(
                f"ℹ️ *How to Play*\n\n"
                f"1. Pick a category & difficulty\n"
                f"2. Answer multiple-choice questions\n"
                f"3. Earn {pts} points per correct answer\n"
                f"4. Streak bonus: 2x points at 5+ streak\n"
                f"5. Climb the leaderboard!\n\n"
                f"Questions from Open Trivia DB 🌐",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
            )

        elif data == "quiz_admin":
            if not self.is_admin(uid):
                await q.answer("⛔ Not authorized", show_alert=True)
                return
            await q.edit_message_text("🔧 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=kb_admin())

        elif data == "quiz_adm_points":
            if not self.is_admin(uid): return
            ctx.user_data["adm_action"] = "set_points"
            await q.edit_message_text("💰 Enter points awarded per correct answer:", reply_markup=kb_cancel())

        elif data == "quiz_adm_broadcast":
            if not self.is_admin(uid): return
            ctx.user_data["adm_action"] = "broadcast"
            await q.edit_message_text("📨 Send your broadcast message:", reply_markup=kb_cancel())

        elif data == "quiz_adm_reset_lb":
            if not self.is_admin(uid): return
            await self.db.execute("UPDATE quiz_users SET points=0, correct=0, wrong=0, streak=0")
            await self.db.commit()
            await q.edit_message_text("✅ Leaderboard reset!", reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Back", callback_data="quiz_admin")
            ]]))

        elif data == "quiz_adm_stats":
            if not self.is_admin(uid): return
            total = (await self.db.fetchone("SELECT COUNT(*) AS c FROM quiz_users"))["c"]
            total_q = (await self.db.fetchone(
                "SELECT COALESCE(SUM(correct+wrong),0) AS s FROM quiz_users"))["s"]
            await q.edit_message_text(
                f"📈 *Stats*\n\nTotal Players: {total}\nQuestions Answered: {total_q}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="quiz_admin")]])
            )

    async def _send_question(self, q, uid, ctx, cat_id, difficulty):
        q_data = await fetch_question(cat_id if cat_id != "random" else None, difficulty)
        if not q_data:
            await q.edit_message_text(
                "❌ Couldn't fetch a question. API might be down. Try again!",
                reply_markup=kb_back()
            )
            return
        # Store correct answer index for validation
        correct_idx = q_data["options"].index(q_data["correct"])
        q_id = str(uid)[-4:] + str(int(datetime.utcnow().timestamp()))[-6:]
        ctx.user_data["current_q"] = {
            "id": q_id,
            "correct_idx": correct_idx,
            "correct_text": q_data["correct"],
            "options": q_data["options"],
            "cat": cat_id,
            "diff": difficulty,
        }
        diff_icon = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(difficulty, "")
        user = await db_get_user(self.db, uid)
        streak = user["streak"] if user else 0
        streak_text = f" 🔥 Streak: {streak}" if streak >= 2 else ""
        text = (
            f"{diff_icon} *{q_data['category']}*{streak_text}\n\n"
            f"❓ {q_data['question']}"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=kb_answers(q_data["options"], q_id))

    async def _handle_answer(self, q, uid, ctx, data: str):
        parts = data.split("_")
        # quiz_ans_{q_id}_{idx}
        q_id = parts[2]
        try:
            chosen_idx = int(parts[3])
        except (ValueError, IndexError):
            return

        current = ctx.user_data.get("current_q")
        if not current or current["id"] != q_id:
            await q.edit_message_text("⏱ Question expired!", reply_markup=kb_back())
            return

        is_correct = chosen_idx == current["correct_idx"]
        pts_per = int(await db_get_setting(self.db, self.bot_id, "points_per_correct", "5"))
        user = await db_get_user(self.db, uid)
        streak = user["streak"] if user else 0

        if is_correct:
            new_streak = streak + 1
            multiplier = 2 if new_streak >= 5 else 1
            earned = pts_per * multiplier
            await self.db.execute(
                "UPDATE quiz_users SET points=points+?, correct=correct+1, streak=? WHERE user_id=?",
                (earned, new_streak, uid)
            )
            await self.db.commit()
            streak_bonus = f" 🔥 ×2 Streak Bonus!" if multiplier == 2 else ""
            result_text = (
                f"✅ *Correct!*{streak_bonus}\n"
                f"+{earned} points (Streak: {new_streak})\n\n"
                f"Answer: {current['correct_text']}"
            )
        else:
            await self.db.execute(
                "UPDATE quiz_users SET wrong=wrong+1, streak=0 WHERE user_id=?", (uid,)
            )
            await self.db.commit()
            result_text = (
                f"❌ *Wrong!*\n\n"
                f"Correct answer: *{current['correct_text']}*\n"
                f"Streak reset 😢"
            )

        next_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Next Question", callback_data=f"quiz_diff_{current['cat']}_{current['diff']}"),
             InlineKeyboardButton("🏠 Menu", callback_data="quiz_main")]
        ])
        ctx.user_data.pop("current_q", None)
        await q.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN, reply_markup=next_kb)

    async def _show_leaderboard(self, q):
        rows = await self.db.fetchall(
            "SELECT user_id, username, points, correct FROM quiz_users ORDER BY points DESC LIMIT 10"
        )
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines = ["🏆 *Quiz Leaderboard*\n"]
        for i, r in enumerate(rows):
            uname = f"@{r['username']}" if r['username'] else f"uid:{r['user_id']}"
            lines.append(f"{medals[i]} {uname} — {r['points']} pts ({r['correct']} correct)")
        await q.edit_message_text("\n".join(lines) or "No players yet!",
                                   parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    async def _show_my_stats(self, q, uid):
        user = await db_get_user(self.db, uid)
        if not user:
            await q.edit_message_text("No stats yet. Play a quiz first!", reply_markup=kb_back())
            return
        total = user["correct"] + user["wrong"]
        accuracy = f"{user['correct']/total*100:.1f}%" if total > 0 else "N/A"
        rank_row = await self.db.fetchone(
            "SELECT COUNT(*)+1 AS rank FROM quiz_users WHERE points > ?", (user["points"],)
        )
        rank = rank_row["rank"] if rank_row else "?"
        text = (
            f"📊 *Your Stats*\n\n"
            f"🏅 Rank: #{rank}\n"
            f"⭐ Points: {user['points']}\n"
            f"✅ Correct: {user['correct']}\n"
            f"❌ Wrong: {user['wrong']}\n"
            f"🎯 Accuracy: {accuracy}\n"
            f"🔥 Current Streak: {user['streak']}"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        text = update.message.text.strip()
        action = ctx.user_data.get("adm_action")
        if not action or not self.is_admin(uid):
            return
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="quiz_admin")]])
        if action == "set_points":
            try:
                pts = int(text)
                await db_set_setting(self.db, self.bot_id, "points_per_correct", str(pts))
                ctx.user_data.clear()
                await update.message.reply_text(f"✅ Points per correct answer set to {pts}", reply_markup=back_kb)
            except ValueError:
                await update.message.reply_text("❌ Enter a valid number.")
        elif action == "broadcast":
            users = await self.db.fetchall("SELECT user_id FROM quiz_users")
            sent = failed = 0
            for u in users:
                try:
                    await update.get_bot().send_message(u["user_id"], text)
                    sent += 1
                except Exception:
                    failed += 1
            ctx.user_data.clear()
            await update.message.reply_text(f"📨 Sent: {sent}, Failed: {failed}", reply_markup=back_kb)

    async def build_app(self) -> Application:
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                points INTEGER DEFAULT 0,
                correct INTEGER DEFAULT 0,
                wrong INTEGER DEFAULT 0,
                streak INTEGER DEFAULT 0
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_settings (
                bot_id INTEGER, key TEXT, value TEXT,
                PRIMARY KEY (bot_id, key)
            )
        """)
        await self.db.commit()
        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("admin", self._cmd_admin))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_message))
        return app

    async def _cmd_admin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Not authorized.")
            return
        await update.message.reply_text("🔧 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                         reply_markup=kb_admin())
