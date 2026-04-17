"""📢 Broadcast Bot"""
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from .base import BaseBotTemplate

SCHEMA_BC = """
CREATE TABLE IF NOT EXISTS bc_subs_{bid} (uid INTEGER PRIMARY KEY, username TEXT, first_name TEXT, active INTEGER DEFAULT 1, joined_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS bc_cfg_{bid} (key TEXT PRIMARY KEY, value TEXT);
"""

class BroadcastBot(BaseBotTemplate):
    TEMPLATE_ID="broadcast_bot"; TEMPLATE_NAME="Mass Broadcast Bot"
    async def build_app(self):
        with self._conn() as c:
            for s in SCHEMA_BC.replace("{bid}",str(self.bot_id)).split(";"):
                if s.strip(): c.execute(s)
            c.execute(f"INSERT OR IGNORE INTO bc_cfg_{self.bot_id}(key,value) VALUES('owner_id','0')")
        app=Application.builder().token(self.token).build(); self.register_handlers(app); return app
    def _sub(self,uid,u,f):
        with self._conn() as c: c.execute(f"INSERT INTO bc_subs_{self.bot_id}(uid,username,first_name) VALUES(?,?,?) ON CONFLICT(uid) DO UPDATE SET active=1",(uid,u,f))
    def _unsub(self,uid):
        with self._conn() as c: c.execute(f"UPDATE bc_subs_{self.bot_id} SET active=0 WHERE uid=?",(uid,))
    def _subs(self):
        with self._conn() as c: return [dict(r) for r in c.execute(f"SELECT uid FROM bc_subs_{self.bot_id} WHERE active=1")]
    def _counts(self):
        with self._conn() as c:
            t=c.execute(f"SELECT COUNT(*) FROM bc_subs_{self.bot_id}").fetchone()[0]
            a=c.execute(f"SELECT COUNT(*) FROM bc_subs_{self.bot_id} WHERE active=1").fetchone()[0]
            return t,a
    def _owner(self):
        with self._conn() as c:
            r=c.execute(f"SELECT value FROM bc_cfg_{self.bot_id} WHERE key='owner_id'").fetchone()
            return int(r[0]) if r else 0
    def _set_owner(self,uid):
        with self._conn() as c: c.execute(f"INSERT OR REPLACE INTO bc_cfg_{self.bot_id}(key,value) VALUES('owner_id',?)",(str(uid),))
    def register_handlers(self,app):
        app.add_handler(CommandHandler("start",self._start))
        app.add_handler(CommandHandler("broadcast",self._bc_cmd))
        app.add_handler(CommandHandler("stats",self._stats))
        app.add_handler(CommandHandler("subscribe",self._sub_cmd))
        app.add_handler(CommandHandler("unsubscribe",self._unsub_cmd))
        app.add_handler(CallbackQueryHandler(self._cb))
        app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,self._handle_msg))
    async def _start(self,u,ctx):
        user=u.effective_user; self._sub(user.id,user.username or "",user.first_name or "User")
        if not self._owner(): self._set_owner(user.id)
        t,a=self._counts(); is_admin=user.id==self._owner()
        msg=(f"📢 **Broadcast Bot**\n\n👋 Hi **{user.first_name}**!\n✅ You're subscribed.\n\n📊 Active: **{a}**\n{'👑 You are admin!' if is_admin else ''}")
        kb_rows=[[InlineKeyboardButton("📊 Stats",callback_data="bc_stats"),InlineKeyboardButton("🔕 Unsubscribe",callback_data="bc_unsub")]]
        if is_admin: kb_rows.insert(0,[InlineKeyboardButton("📢 Broadcast",callback_data="bc_send")])
        await u.message.reply_text(msg,reply_markup=InlineKeyboardMarkup(kb_rows),parse_mode="Markdown")
    async def _bc_cmd(self,u,ctx):
        if u.effective_user.id!=self._owner(): await u.message.reply_text("⛔ Admins only!"); return
        ctx.user_data["bc_mode"]=True; await u.message.reply_text("📢 **Broadcast Mode**\nSend your message now.",parse_mode="Markdown")
    async def _stats(self,u,ctx):
        t,a=self._counts(); await u.message.reply_text(f"📊 Total: **{t}** | Active: **{a}**",parse_mode="Markdown")
    async def _sub_cmd(self,u,ctx):
        user=u.effective_user; self._sub(user.id,user.username or "",user.first_name or "User"); await u.message.reply_text("✅ Re-subscribed!")
    async def _unsub_cmd(self,u,ctx):
        self._unsub(u.effective_user.id); await u.message.reply_text("🔕 Unsubscribed. /subscribe to rejoin.")
    async def _handle_msg(self,u,ctx):
        uid=u.effective_user.id
        if not ctx.user_data.get("bc_mode") or uid!=self._owner(): return
        ctx.user_data.pop("bc_mode",None); subs=self._subs()
        st=await u.message.reply_text(f"📤 Broadcasting to {len(subs)}...")
        sent=failed=0
        for s in subs:
            try: await ctx.bot.send_message(s["uid"],f"📢 **Broadcast:**\n\n{u.message.text}",parse_mode="Markdown"); sent+=1
            except: failed+=1
            await asyncio.sleep(0.05)
        await st.edit_text(f"✅ Done!\n📤 Sent: **{sent}** | ❌ Failed: **{failed}**",parse_mode="Markdown")
    async def _cb(self,u,ctx):
        q=u.callback_query; await q.answer(); d=q.data; uid=q.from_user.id
        if d=="bc_stats":
            t,a=self._counts(); await q.edit_message_text(f"📊 Active: **{a}** / {t}",parse_mode="Markdown")
        elif d=="bc_unsub": self._unsub(uid); await q.edit_message_text("🔕 Unsubscribed. /subscribe to rejoin.")
        elif d=="bc_send":
            if uid==self._owner(): ctx.user_data["bc_mode"]=True; await q.edit_message_text("📢 Send your message now:")
