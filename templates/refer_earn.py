"""
templates/refer_earn.py
========================
Advanced Multi-Level Refer & Earn Bot
- 3-level referral tree (L1 = 40%, L2 = 20%, L3 = 10% of join bonus)
- Keyboard-driven UI with back/cancel on every screen
- Admin panel: set bonuses, minimums, broadcast, view stats, manage users
- Payout channel: auto-posts withdrawal requests for admin to approve
- UPI payout with UPI ID validation
- Withdrawal queue, history, balance dashboard
"""
from __future__ import annotations

import re
import logging
from datetime import datetime
from typing import Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup,
    ReplyKeyboardRemove, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters
)
from telegram.constants import ParseMode

from templates.base import BaseTemplate

logger = logging.getLogger(__name__)

TEMPLATE_INFO = {
    "id":          "refer_earn",
    "name":        "Multi-Level Refer & Earn",
    "emoji":       "💸",
    "category":    "Earning",
    "description": "3-level referral system with UPI payouts, admin panel & payout channel",
    "features":    [
        "3-Level referral tree (L1/L2/L3 commissions)",
        "UPI payout with ID validation",
        "Payout channel auto-notifications",
        "Withdrawal queue & history",
        "Admin: set bonuses, minimums, broadcast",
        "Full keyboard UI with back/cancel",
        "User leaderboard & referral tree viewer",
        "Daily/weekly earning stats",
    ],
    "complexity":  "Advanced",
    "best_for":    "Earning & community growth bots",
    "stars":       5,
    "new":         True,
}

# ── Conversation states ───────────────────────────────────────────────────────
(
    MAIN_MENU, WITHDRAW_UPI, WITHDRAW_AMOUNT, WITHDRAW_CONFIRM,
    ADMIN_MENU, ADMIN_SET_JOIN_BONUS, ADMIN_SET_MIN_WITHDRAW,
    ADMIN_SET_L1, ADMIN_SET_L2, ADMIN_SET_L3,
    ADMIN_SET_PAYOUT_CHANNEL, ADMIN_BROADCAST, ADMIN_BAN_USER,
    ADMIN_ADJUST_BALANCE, ADMIN_ADJUST_UID, ADMIN_ADJUST_AMT,
    ADMIN_APPROVE_WITHDRAWAL, ADMIN_REJECT_WITHDRAWAL,
) = range(18)

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main(is_admin=False):
    buttons = [
        [InlineKeyboardButton("💰 My Balance", callback_data="balance"),
         InlineKeyboardButton("👥 My Referrals", callback_data="my_refs")],
        [InlineKeyboardButton("🔗 Get Referral Link", callback_data="ref_link"),
         InlineKeyboardButton("🌳 Referral Tree", callback_data="ref_tree")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="withdraw"),
         InlineKeyboardButton("📜 History", callback_data="history")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard"),
         InlineKeyboardButton("ℹ️ How It Works", callback_data="how_it_works")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="admin_menu")])
    return InlineKeyboardMarkup(buttons)

def kb_back(target="main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"back_{target}")]])

def kb_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="back_main")]])

def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 Set Join Bonus", callback_data="adm_join_bonus"),
         InlineKeyboardButton("📊 Set Commission %", callback_data="adm_commission")],
        [InlineKeyboardButton("🏦 Set Min Withdraw", callback_data="adm_min_withdraw"),
         InlineKeyboardButton("📢 Set Payout Channel", callback_data="adm_payout_channel")],
        [InlineKeyboardButton("📨 Broadcast", callback_data="adm_broadcast"),
         InlineKeyboardButton("🚫 Ban User", callback_data="adm_ban")],
        [InlineKeyboardButton("💰 Adjust Balance", callback_data="adm_adjust"),
         InlineKeyboardButton("📋 Pending Withdrawals", callback_data="adm_pending")],
        [InlineKeyboardButton("📈 Bot Stats", callback_data="adm_stats"),
         InlineKeyboardButton("⬅️ Back", callback_data="back_main")],
    ])

def kb_commission():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("L1 Commission %", callback_data="adm_set_l1")],
        [InlineKeyboardButton("L2 Commission %", callback_data="adm_set_l2")],
        [InlineKeyboardButton("L3 Commission %", callback_data="adm_set_l3")],
        [InlineKeyboardButton("⬅️ Back to Admin", callback_data="admin_menu")],
    ])

def kb_withdraw_confirm(upi, amount):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm Withdraw", callback_data=f"confirm_withdraw")],
        [InlineKeyboardButton("✏️ Change UPI", callback_data="withdraw"),
         InlineKeyboardButton("❌ Cancel", callback_data="back_main")],
    ])

# ── DB helpers (SQLite via self.db) ──────────────────────────────────────────

async def db_ensure_user(db, uid: int, username: str, ref_by: Optional[int]):
    await db.execute("""
        INSERT OR IGNORE INTO re_users
            (user_id, username, referred_by, balance, total_earned, joined_at)
        VALUES (?, ?, ?, 0, 0, ?)
    """, (uid, username or "", ref_by, datetime.utcnow().isoformat()))
    await db.commit()

async def db_get_user(db, uid: int) -> Optional[dict]:
    row = await db.fetchone("SELECT * FROM re_users WHERE user_id=?", (uid,))
    return dict(row) if row else None

async def db_get_setting(db, bot_id: int, key: str, default=None):
    row = await db.fetchone(
        "SELECT value FROM re_settings WHERE bot_id=? AND key=?", (bot_id, key)
    )
    return row["value"] if row else default

async def db_set_setting(db, bot_id: int, key: str, value: str):
    await db.execute("""
        INSERT INTO re_settings (bot_id, key, value) VALUES (?,?,?)
        ON CONFLICT(bot_id, key) DO UPDATE SET value=excluded.value
    """, (bot_id, key, str(value)))
    await db.commit()

async def db_add_balance(db, uid: int, amount: float, reason: str):
    await db.execute(
        "UPDATE re_users SET balance=balance+?, total_earned=total_earned+? WHERE user_id=?",
        (amount, amount, uid)
    )
    await db.execute(
        "INSERT INTO re_transactions (user_id, amount, type, note, created_at) VALUES (?,?,?,?,?)",
        (uid, amount, "credit", reason, datetime.utcnow().isoformat())
    )
    await db.commit()

async def db_deduct_balance(db, uid: int, amount: float):
    await db.execute("UPDATE re_users SET balance=balance-? WHERE user_id=?", (amount, uid))
    await db.commit()

async def db_create_withdrawal(db, uid: int, amount: float, upi: str) -> int:
    cur = await db.execute(
        "INSERT INTO re_withdrawals (user_id, amount, upi_id, status, created_at) VALUES (?,?,?,?,?)",
        (uid, amount, upi, "pending", datetime.utcnow().isoformat())
    )
    await db.commit()
    return cur.lastrowid

async def db_get_referral_chain(db, uid: int):
    """Returns (l1_uid, l2_uid, l3_uid) by walking up the referral tree."""
    row = await db.fetchone("SELECT referred_by FROM re_users WHERE user_id=?", (uid,))
    l1 = row["referred_by"] if row else None
    l2 = l3 = None
    if l1:
        row2 = await db.fetchone("SELECT referred_by FROM re_users WHERE user_id=?", (l1,))
        l2 = row2["referred_by"] if row2 else None
        if l2:
            row3 = await db.fetchone("SELECT referred_by FROM re_users WHERE user_id=?", (l2,))
            l3 = row3["referred_by"] if row3 else None
    return l1, l2, l3

async def db_get_referral_tree(db, uid: int, depth=3):
    """Returns nested dict of referrals up to `depth` levels."""
    if depth == 0:
        return []
    rows = await db.fetchall("SELECT user_id, username FROM re_users WHERE referred_by=?", (uid,))
    children = []
    for r in rows:
        children.append({
            "uid": r["user_id"],
            "username": r["username"],
            "children": await db_get_referral_tree(db, r["user_id"], depth - 1)
        })
    return children

# ── Helpers ───────────────────────────────────────────────────────────────────

def validate_upi(upi: str) -> bool:
    """Basic UPI ID format validation: localpart@bank"""
    pattern = r'^[\w.\-]{2,256}@[a-zA-Z]{2,64}$'
    return bool(re.match(pattern, upi.strip()))

def render_tree(tree, prefix="") -> str:
    lines = []
    for i, node in enumerate(tree):
        connector = "└─" if i == len(tree) - 1 else "├─"
        uname = f"@{node['username']}" if node['username'] else f"uid:{node['uid']}"
        lines.append(f"{prefix}{connector} {uname}")
        if node["children"]:
            ext = "   " if i == len(tree) - 1 else "│  "
            lines.append(render_tree(node["children"], prefix + ext))
    return "\n".join(lines)

# ── Template class ────────────────────────────────────────────────────────────

class Template(BaseTemplate):

    # ── /start ────────────────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        username = update.effective_user.username or ""
        args = ctx.args

        ref_by = None
        if args:
            try:
                ref_by = int(args[0])
                if ref_by == uid:
                    ref_by = None
            except ValueError:
                pass

        existing = await db_get_user(self.db, uid)
        is_new = existing is None

        await db_ensure_user(self.db, uid, username, ref_by)

        if is_new and ref_by:
            # Credit join bonus up the chain
            join_bonus = float(await db_get_setting(self.db, self.bot_id, "join_bonus", "10"))
            l1_pct = float(await db_get_setting(self.db, self.bot_id, "l1_pct", "40")) / 100
            l2_pct = float(await db_get_setting(self.db, self.bot_id, "l2_pct", "20")) / 100
            l3_pct = float(await db_get_setting(self.db, self.bot_id, "l3_pct", "10")) / 100

            l1, l2, l3 = await db_get_referral_chain(self.db, uid)
            if l1:
                amt = round(join_bonus * l1_pct, 2)
                await db_add_balance(self.db, l1, amt, f"L1 referral bonus for user {uid}")
                try:
                    await ctx.bot.send_message(l1, f"🎉 Someone joined using your link! +₹{amt} credited (L1)")
                except Exception:
                    pass
            if l2:
                amt = round(join_bonus * l2_pct, 2)
                await db_add_balance(self.db, l2, amt, f"L2 referral bonus for user {uid}")
                try:
                    await ctx.bot.send_message(l2, f"🎊 L2 referral joined! +₹{amt} credited")
                except Exception:
                    pass
            if l3:
                amt = round(join_bonus * l3_pct, 2)
                await db_add_balance(self.db, l3, amt, f"L3 referral bonus for user {uid}")
                try:
                    await ctx.bot.send_message(l3, f"🌟 L3 referral joined! +₹{amt} credited")
                except Exception:
                    pass

            # New user join bonus
            await db_add_balance(self.db, uid, join_bonus, "Join bonus")

        user = await db_get_user(self.db, uid)
        welcome = (
            f"👋 Welcome {'back ' if not is_new else ''}*{update.effective_user.first_name}*!\n\n"
            f"💰 Balance: ₹{user['balance']:.2f}\n"
            f"{'🎁 Join bonus credited! Invite friends to earn more.' if is_new else 'Use the menu below to manage your account.'}"
        )
        await update.message.reply_text(
            welcome, parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(self.is_admin(uid))
        )

    # ── Callback router ───────────────────────────────────────────────────────
    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        data = q.data

        # ── Back handlers ──────────────────────────────────────────────────
        if data == "back_main":
            ctx.user_data.clear()
            user = await db_get_user(self.db, uid)
            await q.edit_message_text(
                f"🏠 *Main Menu*\n💰 Balance: ₹{user['balance']:.2f}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(self.is_admin(uid))
            )
            return

        if data == "admin_menu" or data == "back_admin":
            if not self.is_admin(uid):
                await q.answer("⛔ Not authorized", show_alert=True)
                return
            await q.edit_message_text(
                "🔧 *Admin Panel*\nChoose an action:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_admin()
            )
            return

        # ── User actions ────────────────────────────────────────────────────
        if data == "balance":
            await self._show_balance(q, uid)
        elif data == "my_refs":
            await self._show_my_refs(q, uid)
        elif data == "ref_link":
            await self._show_ref_link(q, uid)
        elif data == "ref_tree":
            await self._show_ref_tree(q, uid)
        elif data == "withdraw":
            await self._start_withdraw(q, uid, ctx)
        elif data == "history":
            await self._show_history(q, uid)
        elif data == "leaderboard":
            await self._show_leaderboard(q)
        elif data == "how_it_works":
            await self._show_how(q, uid)

        # ── Admin actions ───────────────────────────────────────────────────
        elif data == "adm_join_bonus":
            await self._adm_prompt(q, uid, ctx, "join_bonus", "💵 Enter new join bonus amount (₹):")
        elif data == "adm_min_withdraw":
            await self._adm_prompt(q, uid, ctx, "min_withdraw", "🏦 Enter minimum withdrawal amount (₹):")
        elif data == "adm_commission":
            await q.edit_message_text("📊 *Commission Levels*\nSet % of join bonus per level:",
                                      parse_mode=ParseMode.MARKDOWN, reply_markup=kb_commission())
        elif data == "adm_set_l1":
            await self._adm_prompt(q, uid, ctx, "l1_pct", "L1 Commission % (e.g. 40):")
        elif data == "adm_set_l2":
            await self._adm_prompt(q, uid, ctx, "l2_pct", "L2 Commission % (e.g. 20):")
        elif data == "adm_set_l3":
            await self._adm_prompt(q, uid, ctx, "l3_pct", "L3 Commission % (e.g. 10):")
        elif data == "adm_payout_channel":
            await self._adm_prompt(q, uid, ctx, "payout_channel", "📢 Enter payout channel ID (e.g. -100123456789):")
        elif data == "adm_broadcast":
            ctx.user_data["adm_action"] = "broadcast"
            await q.edit_message_text("📨 Send the broadcast message now:",
                                      reply_markup=kb_cancel())
        elif data == "adm_ban":
            ctx.user_data["adm_action"] = "ban"
            await q.edit_message_text("🚫 Enter user ID to ban:", reply_markup=kb_cancel())
        elif data == "adm_adjust":
            ctx.user_data["adm_action"] = "adjust_uid"
            await q.edit_message_text("💰 Enter user ID to adjust balance:", reply_markup=kb_cancel())
        elif data == "adm_pending":
            await self._adm_pending(q, uid, ctx)
        elif data == "adm_stats":
            await self._adm_stats(q, uid)
        elif data.startswith("adm_approve_"):
            await self._adm_approve(q, uid, ctx, int(data.split("_")[2]))
        elif data.startswith("adm_reject_"):
            await self._adm_reject(q, uid, ctx, int(data.split("_")[2]))
        elif data == "confirm_withdraw":
            await self._confirm_withdraw(q, uid, ctx)

    # ── User screens ──────────────────────────────────────────────────────────

    async def _show_balance(self, q, uid):
        user = await db_get_user(self.db, uid)
        text = (
            f"💰 *Your Wallet*\n\n"
            f"Available: ₹{user['balance']:.2f}\n"
            f"Total Earned: ₹{user['total_earned']:.2f}\n"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    async def _show_my_refs(self, q, uid):
        rows = await self.db.fetchall("SELECT * FROM re_users WHERE referred_by=?", (uid,))
        l1_count = len(rows)
        l2_ids = [r["user_id"] for r in rows]
        l2_count = 0
        l3_count = 0
        for lid in l2_ids:
            l2_rows = await self.db.fetchall("SELECT * FROM re_users WHERE referred_by=?", (lid,))
            l2_count += len(l2_rows)
            for lid2 in [r["user_id"] for r in l2_rows]:
                l3_rows = await self.db.fetchall("SELECT * FROM re_users WHERE referred_by=?", (lid2,))
                l3_count += len(l3_rows)
        text = (
            f"👥 *Your Referral Network*\n\n"
            f"🥇 Level 1: {l1_count} direct referrals\n"
            f"🥈 Level 2: {l2_count} indirect referrals\n"
            f"🥉 Level 3: {l3_count} deep referrals\n\n"
            f"Total Network: {l1_count + l2_count + l3_count} people"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    async def _show_ref_link(self, q, uid):
        me = await q.message.get_bot().get_me()
        link = f"https://t.me/{me.username}?start={uid}"
        l1_pct = await db_get_setting(self.db, self.bot_id, "l1_pct", "40")
        l2_pct = await db_get_setting(self.db, self.bot_id, "l2_pct", "20")
        l3_pct = await db_get_setting(self.db, self.bot_id, "l3_pct", "10")
        join_bonus = await db_get_setting(self.db, self.bot_id, "join_bonus", "10")
        text = (
            f"🔗 *Your Referral Link*\n\n"
            f"`{link}`\n\n"
            f"📊 *Commission Structure*\n"
            f"L1 (Direct): {l1_pct}% of ₹{join_bonus} = ₹{float(join_bonus)*float(l1_pct)/100:.2f}\n"
            f"L2: {l2_pct}% = ₹{float(join_bonus)*float(l2_pct)/100:.2f}\n"
            f"L3: {l3_pct}% = ₹{float(join_bonus)*float(l3_pct)/100:.2f}\n\n"
            f"Share this link and earn when people join! 🚀"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    async def _show_ref_tree(self, q, uid):
        tree = await db_get_referral_tree(self.db, uid)
        if not tree:
            text = "🌳 Your referral tree is empty.\nShare your link to start earning!"
        else:
            rendered = render_tree(tree)
            text = f"🌳 *Your Referral Tree*\n\n```\n{rendered}\n```"
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    async def _start_withdraw(self, q, uid, ctx):
        min_w = float(await db_get_setting(self.db, self.bot_id, "min_withdraw", "50"))
        user = await db_get_user(self.db, uid)
        if user["balance"] < min_w:
            await q.edit_message_text(
                f"❌ Minimum withdrawal is ₹{min_w:.2f}\nYour balance: ₹{user['balance']:.2f}",
                reply_markup=kb_back()
            )
            return
        ctx.user_data["withdraw_step"] = "upi"
        await q.edit_message_text(
            f"💸 *Withdrawal Request*\n\nEnter your UPI ID (e.g. name@upi):\n\n"
            f"Your balance: ₹{user['balance']:.2f}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_cancel()
        )

    async def _show_history(self, q, uid):
        rows = await self.db.fetchall(
            "SELECT * FROM re_transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (uid,)
        )
        if not rows:
            text = "📜 No transactions yet."
        else:
            lines = ["📜 *Last 10 Transactions*\n"]
            for r in rows:
                sign = "+" if r["type"] == "credit" else "-"
                lines.append(f"{sign}₹{r['amount']:.2f} — {r['note']}\n_{r['created_at'][:10]}_")
            text = "\n".join(lines)
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    async def _show_leaderboard(self, q):
        rows = await self.db.fetchall(
            "SELECT user_id, username, total_earned FROM re_users ORDER BY total_earned DESC LIMIT 10"
        )
        medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
        lines = ["🏆 *Top Earners*\n"]
        for i, r in enumerate(rows):
            uname = f"@{r['username']}" if r['username'] else f"uid:{r['user_id']}"
            lines.append(f"{medals[i]} {uname} — ₹{r['total_earned']:.2f}")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    async def _show_how(self, q, uid):
        join_bonus = await db_get_setting(self.db, self.bot_id, "join_bonus", "10")
        l1_pct = await db_get_setting(self.db, self.bot_id, "l1_pct", "40")
        l2_pct = await db_get_setting(self.db, self.bot_id, "l2_pct", "20")
        l3_pct = await db_get_setting(self.db, self.bot_id, "l3_pct", "10")
        min_w = await db_get_setting(self.db, self.bot_id, "min_withdraw", "50")
        text = (
            f"ℹ️ *How It Works*\n\n"
            f"1️⃣ Share your referral link\n"
            f"2️⃣ Earn when friends join:\n"
            f"   • L1 (direct): {l1_pct}% of ₹{join_bonus}\n"
            f"   • L2 (friend's friend): {l2_pct}%\n"
            f"   • L3 (3rd level): {l3_pct}%\n\n"
            f"3️⃣ Withdraw via UPI when balance ≥ ₹{min_w}\n"
            f"4️⃣ Payouts processed within 24 hours"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    # ── Message handler (text input for multi-step flows) ─────────────────────
    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        text = update.message.text.strip()

        # Admin text inputs
        adm_action = ctx.user_data.get("adm_action")
        if adm_action and self.is_admin(uid):
            await self._handle_admin_input(update, ctx, adm_action, text)
            return

        # Withdraw flow
        withdraw_step = ctx.user_data.get("withdraw_step")
        if withdraw_step == "upi":
            if not validate_upi(text):
                await update.message.reply_text(
                    "❌ Invalid UPI ID format.\nEnter a valid UPI (e.g. name@upi or number@bank):",
                    reply_markup=kb_cancel()
                )
                return
            ctx.user_data["withdraw_upi"] = text
            ctx.user_data["withdraw_step"] = "amount"
            user = await db_get_user(self.db, uid)
            min_w = float(await db_get_setting(self.db, self.bot_id, "min_withdraw", "50"))
            await update.message.reply_text(
                f"✅ UPI: `{text}`\n\nEnter amount to withdraw (min ₹{min_w:.0f}, max ₹{user['balance']:.2f}):",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_cancel()
            )
            return

        if withdraw_step == "amount":
            try:
                amount = float(text)
            except ValueError:
                await update.message.reply_text("❌ Enter a valid number:", reply_markup=kb_cancel())
                return
            user = await db_get_user(self.db, uid)
            min_w = float(await db_get_setting(self.db, self.bot_id, "min_withdraw", "50"))
            if amount < min_w:
                await update.message.reply_text(f"❌ Minimum is ₹{min_w:.2f}", reply_markup=kb_cancel())
                return
            if amount > user["balance"]:
                await update.message.reply_text(
                    f"❌ Insufficient balance (₹{user['balance']:.2f})", reply_markup=kb_cancel()
                )
                return
            ctx.user_data["withdraw_amount"] = amount
            ctx.user_data["withdraw_step"] = "confirm"
            upi = ctx.user_data["withdraw_upi"]
            await update.message.reply_text(
                f"📋 *Withdrawal Summary*\n\n"
                f"UPI ID: `{upi}`\n"
                f"Amount: ₹{amount:.2f}\n\n"
                f"Confirm?",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_withdraw_confirm(upi, amount)
            )

    async def _confirm_withdraw(self, q, uid, ctx):
        upi = ctx.user_data.get("withdraw_upi")
        amount = ctx.user_data.get("withdraw_amount")
        if not upi or not amount:
            await q.edit_message_text("❌ Session expired. Start over.", reply_markup=kb_back())
            return

        user = await db_get_user(self.db, uid)
        if user["balance"] < amount:
            await q.edit_message_text("❌ Insufficient balance.", reply_markup=kb_back())
            return

        await db_deduct_balance(self.db, uid, amount)
        wid = await db_create_withdrawal(self.db, uid, amount, upi)

        # Notify payout channel
        payout_channel = await db_get_setting(self.db, self.bot_id, "payout_channel", None)
        if payout_channel:
            uname = q.from_user.username or f"uid:{uid}"
            approve_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"adm_approve_{wid}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"adm_reject_{wid}")]
            ])
            try:
                await q.get_bot().send_message(
                    payout_channel,
                    f"💸 *New Withdrawal Request #{wid}*\n\n"
                    f"User: @{uname} (`{uid}`)\n"
                    f"UPI: `{upi}`\n"
                    f"Amount: ₹{amount:.2f}",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=approve_btn
                )
            except Exception as e:
                logger.error("Payout channel send failed: %s", e)

        ctx.user_data.clear()
        await q.edit_message_text(
            f"✅ *Withdrawal Requested!*\n\n"
            f"Amount: ₹{amount:.2f}\nUPI: `{upi}`\n\n"
            f"⏳ Will be processed within 24 hours.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_back()
        )

    # ── Admin helpers ─────────────────────────────────────────────────────────

    async def _adm_prompt(self, q, uid, ctx, key, prompt):
        if not self.is_admin(uid):
            await q.answer("⛔ Not authorized", show_alert=True)
            return
        ctx.user_data["adm_action"] = f"set_{key}"
        await q.edit_message_text(prompt, reply_markup=kb_cancel())

    async def _adm_stats(self, q, uid):
        if not self.is_admin(uid):
            await q.answer("⛔ Not authorized", show_alert=True)
            return
        total_users = (await self.db.fetchone("SELECT COUNT(*) AS c FROM re_users"))["c"]
        total_paid = (await self.db.fetchone(
            "SELECT COALESCE(SUM(amount),0) AS s FROM re_withdrawals WHERE status='approved'"
        ))["s"]
        pending_count = (await self.db.fetchone(
            "SELECT COUNT(*) AS c FROM re_withdrawals WHERE status='pending'"
        ))["c"]
        text = (
            f"📈 *Bot Statistics*\n\n"
            f"👥 Total Users: {total_users}\n"
            f"💸 Total Paid Out: ₹{total_paid:.2f}\n"
            f"⏳ Pending Withdrawals: {pending_count}"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup([[
                                       InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")
                                   ]]))

    async def _adm_pending(self, q, uid, ctx):
        if not self.is_admin(uid):
            await q.answer("⛔ Not authorized", show_alert=True)
            return
        rows = await self.db.fetchall(
            "SELECT * FROM re_withdrawals WHERE status='pending' ORDER BY created_at ASC LIMIT 10"
        )
        if not rows:
            await q.edit_message_text("✅ No pending withdrawals.",
                                       reply_markup=InlineKeyboardMarkup([[
                                           InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")
                                       ]]))
            return
        buttons = []
        lines = ["📋 *Pending Withdrawals*\n"]
        for r in rows:
            lines.append(f"#{r['id']} — ₹{r['amount']:.2f} → `{r['upi_id']}` (uid:{r['user_id']})")
            buttons.append([
                InlineKeyboardButton(f"✅ #{r['id']}", callback_data=f"adm_approve_{r['id']}"),
                InlineKeyboardButton(f"❌ #{r['id']}", callback_data=f"adm_reject_{r['id']}")
            ])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")])
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(buttons))

    async def _adm_approve(self, q, uid, ctx, wid: int):
        if not self.is_admin(uid):
            await q.answer("⛔ Not authorized", show_alert=True)
            return
        row = await self.db.fetchone("SELECT * FROM re_withdrawals WHERE id=?", (wid,))
        if not row or row["status"] != "pending":
            await q.answer("Already processed.", show_alert=True)
            return
        await self.db.execute(
            "UPDATE re_withdrawals SET status='approved' WHERE id=?", (wid,)
        )
        await self.db.commit()
        try:
            await q.get_bot().send_message(
                row["user_id"],
                f"✅ Your withdrawal of ₹{row['amount']:.2f} to `{row['upi_id']}` has been *approved*!\n"
                f"Payment will arrive shortly.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        await q.edit_message_text(f"✅ Withdrawal #{wid} approved.", reply_markup=kb_back("admin"))

    async def _adm_reject(self, q, uid, ctx, wid: int):
        if not self.is_admin(uid):
            await q.answer("⛔ Not authorized", show_alert=True)
            return
        row = await self.db.fetchone("SELECT * FROM re_withdrawals WHERE id=?", (wid,))
        if not row or row["status"] != "pending":
            await q.answer("Already processed.", show_alert=True)
            return
        # Refund balance
        await db_add_balance(self.db, row["user_id"], row["amount"], f"Withdrawal #{wid} refunded")
        await self.db.execute("UPDATE re_withdrawals SET status='rejected' WHERE id=?", (wid,))
        await self.db.commit()
        try:
            await q.get_bot().send_message(
                row["user_id"],
                f"❌ Your withdrawal of ₹{row['amount']:.2f} was *rejected*.\n"
                f"Amount refunded to your balance.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        await q.edit_message_text(f"❌ Withdrawal #{wid} rejected & refunded.", reply_markup=kb_back("admin"))

    async def _handle_admin_input(self, update: Update, ctx, action: str, text: str):
        uid = update.effective_user.id
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin Panel", callback_data="admin_menu")]])

        setting_map = {
            "set_join_bonus": "join_bonus",
            "set_min_withdraw": "min_withdraw",
            "set_l1_pct": "l1_pct",
            "set_l2_pct": "l2_pct",
            "set_l3_pct": "l3_pct",
            "set_payout_channel": "payout_channel",
        }
        if action in setting_map:
            key = setting_map[action]
            await db_set_setting(self.db, self.bot_id, key, text)
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ `{key}` set to `{text}`",
                                             parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb)
            return

        if action == "broadcast":
            users = await self.db.fetchall("SELECT user_id FROM re_users WHERE banned=0")
            sent = failed = 0
            for u in users:
                try:
                    await update.get_bot().send_message(u["user_id"], text)
                    sent += 1
                except Exception:
                    failed += 1
            ctx.user_data.clear()
            await update.message.reply_text(f"📨 Broadcast done. Sent: {sent}, Failed: {failed}",
                                             reply_markup=back_kb)
            return

        if action == "ban":
            try:
                ban_uid = int(text)
                await self.db.execute("UPDATE re_users SET banned=1 WHERE user_id=?", (ban_uid,))
                await self.db.commit()
                ctx.user_data.clear()
                await update.message.reply_text(f"🚫 User {ban_uid} banned.", reply_markup=back_kb)
            except ValueError:
                await update.message.reply_text("❌ Invalid user ID.")
            return

        if action == "adjust_uid":
            try:
                ctx.user_data["adjust_uid"] = int(text)
                ctx.user_data["adm_action"] = "adjust_amt"
                await update.message.reply_text(
                    f"Enter amount to add (use negative to deduct):",
                    reply_markup=kb_cancel()
                )
            except ValueError:
                await update.message.reply_text("❌ Invalid user ID.")
            return

        if action == "adjust_amt":
            try:
                amt = float(text)
                target = ctx.user_data["adjust_uid"]
                if amt > 0:
                    await db_add_balance(self.db, target, amt, f"Admin adjustment by {uid}")
                else:
                    await db_deduct_balance(self.db, target, abs(amt))
                ctx.user_data.clear()
                await update.message.reply_text(f"✅ Balance adjusted by ₹{amt:.2f} for user {target}",
                                                 reply_markup=back_kb)
            except (ValueError, KeyError):
                await update.message.reply_text("❌ Error adjusting balance.")
            return

    # ── build_app ─────────────────────────────────────────────────────────────
    async def build_app(self) -> Application:
        # Ensure tables exist
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS re_users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                referred_by INTEGER,
                balance REAL DEFAULT 0,
                total_earned REAL DEFAULT 0,
                banned INTEGER DEFAULT 0,
                joined_at TEXT
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS re_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                type TEXT,
                note TEXT,
                created_at TEXT
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS re_withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount REAL,
                upi_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS re_settings (
                bot_id INTEGER,
                key TEXT,
                value TEXT,
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
        uid = update.effective_user.id
        if not self.is_admin(uid):
            await update.message.reply_text("⛔ Not authorized.")
            return
        await update.message.reply_text("🔧 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                         reply_markup=kb_admin())
