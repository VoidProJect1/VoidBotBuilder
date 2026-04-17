"""
💎 POLYGON AUTO PAY BOT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Crypto-based referral earnings in MATIC/POL.
Features reply keyboard just like screenshot.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sqlite3
import re
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from .base import BaseBotTemplate

# ── Schema ─────────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS pol_users_{bid} (
    uid           INTEGER PRIMARY KEY,
    username      TEXT,
    first_name    TEXT,
    wallet        TEXT DEFAULT '',
    balance       REAL DEFAULT 0.0,
    total_earned  REAL DEFAULT 0.0,
    referrals     INTEGER DEFAULT 0,
    referred_by   INTEGER DEFAULT 0,
    joined_at     TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS pol_channels_{bid} (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS pol_config_{bid} (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS pol_withdrawals_{bid} (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        INTEGER,
    wallet     TEXT,
    amount     REAL,
    status     TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);
"""

MATIC_PER_REF = 0.1        # MATIC per successful referral
MIN_WITHDRAW  = 1.0        # minimum MATIC to withdraw


# ── Reply Keyboard (like screenshot) ──────────────────────────────────────────
def main_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton("💸 Withdraw"),     KeyboardButton("🎁 Refer & Earn")],
            [KeyboardButton("👛 Set POL Wallet"), KeyboardButton("💰 Balance")],
            [KeyboardButton("📊 Stats"),          KeyboardButton("🆘 Help")],
            [KeyboardButton("✨ Features")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )


class PolygonPayBot(BaseBotTemplate):
    TEMPLATE_ID   = "polygon_pay"
    TEMPLATE_NAME = "Polygon Auto Pay Bot"

    async def build_app(self):
        self._init_db()
        app = Application.builder().token(self.token).build()
        self.register_handlers(app)
        return app

    def _init_db(self):
        with self._conn() as c:
            for s in SCHEMA.replace("{bid}", str(self.bot_id)).split(";"):
                if s.strip(): c.execute(s)
            # Default config
            c.execute(f"INSERT OR IGNORE INTO pol_config_{self.bot_id}(key,value) VALUES('owner_id','0')")
            c.execute(f"INSERT OR IGNORE INTO pol_config_{self.bot_id}(key,value) VALUES('matic_per_ref','{MATIC_PER_REF}')")
            c.execute(f"INSERT OR IGNORE INTO pol_config_{self.bot_id}(key,value) VALUES('min_withdraw','{MIN_WITHDRAW}')")

    def t(self, tbl): return f"pol_{tbl}_{self.bot_id}"

    def _cfg(self, key, default="") -> str:
        with self._conn() as c:
            r = c.execute(f"SELECT value FROM {self.t('config')} WHERE key=?", (key,)).fetchone()
            return r[0] if r else default

    def _set_cfg(self, key, val):
        with self._conn() as c:
            c.execute(f"INSERT OR REPLACE INTO {self.t('config')}(key,value) VALUES(?,?)", (key, val))

    def _upsert_user(self, uid, uname, fname, ref_by=0):
        with self._conn() as c:
            existing = c.execute(f"SELECT uid FROM {self.t('users')} WHERE uid=?", (uid,)).fetchone()
            if not existing:
                c.execute(
                    f"INSERT INTO {self.t('users')}(uid,username,first_name,referred_by) VALUES(?,?,?,?)",
                    (uid, uname, fname, ref_by)
                )
                if ref_by and ref_by != uid:
                    rate = float(self._cfg("matic_per_ref", str(MATIC_PER_REF)))
                    c.execute(
                        f"UPDATE {self.t('users')} SET balance=balance+?, total_earned=total_earned+?, referrals=referrals+1 WHERE uid=?",
                        (rate, rate, ref_by)
                    )
                    self.track_ref()
                self.track_user()

    def _get_user(self, uid) -> dict:
        with self._conn() as c:
            r = c.execute(f"SELECT * FROM {self.t('users')} WHERE uid=?", (uid,)).fetchone()
            return dict(r) if r else {}

    def _get_channels(self) -> list:
        with self._conn() as c:
            return [r[0] for r in c.execute(f"SELECT channel FROM {self.t('channels')}")]

    def _get_owner(self) -> int:
        return int(self._cfg("owner_id", "0"))

    def _set_owner(self, uid: int):
        self._set_cfg("owner_id", str(uid))

    def _leaderboard(self):
        with self._conn() as c:
            return [dict(r) for r in c.execute(
                f"SELECT first_name, referrals, total_earned FROM {self.t('users')} ORDER BY referrals DESC LIMIT 10"
            )]

    def _get_stats(self):
        with self._conn() as c:
            total_users   = c.execute(f"SELECT COUNT(*) FROM {self.t('users')}").fetchone()[0]
            total_refs    = c.execute(f"SELECT SUM(referrals) FROM {self.t('users')}").fetchone()[0] or 0
            total_earned  = c.execute(f"SELECT SUM(total_earned) FROM {self.t('users')}").fetchone()[0] or 0
            pending_wds   = c.execute(f"SELECT COUNT(*) FROM {self.t('withdrawals')} WHERE status='pending'").fetchone()[0]
            return total_users, total_refs, round(total_earned, 4), pending_wds

    async def _check_joined(self, ctx, uid: int) -> bool:
        """Check if user has joined all required channels."""
        channels = self._get_channels()
        if not channels: return True
        for ch in channels:
            try:
                member = await ctx.bot.get_chat_member(ch, uid)
                if member.status in ["left", "kicked"]:
                    return False
            except Exception:
                pass
        return True

    def register_handlers(self, app: Application):
        app.add_handler(CommandHandler("start",      self._start))
        app.add_handler(CommandHandler("admin",      self._admin_panel))
        app.add_handler(CommandHandler("addchannel", self._add_channel))
        app.add_handler(CommandHandler("setrate",    self._set_rate))
        app.add_handler(CallbackQueryHandler(self._cb))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))

    # ── /start ─────────────────────────────────────────────────────────────────
    async def _start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        args = ctx.args
        ref  = int(args[0]) if args and args[0].isdigit() and int(args[0]) != user.id else 0

        # Set first user as owner
        if not self._get_owner():
            self._set_owner(user.id)

        # Force join check
        channels = self._get_channels()
        if channels:
            joined = await self._check_joined(ctx, user.id)
            if not joined:
                ch_links = "\n".join([f"🔗 @{ch.lstrip('@')}" for ch in channels])
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Join Channel", url=f"https://t.me/{channels[0].lstrip('@')}")],
                    [InlineKeyboardButton("✅ Joined All", callback_data="check_joined")],
                ])
                await update.message.reply_text(
                    f"🔒 **Join All Channels to Unlock Menu:**\n\n"
                    f"{ch_links}\n\n"
                    f"After joining all, tap ✅ **Joined All**.",
                    reply_markup=kb, parse_mode="Markdown"
                )
                ctx.user_data["pending_ref"] = ref
                return

        self._upsert_user(user.id, user.username or "", user.first_name or "User", ref)
        u = self._get_user(user.id)

        ref_note = ""
        if ref and u.get("referred_by") == ref:
            rate = float(self._cfg("matic_per_ref", str(MATIC_PER_REF)))
            ref_note = f"\n\n🎊 You were referred! Your referrer earned **{rate} MATIC**!"

        msg = (
            f"💎 **POLYGON AUTO PAY BOT**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👋 Welcome, **{user.first_name}**!{ref_note}\n\n"
            f"💰 Balance:      **{u.get('balance',0):.4f} MATIC**\n"
            f"🏆 Total Earned: **{u.get('total_earned',0):.4f} MATIC**\n"
            f"👥 Referrals:    **{u.get('referrals',0)}**\n"
            f"👛 Wallet:       {'✅ Set' if u.get('wallet') else '❌ Not Set'}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Earn **{self._cfg('matic_per_ref', str(MATIC_PER_REF))} MATIC** per referral!\n"
            f"Min withdrawal: **{self._cfg('min_withdraw', str(MIN_WITHDRAW))} MATIC**"
        )
        await update.message.reply_text(msg, reply_markup=main_reply_kb(), parse_mode="Markdown")

    # ── Text Router (Reply Keyboard) ────────────────────────────────────────────
    async def _handle_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        uid  = update.effective_user.id

        if ctx.user_data.get("awaiting_wallet"):
            await self._process_wallet(update, ctx)
            return

        if text == "💸 Withdraw":       await self._withdraw(update, ctx)
        elif text == "🎁 Refer & Earn": await self._refer(update, ctx)
        elif text == "👛 Set POL Wallet": await self._ask_wallet(update, ctx)
        elif text == "💰 Balance":       await self._balance(update, ctx)
        elif text == "📊 Stats":         await self._stats(update, ctx)
        elif text == "🆘 Help":          await self._help(update, ctx)
        elif text == "✨ Features":      await self._features(update, ctx)
        else: pass

    # ── Callback Handler ────────────────────────────────────────────────────────
    async def _cb(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        d = q.data
        uid = q.from_user.id

        if d == "check_joined":
            joined = await self._check_joined(ctx, uid)
            if joined:
                ref = ctx.user_data.pop("pending_ref", 0)
                self._upsert_user(uid, q.from_user.username or "", q.from_user.first_name or "User", ref)
                u = self._get_user(uid)
                await q.edit_message_text(
                    f"✅ **Joined All!** Menu unlocked 🎉\n\n"
                    f"💰 Balance: **{u.get('balance',0):.4f} MATIC**",
                    parse_mode="Markdown"
                )
                await ctx.bot.send_message(uid, "🎉 Welcome! Use the menu below 👇", reply_markup=main_reply_kb())
            else:
                await q.answer("❌ You haven't joined all channels!", show_alert=True)

        elif d == "withdraw_confirm":
            await self._process_withdraw(update, ctx)

        elif d.startswith("admin_approve_"):
            wid = int(d[14:])
            await self._approve_withdraw(update, ctx, wid)

        elif d.startswith("admin_reject_"):
            wid = int(d[13:])
            await self._reject_withdraw(update, ctx, wid)

    # ── Features ────────────────────────────────────────────────────────────────
    async def _features(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        msg = (
            "✨ **POLYGON AUTO PAY BOT — FEATURES**\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💎 **Crypto Earnings**\n"
            f"  Earn real MATIC on Polygon network\n"
            f"  {self._cfg('matic_per_ref', str(MATIC_PER_REF))} MATIC per referral\n\n"
            "🔗 **Referral System**\n"
            "  Share your unique link\n"
            "  Unlimited referrals\n\n"
            "👛 **Polygon Wallet**\n"
            "  Set your POL wallet once\n"
            f"  Min withdrawal: {self._cfg('min_withdraw', str(MIN_WITHDRAW))} MATIC\n\n"
            "🔒 **Force-Join Protection**\n"
            "  Admin can set required channels\n\n"
            "📊 **Live Statistics**\n"
            "  Real-time earnings & referral data\n\n"
            "🏆 **Leaderboard**\n"
            "  Compete for top referrer spot\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    # ── Balance ──────────────────────────────────────────────────────────────────
    async def _balance(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        u = self._get_user(update.effective_user.id)
        if not u:
            await update.message.reply_text("Please /start first!")
            return
        min_wd = float(self._cfg("min_withdraw", str(MIN_WITHDRAW)))
        bal    = u.get("balance", 0)
        can_wd = bal >= min_wd

        msg = (
            f"💰 **YOUR BALANCE**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 Current Balance:  **{bal:.4f} MATIC**\n"
            f"📈 Total Earned:      **{u.get('total_earned',0):.4f} MATIC**\n"
            f"👥 Referrals:          **{u.get('referrals',0)}**\n"
            f"👛 Wallet:              {'✅ ' + u['wallet'][:12] + '...' if u.get('wallet') else '❌ Not Set'}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{'✅ You can withdraw!' if can_wd else f'❌ Need {min_wd - bal:.4f} more MATIC'}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    # ── Refer ────────────────────────────────────────────────────────────────────
    async def _refer(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid  = update.effective_user.id
        bot  = await ctx.bot.get_me()
        link = f"https://t.me/{bot.username}?start={uid}"
        u    = self._get_user(uid)
        rate = self._cfg("matic_per_ref", str(MATIC_PER_REF))

        # Leaderboard
        lb      = self._leaderboard()
        medals  = ["🥇","🥈","🥉","4️⃣","5️⃣"]
        lb_text = "\n".join([f"  {medals[i]} {u2['first_name']} — {u2['referrals']} refs ({u2['total_earned']:.3f} MATIC)"
                              for i, u2 in enumerate(lb[:5])])

        msg = (
            f"🎁 **REFER & EARN**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 **Your Link:**\n`{link}`\n\n"
            f"💰 Earn **{rate} MATIC** per referral\n"
            f"👥 Your referrals: **{u.get('referrals',0)}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏆 **Leaderboard:**\n{lb_text or '  No referrals yet. Be first!'}"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    # ── Wallet ────────────────────────────────────────────────────────────────────
    async def _ask_wallet(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        ctx.user_data["awaiting_wallet"] = True
        u = self._get_user(update.effective_user.id)
        current = u.get("wallet", "") if u else ""
        msg = (
            f"👛 **SET POLYGON WALLET**\n\n"
            f"{'Current: `' + current + '`' if current else 'No wallet set yet.'}\n\n"
            f"Send your **Polygon (POL) wallet address:**\n"
            f"_(Starts with 0x, 42 characters)_"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _process_wallet(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        ctx.user_data.pop("awaiting_wallet", None)
        wallet = update.message.text.strip()
        if not (wallet.startswith("0x") and len(wallet) == 42):
            await update.message.reply_text(
                "❌ Invalid address!\nMust start with `0x` and be 42 characters.",
                parse_mode="Markdown"
            )
            return
        uid = update.effective_user.id
        with self._conn() as c:
            c.execute(f"UPDATE {self.t('users')} SET wallet=? WHERE uid=?", (wallet, uid))
        await update.message.reply_text(
            f"✅ **Wallet Set!**\n\n`{wallet}`\n\nYou can now request withdrawals! 💸",
            parse_mode="Markdown"
        )

    # ── Withdraw ──────────────────────────────────────────────────────────────────
    async def _withdraw(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        u      = self._get_user(update.effective_user.id)
        if not u:
            await update.message.reply_text("Please /start first!")
            return
        min_wd = float(self._cfg("min_withdraw", str(MIN_WITHDRAW)))
        bal    = u.get("balance", 0)
        wallet = u.get("wallet", "")

        if not wallet:
            await update.message.reply_text(
                "❌ **No Wallet Set!**\n\nSet your Polygon wallet first by tapping 👛 Set POL Wallet",
                parse_mode="Markdown"
            )
            return
        if bal < min_wd:
            await update.message.reply_text(
                f"❌ **Insufficient Balance!**\n\n"
                f"Balance: **{bal:.4f} MATIC**\n"
                f"Required: **{min_wd:.4f} MATIC**\n"
                f"Need: **{min_wd - bal:.4f} more MATIC**",
                parse_mode="Markdown"
            )
            return

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Confirm Withdrawal", callback_data="withdraw_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel_wd"),
        ]])
        await update.message.reply_text(
            f"💸 **WITHDRAWAL REQUEST**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Amount:  **{bal:.4f} MATIC**\n"
            f"👛 Wallet:   `{wallet}`\n"
            f"🔗 Network: Polygon (MATIC)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Confirm to submit request to admin.",
            reply_markup=kb, parse_mode="Markdown"
        )

    async def _process_withdraw(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q   = update.callback_query
        uid = q.from_user.id
        u   = self._get_user(uid)
        if not u: return

        bal    = u.get("balance", 0)
        wallet = u.get("wallet", "")
        min_wd = float(self._cfg("min_withdraw", str(MIN_WITHDRAW)))

        if bal < min_wd or not wallet:
            await q.answer("❌ Cannot process!", show_alert=True)
            return

        with self._conn() as c:
            cur = c.execute(
                f"INSERT INTO {self.t('withdrawals')}(uid, wallet, amount) VALUES(?,?,?)",
                (uid, wallet, bal)
            )
            wid = cur.lastrowid
            c.execute(f"UPDATE {self.t('users')} SET balance=0 WHERE uid=?", (uid,))

        self.track_tx()
        await q.edit_message_text(
            f"✅ **Withdrawal Submitted!**\n\n"
            f"💰 Amount: **{bal:.4f} MATIC**\n"
            f"👛 Wallet: `{wallet}`\n"
            f"🆔 Request ID: #{wid}\n\n"
            f"Admin will process soon. Check back!",
            parse_mode="Markdown"
        )

        # Notify admin
        owner = self._get_owner()
        if owner:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"admin_approve_{wid}"),
                InlineKeyboardButton("❌ Reject",  callback_data=f"admin_reject_{wid}"),
            ]])
            try:
                await ctx.bot.send_message(
                    owner,
                    f"🔔 **New Withdrawal Request #{wid}**\n\n"
                    f"👤 User: @{u.get('username','?')} (ID: {uid})\n"
                    f"💰 Amount: **{bal:.4f} MATIC**\n"
                    f"👛 Wallet: `{wallet}`",
                    reply_markup=kb, parse_mode="Markdown"
                )
            except Exception: pass

    async def _approve_withdraw(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, wid: int):
        q = update.callback_query
        with self._conn() as c:
            r = c.execute(f"SELECT * FROM {self.t('withdrawals')} WHERE id=?", (wid,)).fetchone()
            if not r:
                await q.answer("Not found!", show_alert=True); return
            wd = dict(r)
            c.execute(f"UPDATE {self.t('withdrawals')} SET status='approved' WHERE id=?", (wid,))
        await q.edit_message_text(
            f"✅ Withdrawal #{wid} approved!\n💰 {wd['amount']:.4f} MATIC → `{wd['wallet']}`",
            parse_mode="Markdown"
        )
        try:
            await ctx.bot.send_message(
                wd["uid"],
                f"🎉 **Withdrawal Approved!**\n💰 {wd['amount']:.4f} MATIC sent to:\n`{wd['wallet']}`",
                parse_mode="Markdown"
            )
        except: pass

    async def _reject_withdraw(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, wid: int):
        q = update.callback_query
        with self._conn() as c:
            r = c.execute(f"SELECT * FROM {self.t('withdrawals')} WHERE id=?", (wid,)).fetchone()
            if not r: return
            wd = dict(r)
            c.execute(f"UPDATE {self.t('withdrawals')} SET status='rejected' WHERE id=?", (wid,))
            # Refund balance
            c.execute(f"UPDATE {self.t('users')} SET balance=balance+? WHERE uid=?", (wd["amount"], wd["uid"]))
        await q.edit_message_text(f"❌ Withdrawal #{wid} rejected. Balance refunded.", parse_mode="Markdown")

    # ── Stats ──────────────────────────────────────────────────────────────────────
    async def _stats(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        tu, tr, te, pw = self._get_stats()
        rate = self._cfg("matic_per_ref", str(MATIC_PER_REF))
        msg  = (
            f"📊 **BOT STATISTICS**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Total Users:         **{tu}**\n"
            f"🔗 Total Referrals:     **{tr}**\n"
            f"💰 Total MATIC Earned: **{te:.4f}**\n"
            f"⏳ Pending Withdrawals: **{pw}**\n"
            f"💎 Rate/Referral:        **{rate} MATIC**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    # ── Help ────────────────────────────────────────────────────────────────────────
    async def _help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        min_wd = self._cfg("min_withdraw", str(MIN_WITHDRAW))
        rate   = self._cfg("matic_per_ref", str(MATIC_PER_REF))
        msg = (
            f"🆘 **HELP & GUIDE**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💸 **Withdraw** — Request payout\n"
            f"🎁 **Refer & Earn** — Get your link + leaderboard\n"
            f"👛 **Set POL Wallet** — Set your Polygon address\n"
            f"💰 **Balance** — View your earnings\n"
            f"📊 **Stats** — Bot-wide stats\n"
            f"✨ **Features** — All bot features\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 **How to Earn:**\n"
            f"1️⃣ Tap 🎁 Refer & Earn\n"
            f"2️⃣ Share your unique link\n"
            f"3️⃣ Earn **{rate} MATIC** per friend\n"
            f"4️⃣ Set wallet → Withdraw when ≥{min_wd} MATIC\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    # ── Admin ────────────────────────────────────────────────────────────────────────
    async def _admin_panel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if uid != self._get_owner():
            await update.message.reply_text("⛔ Admins only!")
            return
        tu, tr, te, pw = self._get_stats()
        channels       = self._get_channels()
        rate           = self._cfg("matic_per_ref", str(MATIC_PER_REF))
        min_wd         = self._cfg("min_withdraw", str(MIN_WITHDRAW))
        msg = (
            f"👑 **ADMIN PANEL**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Users:            {tu}\n"
            f"🔗 Referrals:        {tr}\n"
            f"💰 Earned:           {te:.4f} MATIC\n"
            f"⏳ Pending WDs:      {pw}\n"
            f"💎 Rate/Ref:          {rate} MATIC\n"
            f"💸 Min Withdraw:    {min_wd} MATIC\n"
            f"📢 Channels:         {len(channels)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"**Commands:**\n"
            f"/addchannel @username — Add force-join channel\n"
            f"/setrate 0.1 — Set MATIC per referral\n"
        )
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def _add_channel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if uid != self._get_owner():
            await update.message.reply_text("⛔ Admins only!")
            return
        if not ctx.args:
            await update.message.reply_text("Usage: /addchannel @channel")
            return
        ch = ctx.args[0] if ctx.args[0].startswith("@") else "@" + ctx.args[0]
        with self._conn() as c:
            c.execute(f"INSERT OR IGNORE INTO {self.t('channels')}(channel) VALUES(?)", (ch,))
        await update.message.reply_text(f"✅ Channel {ch} added to force-join list!")

    async def _set_rate(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if uid != self._get_owner():
            await update.message.reply_text("⛔ Admins only!")
            return
        if not ctx.args:
            await update.message.reply_text("Usage: /setrate 0.1")
            return
        try:
            rate = float(ctx.args[0])
            self._set_cfg("matic_per_ref", str(rate))
            await update.message.reply_text(f"✅ Rate set to {rate} MATIC per referral!")
        except ValueError:
            await update.message.reply_text("❌ Invalid number!")
