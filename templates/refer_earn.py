"""🎁 Refer & Earn Bot Template"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from .base import BaseBotTemplate

SCHEMA = """
CREATE TABLE IF NOT EXISTS ref_users_{bid} (
    uid INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
    coins INTEGER DEFAULT 0, referrals INTEGER DEFAULT 0,
    referred_by INTEGER, joined_at TEXT DEFAULT (datetime('now'))
);"""
COINS_PER_REF = 10
MIN_WD = 100

class ReferEarnBot(BaseBotTemplate):
    TEMPLATE_ID = "refer_earn"
    TEMPLATE_NAME = "Refer & Earn Bot"

    async def build_app(self):
        with self._conn() as c: c.execute(SCHEMA.replace("{bid}", str(self.bot_id)))
        app = Application.builder().token(self.token).build()
        self.register_handlers(app); return app

    def t(self): return f"ref_users_{self.bot_id}"

    def _upsert(self, uid, uname, fname, ref=None):
        with self._conn() as c:
            if not c.execute(f"SELECT uid FROM {self.t()} WHERE uid=?", (uid,)).fetchone():
                c.execute(f"INSERT INTO {self.t()}(uid,username,first_name,referred_by) VALUES(?,?,?,?)", (uid,uname,fname,ref))
                if ref:
                    c.execute(f"UPDATE {self.t()} SET coins=coins+?,referrals=referrals+1 WHERE uid=?", (COINS_PER_REF, ref))
                    self.track_ref()

    def _get(self, uid):
        with self._conn() as c:
            r = c.execute(f"SELECT * FROM {self.t()} WHERE uid=?", (uid,)).fetchone()
            return dict(r) if r else {}

    def _lb(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(f"SELECT first_name,referrals,coins FROM {self.t()} ORDER BY referrals DESC LIMIT 10")]

    def register_handlers(self, app):
        app.add_handler(CommandHandler("start", self._start))
        app.add_handler(CommandHandler("balance", self._balance))
        app.add_handler(CommandHandler("refer", self._refer))
        app.add_handler(CommandHandler("leaderboard", self._lb_cmd))
        app.add_handler(CommandHandler("withdraw", self._withdraw))
        app.add_handler(CallbackQueryHandler(self._cb))

    async def _start(self, u, ctx):
        user = u.effective_user
        args = ctx.args
        ref  = int(args[0]) if args and args[0].isdigit() else None
        self._upsert(user.id, user.username or "", user.first_name or "User", ref)
        d = self._get(user.id)
        msg = (f"🎁 **Refer & Earn Bot**\n\n👋 Hi **{user.first_name}**!\n\n"
               f"🪙 Coins: **{d.get('coins',0)}**\n👥 Referrals: **{d.get('referrals',0)}**\n\n"
               f"Earn **{COINS_PER_REF} coins** per referral!\nMin withdrawal: **{MIN_WD} coins**")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 My Referral Link", callback_data="get_link"),
             InlineKeyboardButton("💰 Balance",           callback_data="balance")],
            [InlineKeyboardButton("🏆 Leaderboard",       callback_data="lb"),
             InlineKeyboardButton("💸 Withdraw",          callback_data="withdraw")],
        ])
        await u.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

    async def _balance(self, u, ctx):
        d = self._get(u.effective_user.id)
        await u.message.reply_text(f"💰 **Balance:** {d.get('coins',0)} coins\n👥 **Referrals:** {d.get('referrals',0)}", parse_mode="Markdown")

    async def _refer(self, u, ctx):
        uid  = u.effective_user.id
        bot  = await ctx.bot.get_me()
        link = f"https://t.me/{bot.username}?start={uid}"
        await u.message.reply_text(f"🔗 **Your Link:**\n`{link}`\n\nEarn **{COINS_PER_REF} coins** per friend!", parse_mode="Markdown")

    async def _lb_cmd(self, u, ctx):
        lb = self._lb()
        medals = ["🥇","🥈","🥉"]+["🔹"]*7
        lines = ["🏆 **TOP REFERRERS**\n"] + [f"{medals[i]} {x['first_name']} — {x['referrals']} refs | {x['coins']}c" for i,x in enumerate(lb)]
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _withdraw(self, u, ctx):
        d = self._get(u.effective_user.id)
        if d.get("coins",0) < MIN_WD:
            await u.message.reply_text(f"❌ Need **{MIN_WD-d.get('coins',0)}** more coins.", parse_mode="Markdown"); return
        await u.message.reply_text(f"💸 Withdrawal of **{d.get('coins',0)}** coins requested! Admin will process. ✅", parse_mode="Markdown")

    async def _cb(self, u, ctx):
        q = u.callback_query; await q.answer()
        d_map = {"get_link": self._refer_cb, "balance": self._balance_cb, "lb": self._lb_cb, "withdraw": self._wd_cb}
        if q.data in d_map: await d_map[q.data](q, ctx)

    async def _refer_cb(self, q, ctx):
        uid = q.from_user.id; bot = await ctx.bot.get_me()
        link = f"https://t.me/{bot.username}?start={uid}"
        await q.edit_message_text(f"🔗 **Your Link:**\n`{link}`\n\nEarn {COINS_PER_REF} coins/friend!", parse_mode="Markdown")

    async def _balance_cb(self, q, ctx):
        d = self._get(q.from_user.id)
        await q.edit_message_text(f"💰 **Coins:** {d.get('coins',0)}\n👥 **Referrals:** {d.get('referrals',0)}", parse_mode="Markdown")

    async def _lb_cb(self, q, ctx):
        lb = self._lb(); medals = ["🥇","🥈","🥉"]+["🔹"]*7
        lines = ["🏆 **Leaderboard**\n"] + [f"{medals[i]} {x['first_name']} — {x['referrals']} refs" for i,x in enumerate(lb)]
        await q.edit_message_text("\n".join(lines), parse_mode="Markdown")

    async def _wd_cb(self, q, ctx):
        d = self._get(q.from_user.id)
        if d.get("coins",0) >= MIN_WD:
            await q.edit_message_text(f"💸 Withdrawal of {d['coins']} coins submitted! ✅")
        else:
            await q.edit_message_text(f"❌ Need {MIN_WD-d.get('coins',0)} more coins.")
