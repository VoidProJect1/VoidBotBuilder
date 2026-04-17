"""🚀 Advanced Refer & Earn Bot — Multi-tier + Ranks + Daily Check-in"""
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from .base import BaseBotTemplate

SCHEMA = """
CREATE TABLE IF NOT EXISTS adv_{bid} (
    uid INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
    coins INTEGER DEFAULT 0, referrals INTEGER DEFAULT 0,
    referred_by INTEGER, rank TEXT DEFAULT 'Bronze',
    checkin_date TEXT DEFAULT '', streak INTEGER DEFAULT 0,
    joined_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS adv_shop_{bid} (
    id INTEGER PRIMARY KEY AUTOINCREMENT, item TEXT, cost INTEGER
);"""

RANKS = [("Bronze","🥉",0,10),("Silver","🥈",10,50),("Gold","🥇",50,100),("Diamond","💎",100,99999)]
MILESTONES = {10:50,25:150,50:300,100:750}
L1,L2,L3 = 15,5,2
MIN_WD = 200

def rank_of(refs):
    for n,i,lo,hi in RANKS:
        if lo <= refs < hi: return n,i
    return "Diamond","💎"

class AdvancedReferBot(BaseBotTemplate):
    TEMPLATE_ID = "adv_refer"
    TEMPLATE_NAME = "Advanced Refer & Earn"

    async def build_app(self):
        with self._conn() as c:
            for s in SCHEMA.replace("{bid}", str(self.bot_id)).split(";"):
                if s.strip(): c.execute(s)
            t = f"adv_shop_{self.bot_id}"
            if c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0:
                c.executemany(f"INSERT INTO {t}(item,cost) VALUES(?,?)",
                    [("🎁 Mystery Box",100),("📱 Recharge",500),("💳 Voucher",1000),("🏆 VIP",250)])
        app = Application.builder().token(self.token).build()
        self.register_handlers(app); return app

    def t(self): return f"adv_{self.bot_id}"

    def _upsert(self, uid, uname, fname, ref=None):
        with self._conn() as c:
            if not c.execute(f"SELECT uid FROM {self.t()} WHERE uid=?", (uid,)).fetchone():
                c.execute(f"INSERT INTO {self.t()}(uid,username,first_name,referred_by) VALUES(?,?,?,?)", (uid,uname,fname,ref))
                if ref and ref != uid:
                    c.execute(f"UPDATE {self.t()} SET coins=coins+?,referrals=referrals+1 WHERE uid=?", (L1,ref))
                    self._check_milestone(ref, c)
                    p = c.execute(f"SELECT referred_by FROM {self.t()} WHERE uid=?", (ref,)).fetchone()
                    if p and p[0]:
                        c.execute(f"UPDATE {self.t()} SET coins=coins+? WHERE uid=?", (L2, p[0]))
                        p2 = c.execute(f"SELECT referred_by FROM {self.t()} WHERE uid=?", (p[0],)).fetchone()
                        if p2 and p2[0]:
                            c.execute(f"UPDATE {self.t()} SET coins=coins+? WHERE uid=?", (L3, p2[0]))
                    self.track_ref()

    def _check_milestone(self, uid, c):
        r = c.execute(f"SELECT referrals FROM {self.t()} WHERE uid=?", (uid,)).fetchone()
        if r:
            b = MILESTONES.get(r[0], 0)
            if b: c.execute(f"UPDATE {self.t()} SET coins=coins+? WHERE uid=?", (b, uid))

    def _get(self, uid):
        with self._conn() as c:
            r = c.execute(f"SELECT * FROM {self.t()} WHERE uid=?", (uid,)).fetchone()
            return dict(r) if r else {}

    def _checkin(self, uid):
        with self._conn() as c:
            u = c.execute(f"SELECT checkin_date,streak FROM {self.t()} WHERE uid=?", (uid,)).fetchone()
            if not u: return 0,0,False
            today = date.today().isoformat()
            yest  = (date.today()-timedelta(days=1)).isoformat()
            if u[0] == today: return 0, u[1], True
            new_s = (u[1]+1) if u[0] == yest else 1
            bonus = 5 + (new_s-1)*2
            c.execute(f"UPDATE {self.t()} SET checkin_date=?,streak=?,coins=coins+? WHERE uid=?", (today,new_s,bonus,uid))
            return bonus, new_s, False

    def _lb(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(f"SELECT first_name,referrals,coins FROM {self.t()} ORDER BY referrals DESC LIMIT 10")]

    def register_handlers(self, app):
        for cmd, fn in [("start",self._start),("profile",self._profile),("refer",self._refer),
                         ("checkin",self._checkin_cmd),("leaderboard",self._lb_cmd),
                         ("shop",self._shop),("withdraw",self._withdraw)]:
            app.add_handler(CommandHandler(cmd, fn))
        app.add_handler(CallbackQueryHandler(self._cb))

    async def _start(self, u, ctx):
        user = u.effective_user
        args = ctx.args
        ref  = int(args[0]) if args and args[0].isdigit() else None
        self._upsert(user.id, user.username or "", user.first_name or "User", ref)
        d = self._get(user.id); rn, ri = rank_of(d.get("referrals",0))
        msg = (f"🚀 **Advanced Refer & Earn**\n\n👋 Hi **{user.first_name}**!\n\n"
               f"{ri} Rank: **{rn}** | 🪙 Coins: **{d.get('coins',0)}**\n"
               f"👥 Referrals: **{d.get('referrals',0)}** | 🔥 Streak: **{d.get('streak',0)}d**\n\n"
               f"L1: **{L1}c** · L2: **{L2}c** · L3: **{L3}c** per referral\n"
               f"_/checkin daily for streak bonuses!_")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Refer",callback_data="refer"),InlineKeyboardButton("👤 Profile",callback_data="profile")],
            [InlineKeyboardButton("📅 Check-in",callback_data="ci"),InlineKeyboardButton("🛒 Shop",callback_data="shop")],
            [InlineKeyboardButton("🏆 Leaderboard",callback_data="lb"),InlineKeyboardButton("💸 Withdraw",callback_data="wd")],
        ])
        await u.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

    async def _profile(self, u, ctx):
        d = self._get(u.effective_user.id); rn,ri = rank_of(d.get("referrals",0))
        await u.message.reply_text(
            f"👤 **Profile**\n\n{ri} **{rn}**\n🪙 {d.get('coins',0)} coins | 👥 {d.get('referrals',0)} refs | 🔥 {d.get('streak',0)}d streak",
            parse_mode="Markdown")

    async def _refer(self, u, ctx):
        uid = u.effective_user.id; bot = await ctx.bot.get_me()
        link = f"https://t.me/{bot.username}?start={uid}"
        await u.message.reply_text(f"🔗 **Your Link:**\n`{link}`\n\nL1:{L1}c · L2:{L2}c · L3:{L3}c per ref!", parse_mode="Markdown")

    async def _checkin_cmd(self, u, ctx):
        coins, streak, already = self._checkin(u.effective_user.id)
        if already: await u.message.reply_text("✅ Already checked in today! Come back tomorrow 🕐")
        else: await u.message.reply_text(f"✅ **Check-in!** +{coins} coins 🪙 | 🔥 {streak} day streak!", parse_mode="Markdown")

    async def _lb_cmd(self, u, ctx):
        lb = self._lb(); medals = ["🥇","🥈","🥉"]+["🔹"]*7
        lines = ["🏆 **TOP EARNERS**\n"] + [f"{medals[i]} {x['first_name']} — {x['referrals']} refs | {x['coins']}c" for i,x in enumerate(lb)]
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _shop(self, u, ctx):
        with self._conn() as c:
            items = [dict(r) for r in c.execute(f"SELECT * FROM adv_shop_{self.bot_id}")]
        lines = ["🛒 **Reward Shop**\n"] + [f"• {i['item']} — **{i['cost']} coins**" for i in items]
        lines.append("\nContact admin to redeem!")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _withdraw(self, u, ctx):
        d = self._get(u.effective_user.id)
        if d.get("coins",0) < MIN_WD:
            await u.message.reply_text(f"❌ Need {MIN_WD-d.get('coins',0)} more coins."); return
        await u.message.reply_text(f"💸 Withdrawal of **{d.get('coins',0)} coins** submitted! ✅", parse_mode="Markdown")

    async def _cb(self, u, ctx):
        q = u.callback_query; await q.answer(); d = q.data; uid = q.from_user.id
        user_d = self._get(uid); rn,ri = rank_of(user_d.get("referrals",0))
        if d == "refer":
            bot = await ctx.bot.get_me()
            link = f"https://t.me/{bot.username}?start={uid}"
            await q.edit_message_text(f"🔗 **Link:** `{link}`\nL1:{L1}c L2:{L2}c L3:{L3}c", parse_mode="Markdown")
        elif d == "profile":
            await q.edit_message_text(f"{ri} **{rn}** · 🪙{user_d.get('coins',0)} · 👥{user_d.get('referrals',0)} · 🔥{user_d.get('streak',0)}d", parse_mode="Markdown")
        elif d == "ci":
            coins, streak, already = self._checkin(uid)
            if already: await q.edit_message_text("✅ Already checked in today!")
            else: await q.edit_message_text(f"✅ +{coins} coins | 🔥 {streak}d streak!", parse_mode="Markdown")
        elif d == "shop":
            with self._conn() as c:
                items = [dict(r) for r in c.execute(f"SELECT * FROM adv_shop_{self.bot_id}")]
            lines = ["🛒 **Shop:**\n"] + [f"• {i['item']} — {i['cost']}c" for i in items]
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown")
        elif d == "lb":
            lb = self._lb(); medals = ["🥇","🥈","🥉"]+["🔹"]*7
            lines = ["🏆\n"] + [f"{medals[i]} {x['first_name']} — {x['referrals']} refs" for i,x in enumerate(lb)]
            await q.edit_message_text("\n".join(lines), parse_mode="Markdown")
        elif d == "wd":
            if user_d.get("coins",0) >= MIN_WD: await q.edit_message_text(f"💸 {user_d['coins']}c withdrawal submitted! ✅")
            else: await q.edit_message_text(f"❌ Need {MIN_WD-user_d.get('coins',0)} more.")
