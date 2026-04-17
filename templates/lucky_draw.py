"""
🎰 LUCKY DRAW & LOTTERY BOT
Ticket-based giveaways with fair random draw.
"""
import random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from .base import BaseBotTemplate

SCHEMA = """
CREATE TABLE IF NOT EXISTS ld_users_{bid} (uid INTEGER PRIMARY KEY, username TEXT, first_name TEXT, tickets INTEGER DEFAULT 0, wins INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ld_draws_{bid} (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, prize TEXT,
    ticket_cost INTEGER DEFAULT 0, max_tickets INTEGER DEFAULT 100,
    status TEXT DEFAULT 'open', winner_uid INTEGER DEFAULT 0,
    winner_name TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ld_entries_{bid} (id INTEGER PRIMARY KEY AUTOINCREMENT, draw_id INTEGER, uid INTEGER, tickets INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS ld_cfg_{bid} (key TEXT PRIMARY KEY, value TEXT);
"""

class LuckyDrawBot(BaseBotTemplate):
    TEMPLATE_ID="lucky_draw"; TEMPLATE_NAME="Lucky Draw & Lottery Bot"

    async def build_app(self):
        with self._conn() as c:
            for s in SCHEMA.replace("{bid}",str(self.bot_id)).split(";"):
                if s.strip(): c.execute(s)
            c.execute(f"INSERT OR IGNORE INTO ld_cfg_{self.bot_id}(key,value) VALUES('owner_id','0')")
        app=Application.builder().token(self.token).build(); self.register_handlers(app); return app

    def _owner(self):
        with self._conn() as c:
            r=c.execute(f"SELECT value FROM ld_cfg_{self.bot_id} WHERE key='owner_id'").fetchone()
            return int(r[0]) if r else 0

    def _upsert(self,uid,uname,fname):
        with self._conn() as c:
            c.execute(f"INSERT INTO ld_users_{self.bot_id}(uid,username,first_name) VALUES(?,?,?) ON CONFLICT(uid) DO UPDATE SET username=excluded.username",(uid,uname,fname))

    def _get_user(self,uid):
        with self._conn() as c:
            r=c.execute(f"SELECT * FROM ld_users_{self.bot_id} WHERE uid=?",(uid,)).fetchone()
            return dict(r) if r else {}

    def _active_draw(self):
        with self._conn() as c:
            r=c.execute(f"SELECT * FROM ld_draws_{self.bot_id} WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
            return dict(r) if r else None

    def _entry_count(self,draw_id):
        with self._conn() as c:
            return c.execute(f"SELECT SUM(tickets) FROM ld_entries_{self.bot_id} WHERE draw_id=?",(draw_id,)).fetchone()[0] or 0

    def _participants(self,draw_id):
        with self._conn() as c:
            return c.execute(f"SELECT COUNT(DISTINCT uid) FROM ld_entries_{self.bot_id} WHERE draw_id=?",(draw_id,)).fetchone()[0] or 0

    def _user_entries(self,draw_id,uid):
        with self._conn() as c:
            return c.execute(f"SELECT COALESCE(SUM(tickets),0) FROM ld_entries_{self.bot_id} WHERE draw_id=? AND uid=?",(draw_id,uid)).fetchone()[0] or 0

    def _enter_draw(self,draw_id,uid):
        with self._conn() as c:
            c.execute(f"INSERT INTO ld_entries_{self.bot_id}(draw_id,uid,tickets) VALUES(?,?,1)",(draw_id,uid))
            c.execute(f"UPDATE ld_users_{self.bot_id} SET tickets=tickets+1 WHERE uid=?",(uid,))

    def _do_draw(self,draw_id):
        with self._conn() as c:
            entries=c.execute(f"SELECT uid FROM ld_entries_{self.bot_id} WHERE draw_id=?",(draw_id,)).fetchall()
            if not entries: return None,None
            pool=[e[0] for e in entries]
            winner_uid=random.choice(pool)
            u=c.execute(f"SELECT first_name FROM ld_users_{self.bot_id} WHERE uid=?",(winner_uid,)).fetchone()
            winner_name=u[0] if u else "Unknown"
            c.execute(f"UPDATE ld_draws_{self.bot_id} SET status='completed',winner_uid=?,winner_name=? WHERE id=?",(winner_uid,winner_name,draw_id))
            c.execute(f"UPDATE ld_users_{self.bot_id} SET wins=wins+1 WHERE uid=?",(winner_uid,))
            return winner_uid, winner_name

    def _get_all_uids(self):
        with self._conn() as c:
            return [r[0] for r in c.execute(f"SELECT uid FROM ld_users_{self.bot_id}")]

    def register_handlers(self,app):
        app.add_handler(CommandHandler("start",self._start))
        app.add_handler(CommandHandler("enter",self._enter))
        app.add_handler(CommandHandler("status",self._status))
        app.add_handler(CommandHandler("history",self._history))
        app.add_handler(CommandHandler("newdraw",self._new_draw))
        app.add_handler(CommandHandler("pickcmd",self._pick_winner))
        app.add_handler(CallbackQueryHandler(self._cb))

    async def _start(self,u,ctx):
        user=u.effective_user; self._upsert(user.id,user.username or "",user.first_name or "User")
        if not self._owner():
            with self._conn() as c: c.execute(f"INSERT OR REPLACE INTO ld_cfg_{self.bot_id}(key,value) VALUES('owner_id',?)",(str(user.id),))
        d=self._get_user(user.id); draw=self._active_draw()
        draw_txt=f"\n\n🎰 **Active Draw:** {draw['title']}\n🏆 Prize: **{draw['prize']}**\n👥 Participants: {self._participants(draw['id'])}" if draw else "\n\n_No active draw right now._"
        msg=(f"🎰 **LUCKY DRAW BOT**\n\n👋 Hi **{user.first_name}**!\n\n"
             f"🎟️ Your Tickets: **{d.get('tickets',0)}**\n🏆 Wins: **{d.get('wins',0)}**{draw_txt}")
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎟️ Enter Draw",callback_data="enter"),InlineKeyboardButton("📊 Status",callback_data="status")],
            [InlineKeyboardButton("📜 History",callback_data="history")],
        ])
        await u.message.reply_text(msg,reply_markup=kb,parse_mode="Markdown")

    async def _enter(self,u,ctx):
        uid=u.effective_user.id; draw=self._active_draw()
        if not draw: await u.message.reply_text("❌ No active draw right now!"); return
        existing=self._user_entries(draw["id"],uid)
        if existing > 0: await u.message.reply_text(f"✅ Already entered!\nYour tickets: {existing}"); return
        self._enter_draw(draw["id"],uid)
        cnt=self._participants(draw["id"])
        await u.message.reply_text(f"🎊 **You're In!**\n\n🎰 Draw: **{draw['title']}**\n🏆 Prize: **{draw['prize']}**\n👥 Total Participants: **{cnt}**\n\nGood luck! 🍀",parse_mode="Markdown")

    async def _status(self,u,ctx):
        draw=self._active_draw()
        if not draw: await u.message.reply_text("📭 No active draw."); return
        cnt=self._participants(draw["id"]); tickets=self._entry_count(draw["id"])
        uid=u.effective_user.id; my=self._user_entries(draw["id"],uid)
        msg=(f"📊 **DRAW STATUS**\n\n🎰 **{draw['title']}**\n🏆 Prize: **{draw['prize']}**\n\n"
             f"👥 Participants: **{cnt}**\n🎟️ Total Tickets: **{tickets}**\n"
             f"🎫 Your Tickets: **{my}**\n\n{'✅ You are entered!' if my else '❌ Not entered yet'}")
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("🎟️ Enter Now",callback_data="enter")]]) if not my else None
        await u.message.reply_text(msg,reply_markup=kb,parse_mode="Markdown")

    async def _history(self,u,ctx):
        with self._conn() as c:
            rows=[dict(r) for r in c.execute(f"SELECT * FROM ld_draws_{self.bot_id} WHERE status='completed' ORDER BY id DESC LIMIT 10")]
        if not rows: await u.message.reply_text("📭 No completed draws yet."); return
        lines=["📜 **DRAW HISTORY**\n"]
        for r in rows: lines.append(f"🏆 {r['title']}\n   Winner: **{r['winner_name']}** | Prize: {r['prize']}")
        await u.message.reply_text("\n".join(lines),parse_mode="Markdown")

    async def _new_draw(self,u,ctx):
        if u.effective_user.id!=self._owner(): await u.message.reply_text("⛔ Admin only!"); return
        args=ctx.args
        if len(args)<2: await u.message.reply_text("Usage: /newdraw <Title> | <Prize>\nE.g: /newdraw Weekly Giveaway | 5 USDT"); return
        full=" ".join(args); parts=full.split("|")
        if len(parts)<2: await u.message.reply_text("Usage: /newdraw Title | Prize"); return
        title=parts[0].strip(); prize=parts[1].strip()
        with self._conn() as c: c.execute(f"INSERT INTO ld_draws_{self.bot_id}(title,prize) VALUES(?,?)",(title,prize))
        await u.message.reply_text(f"🎰 **New Draw Created!**\n\n📛 Title: **{title}**\n🏆 Prize: **{prize}**\n\n/pickcmd to draw winner anytime!",parse_mode="Markdown")

    async def _pick_winner(self,u,ctx):
        if u.effective_user.id!=self._owner(): await u.message.reply_text("⛔ Admin only!"); return
        draw=self._active_draw()
        if not draw: await u.message.reply_text("❌ No active draw!"); return
        cnt=self._participants(draw["id"])
        if cnt==0: await u.message.reply_text("❌ No participants!"); return
        await u.message.reply_text("🎲 Drawing winner...")
        w_uid, w_name=self._do_draw(draw["id"])
        msg=(f"🎊 **WINNER ANNOUNCED!**\n\n{'🥁'*5}\n\n"
             f"🏆 Draw: **{draw['title']}**\n"
             f"🎁 Prize: **{draw['prize']}**\n"
             f"🥇 **WINNER: {w_name}**\n\n"
             f"Congratulations! 🎉")
        all_uids=self._get_all_uids()
        await u.message.reply_text(msg,parse_mode="Markdown")
        for uid in all_uids:
            try: await ctx.bot.send_message(uid,msg,parse_mode="Markdown")
            except: pass

    async def _cb(self,u,ctx):
        q=u.callback_query; await q.answer(); uid=q.from_user.id
        self._upsert(uid,q.from_user.username or "",q.from_user.first_name or "User")
        if q.data=="enter":
            draw=self._active_draw()
            if not draw: await q.edit_message_text("❌ No active draw!"); return
            if self._user_entries(draw["id"],uid): await q.answer("Already entered!",show_alert=True); return
            self._enter_draw(draw["id"],uid)
            await q.edit_message_text(f"🎊 Entered! **{draw['title']}**\nGood luck! 🍀",parse_mode="Markdown")
        elif q.data=="status":
            draw=self._active_draw()
            if not draw: await q.edit_message_text("📭 No active draw."); return
            cnt=self._participants(draw["id"])
            await q.edit_message_text(f"📊 **{draw['title']}**\n🏆 {draw['prize']}\n👥 {cnt} participants",parse_mode="Markdown")
        elif q.data=="history":
            with self._conn() as c:
                rows=[dict(r) for r in c.execute(f"SELECT * FROM ld_draws_{self.bot_id} WHERE status='completed' ORDER BY id DESC LIMIT 5")]
            if not rows: await q.edit_message_text("📭 No history yet."); return
            lines=["📜 **History:**\n"]+[f"🏆 {r['title']} → {r['winner_name']}" for r in rows]
            await q.edit_message_text("\n".join(lines),parse_mode="Markdown")
