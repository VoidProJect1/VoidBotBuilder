"""
templates/betting_bot.py
=========================
Advanced Betting Bot — Manual UPI Payments
- Deposit via UPI (user pays, sends screenshot/UTR, bot queues for admin)
- "Verify" button: bot confirms "adding within 15-30 minutes"
- UPI ID validation before deposit instructions shown
- Admin sets UPI ID, minimum deposit, minimum payout
- Payout button: user requests withdrawal (min balance enforced)
- Admin approves/rejects payouts from panel
- Bet types: coin flip, odd/even, number guess
- Full keyboard UI, back/cancel everywhere
"""
from __future__ import annotations

import logging
import random
import re
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

from templates.base import BaseTemplate

logger = logging.getLogger(__name__)

TEMPLATE_INFO = {
    "id":          "betting_bot",
    "name":        "Betting Bot (Manual UPI)",
    "emoji":       "🎰",
    "category":    "Gaming",
    "description": "Bet & earn with manual UPI deposits, instant bets, admin-controlled payouts",
    "features":    [
        "Manual UPI deposit with verify flow",
        "Payment added within 15-30 min notification",
        "UPI ID format validation",
        "Coin flip, Odd/Even, Number guess bets",
        "Admin sets UPI ID, min deposit, min payout",
        "Payout channel notifications",
        "Withdrawal queue with approval",
        "Full admin panel with stats",
    ],
    "complexity":  "Advanced",
    "best_for":    "Gaming & betting communities",
    "stars":       5,
    "new":         True,
}

# ── Validators ────────────────────────────────────────────────────────────────

def validate_upi(upi: str) -> bool:
    return bool(re.match(r'^[\w.\-]{2,256}@[a-zA-Z]{2,64}$', upi.strip()))

def validate_utr(utr: str) -> bool:
    """UTR/transaction ID: 12-22 alphanumeric chars."""
    return bool(re.match(r'^[A-Za-z0-9]{10,22}$', utr.strip()))

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main(is_admin=False):
    buttons = [
        [InlineKeyboardButton("💰 Deposit", callback_data="bet_deposit"),
         InlineKeyboardButton("🎮 Play", callback_data="bet_play")],
        [InlineKeyboardButton("💸 Withdraw", callback_data="bet_withdraw"),
         InlineKeyboardButton("📜 History", callback_data="bet_history")],
        [InlineKeyboardButton("💳 My Balance", callback_data="bet_balance"),
         InlineKeyboardButton("📊 Stats", callback_data="bet_stats")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="bet_admin")])
    return InlineKeyboardMarkup(buttons)

def kb_back(target="bet_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=target)]])

def kb_cancel(target="bet_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=target)]])

def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏦 Set UPI ID", callback_data="bet_adm_set_upi"),
         InlineKeyboardButton("💵 Set Min Deposit", callback_data="bet_adm_min_dep")],
        [InlineKeyboardButton("🏧 Set Min Payout", callback_data="bet_adm_min_pay"),
         InlineKeyboardButton("📢 Payout Channel", callback_data="bet_adm_payout_ch")],
        [InlineKeyboardButton("📋 Pending Deposits", callback_data="bet_adm_pending_dep"),
         InlineKeyboardButton("📋 Pending Payouts", callback_data="bet_adm_pending_pay")],
        [InlineKeyboardButton("💰 Adjust Balance", callback_data="bet_adm_adjust"),
         InlineKeyboardButton("📈 Stats", callback_data="bet_adm_stats")],
        [InlineKeyboardButton("📨 Broadcast", callback_data="bet_adm_broadcast"),
         InlineKeyboardButton("🚫 Ban User", callback_data="bet_adm_ban")],
        [InlineKeyboardButton("⬅️ Back", callback_data="bet_main")],
    ])

def kb_games():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 Coin Flip", callback_data="bet_game_coin"),
         InlineKeyboardButton("🔢 Odd/Even", callback_data="bet_game_oddeven")],
        [InlineKeyboardButton("🎯 Number Guess (1-6)", callback_data="bet_game_dice")],
        [InlineKeyboardButton("⬅️ Back", callback_data="bet_main")],
    ])

def kb_bet_amount(game):
    amounts = [10, 25, 50, 100, 250, 500]
    buttons = []
    for i in range(0, len(amounts), 3):
        row = [InlineKeyboardButton(f"₹{a}", callback_data=f"bet_amount_{game}_{a}")
               for a in amounts[i:i+3]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton("✏️ Custom Amount", callback_data=f"bet_custom_{game}")])
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="bet_play")])
    return InlineKeyboardMarkup(buttons)

def kb_coin_pick(amount):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟡 Heads", callback_data=f"bet_coin_heads_{amount}"),
         InlineKeyboardButton("⚫ Tails", callback_data=f"bet_coin_tails_{amount}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="bet_game_coin")],
    ])

def kb_oddeven_pick(amount):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 Odd", callback_data=f"bet_oe_odd_{amount}"),
         InlineKeyboardButton("🔴 Even", callback_data=f"bet_oe_even_{amount}")],
        [InlineKeyboardButton("⬅️ Back", callback_data="bet_game_oddeven")],
    ])

def kb_dice_picks(amount):
    buttons = [[InlineKeyboardButton(str(n), callback_data=f"bet_dice_{n}_{amount}") for n in range(1, 7)]]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="bet_game_dice")])
    return InlineKeyboardMarkup(buttons)

def kb_verify_deposit(dep_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I've Paid — Verify", callback_data=f"bet_verify_dep_{dep_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="bet_main")],
    ])

# ── DB helpers ────────────────────────────────────────────────────────────────

async def db_ensure_user(db, uid, username):
    await db.execute("""
        INSERT OR IGNORE INTO bet_users (user_id, username, balance, total_bet, total_won, banned)
        VALUES (?,?,0,0,0,0)
    """, (uid, username or ""))
    await db.commit()

async def db_get_user(db, uid):
    row = await db.fetchone("SELECT * FROM bet_users WHERE user_id=?", (uid,))
    return dict(row) if row else None

async def db_get_setting(db, bot_id, key, default=None):
    row = await db.fetchone("SELECT value FROM bet_settings WHERE bot_id=? AND key=?", (bot_id, key))
    return row["value"] if row else default

async def db_set_setting(db, bot_id, key, value):
    await db.execute("""
        INSERT INTO bet_settings (bot_id, key, value) VALUES (?,?,?)
        ON CONFLICT(bot_id,key) DO UPDATE SET value=excluded.value
    """, (bot_id, key, str(value)))
    await db.commit()

async def db_add_balance(db, uid, amount, note):
    await db.execute("UPDATE bet_users SET balance=balance+? WHERE user_id=?", (amount, uid))
    await db.execute(
        "INSERT INTO bet_txns (user_id, amount, type, note, created_at) VALUES (?,?,?,?,?)",
        (uid, amount, "credit", note, datetime.utcnow().isoformat())
    )
    await db.commit()

async def db_deduct_balance(db, uid, amount, note):
    await db.execute("UPDATE bet_users SET balance=balance-? WHERE user_id=?", (amount, uid))
    await db.execute(
        "INSERT INTO bet_txns (user_id, amount, type, note, created_at) VALUES (?,?,?,?,?)",
        (uid, amount, "debit", note, datetime.utcnow().isoformat())
    )
    await db.commit()

# ── Template ──────────────────────────────────────────────────────────────────

class Template(BaseTemplate):

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        await db_ensure_user(self.db, uid, update.effective_user.username)
        user = await db_get_user(self.db, uid)
        await update.message.reply_text(
            f"🎰 *Welcome to Betting Bot!*\n\n"
            f"💰 Balance: ₹{user['balance']:.2f}\n\n"
            f"Deposit via UPI, play games & withdraw winnings!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(self.is_admin(uid))
        )

    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        data = q.data
        await db_ensure_user(self.db, uid, q.from_user.username)
        user = await db_get_user(self.db, uid)

        if user and user.get("banned"):
            await q.answer("🚫 You are banned.", show_alert=True)
            return

        # ── Navigation ─────────────────────────────────────────────────────
        if data == "bet_main":
            ctx.user_data.clear()
            await q.edit_message_text(
                f"🎰 *Betting Bot*\n💰 Balance: ₹{user['balance']:.2f}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(self.is_admin(uid))
            )

        elif data == "bet_balance":
            total_bet = user["total_bet"]
            total_won = user["total_won"]
            profit = total_won - total_bet
            await q.edit_message_text(
                f"💳 *Your Wallet*\n\n"
                f"💰 Balance: ₹{user['balance']:.2f}\n"
                f"🎮 Total Wagered: ₹{total_bet:.2f}\n"
                f"🏆 Total Won: ₹{total_won:.2f}\n"
                f"{'📈' if profit >= 0 else '📉'} Net: ₹{profit:.2f}",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
            )

        elif data == "bet_history":
            rows = await self.db.fetchall(
                "SELECT * FROM bet_txns WHERE user_id=? ORDER BY created_at DESC LIMIT 10", (uid,)
            )
            lines = ["📜 *Last 10 Transactions*\n"]
            for r in rows:
                sign = "+" if r["type"] == "credit" else "-"
                lines.append(f"{sign}₹{r['amount']:.2f} — {r['note']}\n_{r['created_at'][:10]}_")
            await q.edit_message_text(
                "\n".join(lines) if rows else "No transactions yet.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
            )

        elif data == "bet_stats":
            rows = await self.db.fetchall(
                "SELECT user_id, username, total_won FROM bet_users ORDER BY total_won DESC LIMIT 10"
            )
            medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
            lines = ["🏆 *Top Winners*\n"]
            for i, r in enumerate(rows):
                un = f"@{r['username']}" if r['username'] else f"uid:{r['user_id']}"
                lines.append(f"{medals[i]} {un} — ₹{r['total_won']:.2f}")
            await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

        # ── Deposit ────────────────────────────────────────────────────────
        elif data == "bet_deposit":
            upi = await db_get_setting(self.db, self.bot_id, "upi_id", None)
            min_dep = await db_get_setting(self.db, self.bot_id, "min_deposit", "50")
            if not upi:
                await q.edit_message_text(
                    "❌ UPI not configured yet. Contact admin.",
                    reply_markup=kb_back()
                )
                return
            # Validate UPI is set correctly
            if not validate_upi(upi):
                await q.edit_message_text(
                    "❌ Admin UPI ID is invalid. Contact admin.",
                    reply_markup=kb_back()
                )
                return
            ctx.user_data["deposit_step"] = "enter_amount"
            await q.edit_message_text(
                f"💰 *Deposit via UPI*\n\n"
                f"UPI ID: `{upi}`\n"
                f"Min Deposit: ₹{min_dep}\n\n"
                f"Enter the amount you want to deposit:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel()
            )

        elif data.startswith("bet_verify_dep_"):
            dep_id = int(data.replace("bet_verify_dep_", ""))
            row = await self.db.fetchone("SELECT * FROM bet_deposits WHERE id=?", (dep_id,))
            if not row or row["user_id"] != uid:
                await q.answer("Invalid deposit.", show_alert=True)
                return
            if row["status"] != "pending_utr":
                await q.answer("Already submitted.", show_alert=True)
                return
            ctx.user_data["deposit_step"] = "enter_utr"
            ctx.user_data["deposit_id"] = dep_id
            await q.edit_message_text(
                f"✅ *Payment Verification*\n\n"
                f"Enter your UTR/Transaction ID\n"
                f"(12-22 alphanumeric characters from your UPI app):",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel()
            )

        # ── Games ──────────────────────────────────────────────────────────
        elif data == "bet_play":
            await q.edit_message_text(
                "🎮 *Choose a Game:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_games()
            )

        elif data == "bet_game_coin":
            await q.edit_message_text(
                "🪙 *Coin Flip*\n\nSelect your bet amount:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_bet_amount("coin")
            )

        elif data == "bet_game_oddeven":
            await q.edit_message_text(
                "🔢 *Odd/Even*\n\nA number 1-10 is rolled. Pick odd or even!\nWin 1.9x your bet.\n\nSelect bet amount:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_bet_amount("oe")
            )

        elif data == "bet_game_dice":
            await q.edit_message_text(
                "🎯 *Number Guess (1-6)*\n\nGuess the dice! Win 5x your bet.\n\nSelect bet amount:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_bet_amount("dice")
            )

        elif data.startswith("bet_amount_"):
            parts = data.split("_")
            game = parts[2]
            amount = float(parts[3])
            await self._bet_pick(q, uid, user, game, amount, ctx)

        elif data.startswith("bet_custom_"):
            game = data.replace("bet_custom_", "")
            ctx.user_data["bet_game"] = game
            ctx.user_data["bet_step"] = "custom_amount"
            await q.edit_message_text(
                f"✏️ Enter custom bet amount (₹):",
                reply_markup=kb_cancel()
            )

        elif data.startswith("bet_coin_"):
            parts = data.split("_")
            pick = parts[2]
            amount = float(parts[3])
            await self._play_coin(q, uid, user, pick, amount)

        elif data.startswith("bet_oe_"):
            parts = data.split("_")
            pick = parts[2]
            amount = float(parts[3])
            await self._play_oddeven(q, uid, user, pick, amount)

        elif data.startswith("bet_dice_"):
            parts = data.split("_")
            pick = int(parts[2])
            amount = float(parts[3])
            await self._play_dice(q, uid, user, pick, amount)

        # ── Withdraw ───────────────────────────────────────────────────────
        elif data == "bet_withdraw":
            min_pay = float(await db_get_setting(self.db, self.bot_id, "min_payout", "100"))
            if user["balance"] < min_pay:
                await q.edit_message_text(
                    f"❌ Min withdrawal: ₹{min_pay:.2f}\nYour balance: ₹{user['balance']:.2f}",
                    reply_markup=kb_back()
                )
                return
            ctx.user_data["withdraw_step"] = "upi"
            await q.edit_message_text(
                f"💸 *Withdrawal*\n\nBalance: ₹{user['balance']:.2f}\n\nEnter your UPI ID:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel()
            )

        # ── Admin ──────────────────────────────────────────────────────────
        elif data == "bet_admin":
            if not self.is_admin(uid):
                await q.answer("⛔ Not authorized", show_alert=True)
                return
            await q.edit_message_text("🔧 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=kb_admin())

        elif data.startswith("bet_adm_"):
            await self._handle_admin_callback(q, uid, ctx, data)

    async def _bet_pick(self, q, uid, user, game, amount, ctx):
        if user["balance"] < amount:
            await q.edit_message_text(
                f"❌ Insufficient balance!\nBalance: ₹{user['balance']:.2f}\nBet: ₹{amount:.2f}",
                reply_markup=kb_back("bet_play")
            )
            return
        if game == "coin":
            await q.edit_message_text(
                f"🪙 Bet: ₹{amount:.2f}\nPick your side:",
                reply_markup=kb_coin_pick(amount)
            )
        elif game == "oe":
            await q.edit_message_text(
                f"🔢 Bet: ₹{amount:.2f}\nPick Odd or Even:",
                reply_markup=kb_oddeven_pick(amount)
            )
        elif game == "dice":
            await q.edit_message_text(
                f"🎯 Bet: ₹{amount:.2f}\nPick a number (1-6):",
                reply_markup=kb_dice_picks(amount)
            )

    async def _play_coin(self, q, uid, user, pick, amount):
        if user["balance"] < amount:
            await q.edit_message_text("❌ Insufficient balance!", reply_markup=kb_back("bet_play"))
            return
        result = random.choice(["heads", "tails"])
        won = pick == result
        winnings = round(amount * 1.9, 2) if won else 0
        await db_deduct_balance(self.db, uid, amount, f"Coin flip bet")
        if won:
            await db_add_balance(self.db, uid, winnings, f"Coin flip win")
        await self.db.execute(
            "UPDATE bet_users SET total_bet=total_bet+?, total_won=total_won+? WHERE user_id=?",
            (amount, winnings, uid)
        )
        await self.db.commit()
        user = await db_get_user(self.db, uid)
        coin_icon = "🟡" if result == "heads" else "⚫"
        result_text = (
            f"{coin_icon} *Result: {result.title()}!*\n\n"
            f"{'✅ You Won!' if won else '❌ You Lost!'}\n"
            f"{'Winnings: ₹' + str(winnings) if won else 'Lost: ₹' + str(amount)}\n"
            f"New Balance: ₹{user['balance']:.2f}"
        )
        play_again = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Play Again", callback_data="bet_game_coin"),
             InlineKeyboardButton("🏠 Menu", callback_data="bet_main")]
        ])
        await q.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN, reply_markup=play_again)

    async def _play_oddeven(self, q, uid, user, pick, amount):
        if user["balance"] < amount:
            await q.edit_message_text("❌ Insufficient balance!", reply_markup=kb_back("bet_play"))
            return
        number = random.randint(1, 10)
        result = "odd" if number % 2 != 0 else "even"
        won = pick == result
        winnings = round(amount * 1.9, 2) if won else 0
        await db_deduct_balance(self.db, uid, amount, "Odd/Even bet")
        if won:
            await db_add_balance(self.db, uid, winnings, "Odd/Even win")
        await self.db.execute(
            "UPDATE bet_users SET total_bet=total_bet+?, total_won=total_won+? WHERE user_id=?",
            (amount, winnings, uid)
        )
        await self.db.commit()
        user = await db_get_user(self.db, uid)
        result_text = (
            f"🎲 *Number rolled: {number}* ({result.title()})\n\n"
            f"You picked: {pick.title()}\n"
            f"{'✅ You Won!' if won else '❌ You Lost!'}\n"
            f"{'Winnings: ₹' + str(winnings) if won else 'Lost: ₹' + str(amount)}\n"
            f"Balance: ₹{user['balance']:.2f}"
        )
        play_again = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Play Again", callback_data="bet_game_oddeven"),
             InlineKeyboardButton("🏠 Menu", callback_data="bet_main")]
        ])
        await q.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN, reply_markup=play_again)

    async def _play_dice(self, q, uid, user, pick, amount):
        if user["balance"] < amount:
            await q.edit_message_text("❌ Insufficient balance!", reply_markup=kb_back("bet_play"))
            return
        number = random.randint(1, 6)
        won = pick == number
        winnings = round(amount * 5.0, 2) if won else 0
        await db_deduct_balance(self.db, uid, amount, "Dice bet")
        if won:
            await db_add_balance(self.db, uid, winnings, "Dice win")
        await self.db.execute(
            "UPDATE bet_users SET total_bet=total_bet+?, total_won=total_won+? WHERE user_id=?",
            (amount, winnings, uid)
        )
        await self.db.commit()
        user = await db_get_user(self.db, uid)
        dice_emojis = ["", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"]
        result_text = (
            f"🎯 *Dice rolled: {dice_emojis[number]} ({number})*\n\n"
            f"You guessed: {pick}\n"
            f"{'✅ JACKPOT! You Won!' if won else '❌ Wrong guess!'}\n"
            f"{'Winnings: ₹' + str(winnings) + ' (5x)' if won else 'Lost: ₹' + str(amount)}\n"
            f"Balance: ₹{user['balance']:.2f}"
        )
        play_again = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Play Again", callback_data="bet_game_dice"),
             InlineKeyboardButton("🏠 Menu", callback_data="bet_main")]
        ])
        await q.edit_message_text(result_text, parse_mode=ParseMode.MARKDOWN, reply_markup=play_again)

    async def _handle_admin_callback(self, q, uid, ctx, data: str):
        if not self.is_admin(uid):
            await q.answer("⛔ Not authorized", show_alert=True)
            return

        setting_prompts = {
            "bet_adm_set_upi":     ("adm_set_upi_id",  "🏦 Enter the UPI ID for receiving deposits:"),
            "bet_adm_min_dep":     ("adm_set_min_dep",  "💵 Enter minimum deposit amount (₹):"),
            "bet_adm_min_pay":     ("adm_set_min_pay",  "🏧 Enter minimum payout amount (₹):"),
            "bet_adm_payout_ch":   ("adm_set_pay_ch",   "📢 Enter payout channel ID (e.g. -100123456):"),
            "bet_adm_broadcast":   ("adm_broadcast",    "📨 Send your broadcast message:"),
            "bet_adm_ban":         ("adm_ban",          "🚫 Enter user ID to ban:"),
            "bet_adm_adjust":      ("adm_adjust_uid",   "💰 Enter user ID to adjust balance:"),
        }
        if data in setting_prompts:
            action, prompt = setting_prompts[data]
            ctx.user_data["adm_action"] = action
            await q.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="bet_admin")
            ]]))
            return

        if data == "bet_adm_stats":
            total = (await self.db.fetchone("SELECT COUNT(*) AS c FROM bet_users"))["c"]
            total_dep = (await self.db.fetchone(
                "SELECT COALESCE(SUM(amount),0) AS s FROM bet_deposits WHERE status='approved'"
            ))["s"]
            total_pay = (await self.db.fetchone(
                "SELECT COALESCE(SUM(amount),0) AS s FROM bet_payouts WHERE status='approved'"
            ))["s"]
            await q.edit_message_text(
                f"📈 *Bot Stats*\n\nUsers: {total}\nTotal Deposits: ₹{total_dep:.2f}\nTotal Payouts: ₹{total_pay:.2f}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="bet_admin")]])
            )

        elif data == "bet_adm_pending_dep":
            rows = await self.db.fetchall(
                "SELECT * FROM bet_deposits WHERE status='pending_approval' ORDER BY created_at ASC LIMIT 10"
            )
            if not rows:
                await q.edit_message_text("✅ No pending deposits.", reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="bet_admin")
                ]]))
                return
            buttons = []
            lines = ["📋 *Pending Deposits*\n"]
            for r in rows:
                lines.append(f"#{r['id']} — ₹{r['amount']:.2f} | UTR: {r['utr']} | uid:{r['user_id']}")
                buttons.append([
                    InlineKeyboardButton(f"✅ #{r['id']}", callback_data=f"bet_adm_dep_ok_{r['id']}"),
                    InlineKeyboardButton(f"❌ #{r['id']}", callback_data=f"bet_adm_dep_rej_{r['id']}")
                ])
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="bet_admin")])
            await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=InlineKeyboardMarkup(buttons))

        elif data == "bet_adm_pending_pay":
            rows = await self.db.fetchall(
                "SELECT * FROM bet_payouts WHERE status='pending' ORDER BY created_at ASC LIMIT 10"
            )
            if not rows:
                await q.edit_message_text("✅ No pending payouts.", reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⬅️ Back", callback_data="bet_admin")
                ]]))
                return
            buttons = []
            lines = ["📋 *Pending Payouts*\n"]
            for r in rows:
                lines.append(f"#{r['id']} — ₹{r['amount']:.2f} → `{r['upi_id']}` | uid:{r['user_id']}")
                buttons.append([
                    InlineKeyboardButton(f"✅ #{r['id']}", callback_data=f"bet_adm_pay_ok_{r['id']}"),
                    InlineKeyboardButton(f"❌ #{r['id']}", callback_data=f"bet_adm_pay_rej_{r['id']}")
                ])
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="bet_admin")])
            await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("bet_adm_dep_ok_"):
            dep_id = int(data.split("_")[-1])
            await self._admin_approve_deposit(q, dep_id)

        elif data.startswith("bet_adm_dep_rej_"):
            dep_id = int(data.split("_")[-1])
            await self._admin_reject_deposit(q, dep_id)

        elif data.startswith("bet_adm_pay_ok_"):
            pay_id = int(data.split("_")[-1])
            await self._admin_approve_payout(q, pay_id)

        elif data.startswith("bet_adm_pay_rej_"):
            pay_id = int(data.split("_")[-1])
            await self._admin_reject_payout(q, pay_id)

    async def _admin_approve_deposit(self, q, dep_id):
        row = await self.db.fetchone("SELECT * FROM bet_deposits WHERE id=?", (dep_id,))
        if not row or row["status"] != "pending_approval":
            await q.answer("Already processed.", show_alert=True)
            return
        await db_add_balance(self.db, row["user_id"], row["amount"], f"Deposit #{dep_id} approved")
        await self.db.execute("UPDATE bet_deposits SET status='approved' WHERE id=?", (dep_id,))
        await self.db.commit()
        try:
            await q.get_bot().send_message(
                row["user_id"],
                f"✅ Your deposit of ₹{row['amount']:.2f} has been *approved* and added to your balance!",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception: pass
        await q.edit_message_text(f"✅ Deposit #{dep_id} approved.",
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="bet_admin")]]))

    async def _admin_reject_deposit(self, q, dep_id):
        row = await self.db.fetchone("SELECT * FROM bet_deposits WHERE id=?", (dep_id,))
        if not row: return
        await self.db.execute("UPDATE bet_deposits SET status='rejected' WHERE id=?", (dep_id,))
        await self.db.commit()
        try:
            await q.get_bot().send_message(
                row["user_id"],
                f"❌ Your deposit of ₹{row['amount']:.2f} was rejected. Contact support if this is an error."
            )
        except Exception: pass
        await q.edit_message_text(f"❌ Deposit #{dep_id} rejected.",
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="bet_admin")]]))

    async def _admin_approve_payout(self, q, pay_id):
        row = await self.db.fetchone("SELECT * FROM bet_payouts WHERE id=?", (pay_id,))
        if not row or row["status"] != "pending":
            await q.answer("Already processed.", show_alert=True)
            return
        await self.db.execute("UPDATE bet_payouts SET status='approved' WHERE id=?", (pay_id,))
        await self.db.commit()
        try:
            await q.get_bot().send_message(
                row["user_id"],
                f"✅ Payout of ₹{row['amount']:.2f} to `{row['upi_id']}` *approved*! Arriving shortly.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception: pass
        await q.edit_message_text(f"✅ Payout #{pay_id} approved.",
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="bet_admin")]]))

    async def _admin_reject_payout(self, q, pay_id):
        row = await self.db.fetchone("SELECT * FROM bet_payouts WHERE id=?", (pay_id,))
        if not row: return
        await db_add_balance(self.db, row["user_id"], row["amount"], f"Payout #{pay_id} refunded")
        await self.db.execute("UPDATE bet_payouts SET status='rejected' WHERE id=?", (pay_id,))
        await self.db.commit()
        try:
            await q.get_bot().send_message(
                row["user_id"],
                f"❌ Payout #{pay_id} rejected. ₹{row['amount']:.2f} refunded to balance."
            )
        except Exception: pass
        await q.edit_message_text(f"❌ Payout #{pay_id} rejected & refunded.",
                                   reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="bet_admin")]]))

    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        text = update.message.text.strip()
        back_admin_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="bet_admin")]])
        back_main_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="bet_main")]])

        # ── Deposit flow ────────────────────────────────────────────────────
        deposit_step = ctx.user_data.get("deposit_step")
        if deposit_step == "enter_amount":
            try:
                amount = float(text)
            except ValueError:
                await update.message.reply_text("❌ Enter a valid number.", reply_markup=kb_cancel())
                return
            min_dep = float(await db_get_setting(self.db, self.bot_id, "min_deposit", "50"))
            if amount < min_dep:
                await update.message.reply_text(f"❌ Minimum deposit: ₹{min_dep:.2f}", reply_markup=kb_cancel())
                return
            upi = await db_get_setting(self.db, self.bot_id, "upi_id", "")
            cur = await self.db.execute(
                "INSERT INTO bet_deposits (user_id, amount, utr, status, created_at) VALUES (?,?,?,?,?)",
                (uid, amount, "", "pending_utr", datetime.utcnow().isoformat())
            )
            await self.db.commit()
            dep_id = cur.lastrowid
            ctx.user_data["deposit_step"] = None
            await update.message.reply_text(
                f"💳 *Deposit Instructions*\n\n"
                f"Amount: ₹{amount:.2f}\n"
                f"Pay to UPI: `{upi}`\n\n"
                f"After paying, click *Verify Payment* below.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_verify_deposit(dep_id)
            )
            return

        if deposit_step == "enter_utr":
            dep_id = ctx.user_data.get("deposit_id")
            if not validate_utr(text):
                await update.message.reply_text(
                    "❌ Invalid UTR/Transaction ID.\nEnter the 12-22 character ID from your UPI app:",
                    reply_markup=kb_cancel()
                )
                return
            await self.db.execute(
                "UPDATE bet_deposits SET utr=?, status='pending_approval' WHERE id=? AND user_id=?",
                (text, dep_id, uid)
            )
            await self.db.commit()
            # Notify payout channel
            payout_channel = await db_get_setting(self.db, self.bot_id, "payout_channel", None)
            row = await self.db.fetchone("SELECT * FROM bet_deposits WHERE id=?", (dep_id,))
            if payout_channel and row:
                try:
                    await update.get_bot().send_message(
                        payout_channel,
                        f"💰 *New Deposit Request #{dep_id}*\n\n"
                        f"User: uid:{uid}\nAmount: ₹{row['amount']:.2f}\nUTR: `{text}`",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton(f"✅ Approve", callback_data=f"bet_adm_dep_ok_{dep_id}"),
                            InlineKeyboardButton(f"❌ Reject", callback_data=f"bet_adm_dep_rej_{dep_id}"),
                        ]])
                    )
                except Exception as e:
                    logger.error("Payout channel error: %s", e)
            ctx.user_data.clear()
            await update.message.reply_text(
                f"✅ *Payment submitted for verification!*\n\n"
                f"UTR: `{text}`\n\n"
                f"⏳ Your balance will be credited within *15-30 minutes* after verification.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_main_kb
            )
            return

        # ── Withdraw flow ────────────────────────────────────────────────────
        withdraw_step = ctx.user_data.get("withdraw_step")
        if withdraw_step == "upi":
            if not validate_upi(text):
                await update.message.reply_text(
                    "❌ Invalid UPI ID. Enter format: name@bank", reply_markup=kb_cancel()
                )
                return
            ctx.user_data["withdraw_upi"] = text
            ctx.user_data["withdraw_step"] = "amount"
            user = await db_get_user(self.db, uid)
            min_pay = await db_get_setting(self.db, self.bot_id, "min_payout", "100")
            await update.message.reply_text(
                f"Enter amount (min ₹{min_pay}, max ₹{user['balance']:.2f}):",
                reply_markup=kb_cancel()
            )
            return

        if withdraw_step == "amount":
            try:
                amount = float(text)
            except ValueError:
                await update.message.reply_text("❌ Invalid amount.", reply_markup=kb_cancel())
                return
            user = await db_get_user(self.db, uid)
            min_pay = float(await db_get_setting(self.db, self.bot_id, "min_payout", "100"))
            if amount < min_pay:
                await update.message.reply_text(f"❌ Minimum: ₹{min_pay:.2f}", reply_markup=kb_cancel())
                return
            if amount > user["balance"]:
                await update.message.reply_text("❌ Insufficient balance.", reply_markup=kb_cancel())
                return
            upi = ctx.user_data["withdraw_upi"]
            await db_deduct_balance(self.db, uid, amount, f"Payout request")
            cur = await self.db.execute(
                "INSERT INTO bet_payouts (user_id, amount, upi_id, status, created_at) VALUES (?,?,?,?,?)",
                (uid, amount, upi, "pending", datetime.utcnow().isoformat())
            )
            await self.db.commit()
            pay_id = cur.lastrowid
            payout_channel = await db_get_setting(self.db, self.bot_id, "payout_channel", None)
            if payout_channel:
                try:
                    await update.get_bot().send_message(
                        payout_channel,
                        f"💸 *Payout Request #{pay_id}*\n\nUser: uid:{uid}\nAmount: ₹{amount:.2f}\nUPI: `{upi}`",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton(f"✅ Approve", callback_data=f"bet_adm_pay_ok_{pay_id}"),
                            InlineKeyboardButton(f"❌ Reject", callback_data=f"bet_adm_pay_rej_{pay_id}"),
                        ]])
                    )
                except Exception: pass
            ctx.user_data.clear()
            await update.message.reply_text(
                f"✅ *Withdrawal Requested!*\n\nAmount: ₹{amount:.2f}\nUPI: `{upi}`\n\n⏳ Processing within 24h.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=back_main_kb
            )
            return

        # ── Custom bet amount ────────────────────────────────────────────────
        if ctx.user_data.get("bet_step") == "custom_amount":
            try:
                amount = float(text)
            except ValueError:
                await update.message.reply_text("❌ Invalid amount.", reply_markup=kb_cancel())
                return
            game = ctx.user_data.get("bet_game", "coin")
            user = await db_get_user(self.db, uid)
            ctx.user_data.clear()
            if user["balance"] < amount:
                await update.message.reply_text(
                    f"❌ Insufficient balance (₹{user['balance']:.2f})", reply_markup=back_main_kb
                )
                return
            if game == "coin":
                await update.message.reply_text(
                    f"🪙 Bet: ₹{amount:.2f}\nPick:", reply_markup=kb_coin_pick(amount)
                )
            elif game == "oe":
                await update.message.reply_text(
                    f"🔢 Bet: ₹{amount:.2f}\nPick:", reply_markup=kb_oddeven_pick(amount)
                )
            elif game == "dice":
                await update.message.reply_text(
                    f"🎯 Bet: ₹{amount:.2f}\nPick:", reply_markup=kb_dice_picks(amount)
                )
            return

        # ── Admin text inputs ────────────────────────────────────────────────
        if not self.is_admin(uid):
            return
        action = ctx.user_data.get("adm_action")
        if not action:
            return

        setting_map = {
            "adm_set_upi_id":  "upi_id",
            "adm_set_min_dep": "min_deposit",
            "adm_set_min_pay": "min_payout",
            "adm_set_pay_ch":  "payout_channel",
        }
        if action in setting_map:
            if action == "adm_set_upi_id" and not validate_upi(text):
                await update.message.reply_text("❌ Invalid UPI ID format.", reply_markup=back_admin_kb)
                ctx.user_data.clear()
                return
            await db_set_setting(self.db, self.bot_id, setting_map[action], text)
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ Setting updated: `{text}`",
                                             parse_mode=ParseMode.MARKDOWN, reply_markup=back_admin_kb)
        elif action == "adm_broadcast":
            users = await self.db.fetchall("SELECT user_id FROM bet_users WHERE banned=0")
            sent = failed = 0
            for u in users:
                try:
                    await update.get_bot().send_message(u["user_id"], text)
                    sent += 1
                except Exception:
                    failed += 1
            ctx.user_data.clear()
            await update.message.reply_text(f"📨 Sent: {sent}, Failed: {failed}", reply_markup=back_admin_kb)
        elif action == "adm_ban":
            try:
                ban_uid = int(text)
                await self.db.execute("UPDATE bet_users SET banned=1 WHERE user_id=?", (ban_uid,))
                await self.db.commit()
                ctx.user_data.clear()
                await update.message.reply_text(f"🚫 User {ban_uid} banned.", reply_markup=back_admin_kb)
            except ValueError:
                await update.message.reply_text("❌ Invalid user ID.")
        elif action == "adm_adjust_uid":
            try:
                ctx.user_data["adjust_uid"] = int(text)
                ctx.user_data["adm_action"] = "adm_adjust_amt"
                await update.message.reply_text("Enter amount (+/-):", reply_markup=kb_cancel("bet_admin"))
            except ValueError:
                await update.message.reply_text("❌ Invalid ID.")
        elif action == "adm_adjust_amt":
            try:
                amt = float(text)
                target = ctx.user_data["adjust_uid"]
                if amt >= 0:
                    await db_add_balance(self.db, target, amt, f"Admin credit by {uid}")
                else:
                    await db_deduct_balance(self.db, target, abs(amt), f"Admin debit by {uid}")
                ctx.user_data.clear()
                await update.message.reply_text(f"✅ Balance adjusted ₹{amt:+.2f} for uid:{target}",
                                                 reply_markup=back_admin_kb)
            except (ValueError, KeyError):
                await update.message.reply_text("❌ Error.")

    async def build_app(self) -> Application:
        for ddl in [
            """CREATE TABLE IF NOT EXISTS bet_users (
                user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '',
                balance REAL DEFAULT 0, total_bet REAL DEFAULT 0,
                total_won REAL DEFAULT 0, banned INTEGER DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS bet_txns (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                amount REAL, type TEXT, note TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS bet_deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                amount REAL, utr TEXT DEFAULT '', status TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS bet_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                amount REAL, upi_id TEXT, status TEXT, created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS bet_settings (
                bot_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(bot_id,key))""",
        ]:
            await self.db.execute(ddl)
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
