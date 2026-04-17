"""🎯 Quiz & Trivia Bot Template"""
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, PollAnswerHandler, ContextTypes
from .base import BaseBotTemplate

SCHEMA = """CREATE TABLE IF NOT EXISTS quiz_{bid} (
    uid INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
    score INTEGER DEFAULT 0, streak INTEGER DEFAULT 0, questions INTEGER DEFAULT 0
);"""

QUESTIONS = {
    "🌍 Geography": [
        {"q":"Capital of France?","a":["Paris","Lyon","Berlin","Madrid"],"c":0},
        {"q":"Largest ocean?","a":["Atlantic","Indian","Pacific","Arctic"],"c":2},
        {"q":"Capital of Japan?","a":["Osaka","Kyoto","Tokyo","Hiroshima"],"c":2},
        {"q":"Most populated country 2024?","a":["USA","India","China","Indonesia"],"c":1},
    ],
    "🔬 Science": [
        {"q":"Closest planet to Sun?","a":["Venus","Mercury","Mars","Earth"],"c":1},
        {"q":"H2O is commonly known as?","a":["Salt","Water","Acid","Gas"],"c":1},
        {"q":"Human bones count?","a":["100","186","206","256"],"c":2},
        {"q":"Speed of light (approx)?","a":["100k km/s","300k km/s","500k km/s","1M km/s"],"c":1},
    ],
    "💻 Technology": [
        {"q":"Who founded Microsoft?","a":["Jobs","Gates","Musk","Bezos"],"c":1},
        {"q":"CPU stands for?","a":["Central Power Unit","Central Processing Unit","Core Processor Unit","Computer Process Unit"],"c":1},
        {"q":"First iPhone year?","a":["2005","2006","2007","2008"],"c":2},
    ],
    "⚽ Sports": [
        {"q":"Players in football team?","a":["9","10","11","12"],"c":2},
        {"q":"2018 FIFA World Cup winner?","a":["Brazil","Germany","France","Croatia"],"c":2},
        {"q":"Olympic pool length (m)?","a":["25","50","75","100"],"c":1},
    ],
    "🎬 Movies": [
        {"q":"Director of Titanic (1997)?","a":["Spielberg","Cameron","Nolan","Scott"],"c":1},
        {"q":"'I'll be back' movie?","a":["Rocky","Die Hard","Terminator","RoboCop"],"c":2},
        {"q":"Iron Man franchise?","a":["DC","MCU","X-Men","Transformers"],"c":1},
    ],
}

class QuizBot(BaseBotTemplate):
    TEMPLATE_ID = "quiz_bot"; TEMPLATE_NAME = "Quiz & Trivia Bot"

    async def build_app(self):
        with self._conn() as c: c.execute(SCHEMA.replace("{bid}", str(self.bot_id)))
        app = Application.builder().token(self.token).build()
        self.register_handlers(app); return app

    def t(self): return f"quiz_{self.bot_id}"

    def _upsert(self, uid, uname, fname):
        with self._conn() as c:
            c.execute(f"INSERT INTO {self.t()}(uid,username,first_name) VALUES(?,?,?) ON CONFLICT(uid) DO UPDATE SET username=excluded.username", (uid,uname,fname))

    def _get(self, uid):
        with self._conn() as c:
            r = c.execute(f"SELECT * FROM {self.t()} WHERE uid=?", (uid,)).fetchone()
            return dict(r) if r else {}

    def _update(self, uid, correct):
        with self._conn() as c:
            if correct: c.execute(f"UPDATE {self.t()} SET score=score+10,streak=streak+1,questions=questions+1 WHERE uid=?", (uid,))
            else: c.execute(f"UPDATE {self.t()} SET streak=0,questions=questions+1 WHERE uid=?", (uid,))

    def _lb(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(f"SELECT first_name,score,questions FROM {self.t()} ORDER BY score DESC LIMIT 10")]

    def register_handlers(self, app):
        app.add_handler(CommandHandler("start", self._start))
        app.add_handler(CommandHandler("quiz",  self._quiz))
        app.add_handler(CommandHandler("score", self._score))
        app.add_handler(CommandHandler("leaderboard", self._lb_cmd))
        app.add_handler(CallbackQueryHandler(self._cb))
        app.add_handler(PollAnswerHandler(self._poll_ans))

    async def _start(self, u, ctx):
        user = u.effective_user; self._upsert(user.id, user.username or "", user.first_name or "User")
        d = self._get(user.id)
        msg = (f"🎯 **Quiz & Trivia Bot**\n\n👋 Hi **{user.first_name}**!\n\n"
               f"🏆 Score: **{d['score']}** | ❓ Answered: **{d['questions']}** | 🔥 Streak: **{d['streak']}**\n\n"
               f"Categories: {', '.join(QUESTIONS.keys())}\n\n_/quiz to start!_")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Play Quiz",callback_data="quiz"),InlineKeyboardButton("📊 Score",callback_data="score")],
            [InlineKeyboardButton("🏆 Leaderboard",callback_data="lb")],
        ])
        await u.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

    async def _quiz(self, u, ctx):
        uid = u.effective_user.id; cat = random.choice(list(QUESTIONS.keys()))
        q = random.choice(QUESTIONS[cat]); ctx.user_data["cq"] = {"uid": uid, "c": q["c"]}
        await ctx.bot.send_poll(chat_id=u.effective_chat.id, question=f"{cat}\n❓ {q['q']}",
            options=q["a"], type="quiz", correct_option_id=q["c"], is_anonymous=False, open_period=15)

    async def _poll_ans(self, u, ctx):
        ans = u.poll_answer; uid = ans.user.id; sel = ans.option_ids[0] if ans.option_ids else -1
        cq  = ctx.user_data.get("cq", {}); correct = sel == cq.get("c", -2)
        self._update(uid, correct); d = self._get(uid)
        if d:
            txt = f"✅ +10pts! Streak {d['streak']} | Total {d['score']}" if correct else f"❌ Wrong! Score {d['score']}"
            try: await ctx.bot.send_message(uid, txt, parse_mode="Markdown")
            except: pass

    async def _score(self, u, ctx):
        d = self._get(u.effective_user.id)
        await u.message.reply_text(f"📊 Score: **{d.get('score',0)}** | Qs: **{d.get('questions',0)}** | Streak: **{d.get('streak',0)}**", parse_mode="Markdown")

    async def _lb_cmd(self, u, ctx):
        lb = self._lb(); medals = ["🥇","🥈","🥉"]+["🔹"]*7
        lines = ["🏆 **QUIZ LEADERBOARD**\n"] + [f"{medals[i]} {x['first_name']} — {x['score']}pts ({x['questions']}Qs)" for i,x in enumerate(lb)]
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cb(self, u, ctx):
        q = u.callback_query; await q.answer(); uid = q.from_user.id
        self._upsert(uid, q.from_user.username or "", q.from_user.first_name or "User")
        if q.data == "quiz": await q.edit_message_text("🎯 /quiz to get a poll question!"); 
        elif q.data == "score":
            d = self._get(uid); await q.edit_message_text(f"📊 {d.get('score',0)}pts | {d.get('questions',0)}Qs | 🔥{d.get('streak',0)}", parse_mode="Markdown")
        elif q.data == "lb":
            lb = self._lb(); medals = ["🥇","🥈","🥉"]+["🔹"]*7
            lines = ["🏆\n"] + [f"{medals[i]} {x['first_name']} — {x['score']}pts" for i,x in enumerate(lb)]
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown")
