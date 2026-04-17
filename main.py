"""
╔══════════════════════════════════════════════════╗
║   ██╗   ██╗ ██████╗ ██╗██████╗                  ║
║   ██║   ██║██╔═══██╗██║██╔══██╗                 ║
║   ██║   ██║██║   ██║██║██║  ██║                 ║
║   ╚██╗ ██╔╝██║   ██║██║██║  ██║                 ║
║    ╚████╔╝ ╚██████╔╝██║██████╔╝                 ║
║     ╚═══╝   ╚═════╝ ╚═╝╚═════╝                  ║
║          BOT  BUILDER  BOT  ⚡                    ║
╚══════════════════════════════════════════════════╝
"""

import logging
import asyncio
from datetime import datetime
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from config import BUILDER_TOKEN, ADMIN_IDS, BOT_VERSION
from database import Database
from bot_manager import BotManager
from templates import BOT_TEMPLATES, get_template_info

logging.basicConfig(
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("⚡ VoidBuilder")

# ── States ─────────────────────────────────────────────────────────────────────
MAIN_MENU, AWAIT_TOKEN, SELECT_TEMPLATE, CONFIRM_DEPLOY = range(4)

db = Database()
bot_mgr = BotManager(db)

# ══════════════════════════════════════════════════════════════════════════════
#                              🎨  BANNERS & ART
# ══════════════════════════════════════════════════════════════════════════════

VOID_LOGO = (
    "```\n"
    "╔═══════════════════════════════════╗\n"
    "║  ⚡  VOID  BOT  BUILDER  ⚡        ║\n"
    "║  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  ║\n"
    "║    🤖 Build · Deploy · Dominate   ║\n"
    "╚═══════════════════════════════════╝\n"
    "```"
)

DIVIDER      = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
DIVIDER_BOLD = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"


def welcome_msg(name: str, total: int, user_bots: int) -> str:
    return (
        f"{VOID_LOGO}\n"
        f"👋 Yo **{name}**! Welcome to the most powerful bot factory!\n\n"
        f"⚡ **VOID BOT BUILDER** can deploy fully working Telegram bots\n"
        f"in under 10 seconds — just paste a token!\n\n"
        f"🏭 **8 Premium Templates Available:**\n"
        f"  💎  Polygon Auto Pay Bot\n"
        f"  🎁  Refer & Earn Bot\n"
        f"  🚀  Advanced Refer & Earn\n"
        f"  🎯  Quiz & Trivia Bot\n"
        f"  📢  Mass Broadcast Bot\n"
        f"  👋  Group Welcome Manager\n"
        f"  🎰  Lucky Draw & Lottery Bot\n"
        f"  🛒  Mini Shop Bot\n\n"
        f"{DIVIDER_BOLD}\n"
        f"🌍 **{total}** bots running worldwide  |  🤖 You have **{user_bots}**\n"
        f"⚡ Version **{BOT_VERSION}**"
    )


# ══════════════════════════════════════════════════════════════════════════════
#                            🎛️  KEYBOARD BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def main_kb(uid: int) -> InlineKeyboardMarkup:
    cnt = db.count_user_bots(uid)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Add New Bot", callback_data="add_bot"),
            InlineKeyboardButton(f"🤖 My Bots [{cnt}]", callback_data="my_bots"),
        ],
        [
            InlineKeyboardButton("🛍️ Templates Store", callback_data="templates"),
            InlineKeyboardButton("📊 Live Stats", callback_data="stats"),
        ],
        [
            InlineKeyboardButton("📖 How It Works", callback_data="howto"),
            InlineKeyboardButton("👑 Admin Panel", callback_data="admin"),
        ],
        [
            InlineKeyboardButton("💬 Support", url="https://t.me/VoidSupport"),
            InlineKeyboardButton("📢 Channel", url="https://t.me/VoidBuilderBot"),
        ],
    ])


def back_kb(cb="main_menu") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data=cb)]])


def templates_kb() -> InlineKeyboardMarkup:
    rows = []
    for tid, t in BOT_TEMPLATES.items():
        badge = "🔥 NEW" if t.get("new") else ("⭐" * t["stars"])
        rows.append([InlineKeyboardButton(
            f"{t['emoji']}  {t['name']}  {badge}",
            callback_data=f"tpl_{tid}"
        )])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def mybots_kb(bots: list) -> InlineKeyboardMarkup:
    rows = []
    for b in bots:
        icon = "🟢" if b["status"] == "running" else "🔴"
        rows.append([InlineKeyboardButton(
            f"{icon} @{b['username']}  ·  {b['template_name']}",
            callback_data=f"bmenu_{b['id']}"
        )])
    rows.append([InlineKeyboardButton("➕ Add Bot", callback_data="add_bot"),
                 InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)


def bot_panel_kb(bid: int, status: str) -> InlineKeyboardMarkup:
    t_label = "⏸️ Stop" if status == "running" else "▶️ Start"
    t_cb    = f"bstop_{bid}" if status == "running" else f"bstart_{bid}"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t_label, callback_data=t_cb),
            InlineKeyboardButton("🔄 Restart", callback_data=f"brestart_{bid}"),
            InlineKeyboardButton("📊 Stats", callback_data=f"bstats_{bid}"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data=f"bsettings_{bid}"),
            InlineKeyboardButton("🗑️ Delete", callback_data=f"bdelete_confirm_{bid}"),
        ],
        [InlineKeyboardButton("🔙 My Bots", callback_data="my_bots")],
    ])


def delete_confirm_kb(bid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ Yes, Delete Forever", callback_data=f"bdelete_{bid}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"bmenu_{bid}"),
        ]
    ])


# ══════════════════════════════════════════════════════════════════════════════
#                          🚀  COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    db.upsert_user(user.id, user.username or "", user.first_name or "User")
    total = db.count_all_bots()
    ucnt  = db.count_user_bots(user.id)
    msg   = welcome_msg(user.first_name or "Friend", total, ucnt)
    kb    = main_kb(user.id)
    if update.message:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    ctx.user_data.clear()
    return MAIN_MENU


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "⚡ **VOID BOT BUILDER — Help**\n\n"
        f"{DIVIDER_BOLD}\n"
        "**Commands:**\n"
        "/start   — 🏠 Main menu\n"
        "/addbot  — ➕ Deploy a new bot\n"
        "/mybots  — 🤖 Manage your bots\n"
        "/stats   — 📊 Global statistics\n"
        "/help    — ❓ This message\n\n"
        f"{DIVIDER_BOLD}\n"
        "**How to get a Bot Token:**\n"
        "1️⃣ Open @BotFather → /newbot\n"
        "2️⃣ Follow the steps\n"
        "3️⃣ Copy the token → paste here\n\n"
        "Support: @VoidSupport"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_addbot(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    ctx.user_data.clear()
    return await _show_token_input(update, ctx)


async def cmd_mybots(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    return await _show_mybots(update, ctx)


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    s = db.get_global_stats()
    msg = _build_stats_msg(s)
    await update.message.reply_text(msg, reply_markup=back_kb(), parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
#                          🎛️  CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════════════════════

async def cb_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q    = update.callback_query
    await q.answer()
    data = q.data
    uid  = q.from_user.id

    # ── Navigation ─────────────────────────────────────────────────────────
    if data == "main_menu":       return await cmd_start(update, ctx)
    if data == "add_bot":         return await cmd_addbot(update, ctx)
    if data == "my_bots":         return await _show_mybots(update, ctx)
    if data == "stats":           return await _show_stats(update, ctx)
    if data == "templates":       return await _show_templates(update, ctx)
    if data == "howto":           return await _show_howto(update, ctx)
    if data == "admin":           return await _show_admin(update, ctx)

    # ── Template Detail ─────────────────────────────────────────────────────
    if data.startswith("tpl_"):
        return await _show_template_detail(update, ctx, data[4:])

    # ── Deploy from template page ────────────────────────────────────────────
    if data.startswith("deploy_"):
        ctx.user_data["selected_template"] = data[7:]
        return await _show_token_input(update, ctx)

    # ── Bot Management ───────────────────────────────────────────────────────
    if data.startswith("bmenu_"):        return await _bot_panel(update, ctx, int(data[6:]))
    if data.startswith("bstop_"):
        bid = int(data[6:])
        bot_mgr.stop_bot(bid); db.update_bot_status(bid, "stopped")
        await q.answer("⏸️ Stopped!", show_alert=True)
        return await _bot_panel(update, ctx, bid)
    if data.startswith("bstart_"):
        bid = int(data[7:])
        bd  = db.get_bot(bid)
        if bd: await bot_mgr.start_bot(bd); db.update_bot_status(bid, "running")
        await q.answer("▶️ Started!", show_alert=True)
        return await _bot_panel(update, ctx, bid)
    if data.startswith("brestart_"):
        bid = int(data[9:])
        bot_mgr.stop_bot(bid)
        bd  = db.get_bot(bid)
        if bd: await asyncio.sleep(1); await bot_mgr.start_bot(bd); db.update_bot_status(bid, "running")
        await q.answer("🔄 Restarted!", show_alert=True)
        return await _bot_panel(update, ctx, bid)
    if data.startswith("bstats_"):       return await _bot_stats(update, ctx, int(data[7:]))
    if data.startswith("bsettings_"):    return await _bot_settings(update, ctx, int(data[10:]))
    if data.startswith("bdelete_confirm_"):
        bid = int(data[16:])
        await q.edit_message_text(
            f"⚠️ **Delete Bot?**\n\nThis will permanently remove the bot and all its data.\nThis cannot be undone!",
            reply_markup=delete_confirm_kb(bid), parse_mode="Markdown"
        )
        return MAIN_MENU
    if data.startswith("bdelete_"):
        bid = int(data[8:])
        bot_mgr.stop_bot(bid); db.delete_bot(bid)
        await q.answer("🗑️ Deleted!", show_alert=True)
        return await _show_mybots(update, ctx)

    # ── Deploy flow ──────────────────────────────────────────────────────────
    if data == "confirm_deploy":  return await _deploy_bot(update, ctx)
    if data == "cancel_deploy":
        ctx.user_data.clear()
        return await cmd_start(update, ctx)

    # ── Admin actions ────────────────────────────────────────────────────────
    if data == "admin_allbots":   return await _admin_allbots(update, ctx)
    if data == "admin_restart_all":
        bots = db.get_all_running_bots()
        await q.edit_message_text(f"♻️ Restarting {len(bots)} bots...", parse_mode="Markdown")
        await bot_mgr.restart_all_running()
        await q.edit_message_text(f"✅ Restarted {len(bots)} bots!", reply_markup=back_kb("admin"))
        return MAIN_MENU

    return MAIN_MENU


# ══════════════════════════════════════════════════════════════════════════════
#                          📥  TOKEN INPUT FLOW
# ══════════════════════════════════════════════════════════════════════════════

async def _show_token_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    pre_tpl = ctx.user_data.get("selected_template")
    pre_info = get_template_info(pre_tpl) if pre_tpl else None
    pre_line = f"\n✨ Template pre-selected: {pre_info['emoji']} **{pre_info['name']}**\n" if pre_info else ""
    msg = (
        f"➕ **ADD YOUR BOT**\n\n"
        f"{DIVIDER_BOLD}\n"
        f"📋 Step 1 of 3 — **Enter Bot Token**\n"
        f"{DIVIDER_BOLD}\n"
        f"{pre_line}\n"
        f"To get your token:\n"
        f"1️⃣ Open [@BotFather](https://t.me/BotFather)\n"
        f"2️⃣ Send `/newbot` → follow steps\n"
        f"3️⃣ Copy the token\n\n"
        f"🔐 Format: `1234567890:ABCdefGhi...`\n\n"
        f"⬇️ **Paste your token now:**"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="main_menu")]])
    if update.message:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return AWAIT_TOKEN


async def msg_token(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    token = update.message.text.strip()
    if ":" not in token or len(token) < 30:
        await update.message.reply_text(
            "❌ **Invalid format!**\n\nExpected: `1234567890:ABCdef...`\n\nTry again:",
            parse_mode="Markdown"
        )
        return AWAIT_TOKEN

    pm = await update.message.reply_text("⏳ Connecting to Telegram API...")
    try:
        test = Application.builder().token(token).build()
        bi   = await test.bot.get_me()
        await test.shutdown()
    except Exception:
        await pm.edit_text("❌ **Invalid Token!**\nCould not authenticate. Check & retry.", parse_mode="Markdown")
        return AWAIT_TOKEN

    if db.bot_token_exists(token):
        await pm.edit_text(
            f"⚠️ **Already Registered!**\n@{bi.username} is already in your panel.\nUse /mybots",
            parse_mode="Markdown"
        )
        return MAIN_MENU

    ctx.user_data.update({"token": token, "bot_username": bi.username, "bot_name": bi.first_name})
    await pm.edit_text(
        f"✅ **Token Verified!**\n\n🤖 Bot: **@{bi.username}**\n📛 Name: {bi.first_name}\n\nNow choose a template 👇",
        parse_mode="Markdown"
    )

    pre = ctx.user_data.pop("selected_template", None)
    if pre:
        ctx.user_data["selected_template"] = pre
        info = get_template_info(pre)
        kb   = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Deploy!", callback_data="confirm_deploy"),
             InlineKeyboardButton("❌ Cancel",  callback_data="cancel_deploy")]
        ])
        await update.message.reply_text(
            f"✅ **Confirm Deployment**\n\n{DIVIDER_BOLD}\n"
            f"🤖 Bot: @{bi.username}\n{info['emoji']} Template: **{info['name']}**\n{DIVIDER_BOLD}",
            reply_markup=kb, parse_mode="Markdown"
        )
        return CONFIRM_DEPLOY

    # Show template selection
    msg = (
        f"🛍️ **Step 2 of 3 — Choose Template**\n\n"
        f"{DIVIDER}\nPick the bot type to deploy on @{bi.username}:\n{DIVIDER}"
    )
    await update.message.reply_text(msg, reply_markup=templates_kb(), parse_mode="Markdown")
    return SELECT_TEMPLATE


async def cb_template_select(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q    = update.callback_query
    await q.answer()
    data = q.data

    if data == "main_menu":
        ctx.user_data.clear()
        return await cmd_start(update, ctx)

    if not data.startswith("tpl_"):
        return SELECT_TEMPLATE

    tid  = data[4:]
    info = get_template_info(tid)
    if not info:
        await q.answer("Not found!", show_alert=True)
        return SELECT_TEMPLATE

    ctx.user_data["selected_template"] = tid
    uname = ctx.user_data.get("bot_username", "?")
    tok   = ctx.user_data.get("token", "")
    ts    = tok[:14] + "..." if len(tok) > 14 else tok

    feats = "\n".join([f"  ✅ {f}" for f in info["features"][:4]])
    msg   = (
        f"📋 **Step 3 of 3 — Confirm**\n\n"
        f"{DIVIDER_BOLD}\n"
        f"🤖  Bot:        @{uname}\n"
        f"{info['emoji']}  Template:   {info['name']}\n"
        f"🔑  Token:      `{ts}`\n"
        f"{DIVIDER_BOLD}\n\n"
        f"🔥 **Included features:**\n{feats}\n\n"
        f"🚀 Tap Deploy — your bot goes live instantly!"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Deploy Now!", callback_data="confirm_deploy"),
         InlineKeyboardButton("❌ Cancel",      callback_data="cancel_deploy")],
        [InlineKeyboardButton("🔙 Change Template", callback_data="back_template")],
    ])
    await q.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return CONFIRM_DEPLOY


async def cb_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q   = update.callback_query
    await q.answer()
    if q.data == "back_template":
        ctx.user_data.pop("selected_template", None)
        await q.edit_message_text("🛍️ Choose a template:", reply_markup=templates_kb(), parse_mode="Markdown")
        return SELECT_TEMPLATE
    if q.data == "cancel_deploy":
        ctx.user_data.clear()
        return await cmd_start(update, ctx)
    if q.data == "confirm_deploy":
        return await _deploy_bot(update, ctx)
    return CONFIRM_DEPLOY


async def _deploy_bot(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    q     = update.callback_query
    uid   = q.from_user.id
    token = ctx.user_data.get("token")
    tid   = ctx.user_data.get("selected_template")
    uname = ctx.user_data.get("bot_username", "unknown")
    name  = ctx.user_data.get("bot_name", "Bot")

    if not token or not tid:
        await q.edit_message_text("❌ Session expired. /start again.")
        return MAIN_MENU

    info = get_template_info(tid)
    await q.edit_message_text(
        f"⚙️ **Deploying @{uname}...**\n\n"
        f"┣ {info['emoji']} Loading {info['name']}\n"
        f"┣ 🔌 Connecting to Telegram\n"
        f"┗ ⏳ Starting bot engine...",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1)

    bot_id  = db.add_bot(owner_id=uid, token=token, username=uname,
                         name=name, template_id=tid, template_name=info["name"])
    bd      = db.get_bot(bot_id)
    success = await bot_mgr.start_bot(bd)

    if success:
        db.update_bot_status(bot_id, "running")
        msg = (
            f"🎊 **DEPLOYED SUCCESSFULLY!**\n\n"
            f"╔{'═'*30}╗\n"
            f"║  ✅  STATUS: LIVE & RUNNING 🟢    ║\n"
            f"╚{'═'*30}╝\n\n"
            f"🤖 Bot:      @{uname}\n"
            f"{info['emoji']} Template: {info['name']}\n"
            f"🆔 Bot ID:   #{bot_id}\n"
            f"📅 Deployed: {datetime.now().strftime('%d %b %Y  %H:%M')}\n\n"
            f"🔗 [Open @{uname}](https://t.me/{uname}) — It's live! 🎉"
        )
    else:
        msg = (
            f"⚠️ **Registered — Starting Soon**\n\n"
            f"@{uname} with {info['name']} is registered.\n"
            f"Check /mybots in a moment."
        )

    ctx.user_data.clear()
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 My Bots",    callback_data="my_bots"),
         InlineKeyboardButton("➕ Add Another", callback_data="add_bot")],
        [InlineKeyboardButton("🏠 Main Menu",   callback_data="main_menu")],
    ])
    await q.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU


# ══════════════════════════════════════════════════════════════════════════════
#                          📟  DISPLAY SECTIONS
# ══════════════════════════════════════════════════════════════════════════════

async def _show_mybots(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid  = update.effective_user.id
    bots = db.get_user_bots(uid)
    if not bots:
        msg = (
            "🤖 **My Bots**\n\n"
            "You haven't deployed any bots yet!\n\n"
            "Tap ➕ to deploy your first bot in seconds 🚀"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Deploy First Bot", callback_data="add_bot")],
            [InlineKeyboardButton("🔙 Back",             callback_data="main_menu")],
        ])
    else:
        run = sum(1 for b in bots if b["status"] == "running")
        msg = (
            f"🤖 **My Bots** — {len(bots)} deployed\n\n"
            f"🟢 Running: **{run}**   🔴 Stopped: **{len(bots)-run}**\n\n"
            f"{DIVIDER}\nSelect a bot to manage:\n{DIVIDER}"
        )
        kb = mybots_kb(bots)

    if update.message:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU


async def _bot_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE, bid: int) -> int:
    b = db.get_bot(bid)
    if not b:
        await update.callback_query.answer("Bot not found!", show_alert=True)
        return MAIN_MENU
    icon = "🟢 Running" if b["status"] == "running" else "🔴 Stopped"
    info = get_template_info(b["template_id"]) or {}
    st   = db.get_bot_stats(bid)
    msg  = (
        f"{info.get('emoji','🤖')} **@{b['username']}**\n\n"
        f"{DIVIDER_BOLD}\n"
        f"📛 Name:       {b['name']}\n"
        f"📋 Template:  {b['template_name']}\n"
        f"📊 Status:     {icon}\n"
        f"👥 Users:      {st.get('users',0)}\n"
        f"💬 Msgs:       {st.get('messages',0)}\n"
        f"🆔 ID:          #{bid}\n"
        f"📅 Since:      {str(b.get('created_at',''))[:10]}\n"
        f"{DIVIDER_BOLD}"
    )
    await update.callback_query.edit_message_text(
        msg, reply_markup=bot_panel_kb(bid, b["status"]), parse_mode="Markdown"
    )
    return MAIN_MENU


async def _bot_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE, bid: int) -> int:
    b  = db.get_bot(bid)
    if not b: return MAIN_MENU
    st = db.get_bot_stats(bid)
    msg = (
        f"📊 **Detailed Stats — @{b['username']}**\n\n"
        f"{DIVIDER_BOLD}\n"
        f"👥 Total Users:    {st.get('users',0)}\n"
        f"💬 Messages:       {st.get('messages',0)}\n"
        f"🔗 Referrals:       {st.get('referrals',0)}\n"
        f"💳 Transactions:   {st.get('transactions',0)}\n"
        f"📅 Last Active:    {st.get('last_ping','N/A')}\n"
        f"{DIVIDER_BOLD}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"bmenu_{bid}")]])
    await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU


async def _bot_settings(update: Update, ctx: ContextTypes.DEFAULT_TYPE, bid: int) -> int:
    b = db.get_bot(bid)
    if not b: return MAIN_MENU
    msg = (
        f"⚙️ **Bot Settings — @{b['username']}**\n\n"
        f"🤖 Template: {b['template_name']}\n\n"
        f"Settings are configured directly within your bot.\n"
        f"Start your bot and use admin commands inside it."
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"bmenu_{bid}")]])
    await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU


async def _show_template_detail(update: Update, ctx: ContextTypes.DEFAULT_TYPE, tid: str) -> int:
    info = get_template_info(tid)
    if not info:
        await update.callback_query.answer("Not found!", show_alert=True)
        return MAIN_MENU
    feats = "\n".join([f"  ✅ {f}" for f in info["features"]])
    badge = "🔥 NEW TEMPLATE" if info.get("new") else f"{'⭐'*info['stars']} Rating"
    msg   = (
        f"{info['emoji']} **{info['name']}**\n"
        f"{badge} · 📂 {info['category']}\n\n"
        f"💬 _{info['description']}_\n\n"
        f"{DIVIDER}\n"
        f"🔥 **All Features:**\n{feats}\n{DIVIDER}\n\n"
        f"⚙️ Complexity: **{info['complexity']}**\n"
        f"👥 Best For: _{info['best_for']}_"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Deploy This Bot", callback_data=f"deploy_{tid}")],
        [InlineKeyboardButton("🔙 All Templates",   callback_data="templates")],
    ])
    await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU


async def _show_templates(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = (
        f"🛍️ **VOID TEMPLATES STORE**\n\n"
        f"{DIVIDER_BOLD}\n"
        f"8 premium templates — all included FREE\n"
        f"{DIVIDER_BOLD}\n\n"
        f"Tap any template to view details & deploy:"
    )
    await update.callback_query.edit_message_text(
        msg, reply_markup=templates_kb(), parse_mode="Markdown"
    )
    return MAIN_MENU


async def _show_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    s   = db.get_global_stats()
    msg = _build_stats_msg(s)
    await update.callback_query.edit_message_text(msg, reply_markup=back_kb(), parse_mode="Markdown")
    return MAIN_MENU


def _build_stats_msg(s: dict) -> str:
    lines = [
        f"📊 **VOID BOT BUILDER — Live Stats**\n",
        f"{DIVIDER_BOLD}",
        f"🌍 Total Bots Deployed:   **{s['total_bots']}**",
        f"🟢 Currently Running:      **{s['running_bots']}**",
        f"👥 Registered Users:        **{s['total_users']}**",
        f"🚀 Deployed Today:           **{s['today_deploys']}**",
        f"{DIVIDER_BOLD}",
        f"\n🏆 **Top Templates:**",
    ]
    for i, (name, cnt) in enumerate(s.get("top_templates", []), 1):
        bars = "█" * min(cnt, 10) + "░" * max(0, 10 - cnt)
        lines.append(f"  {i}. {name}\n     {bars} {cnt}")
    lines.append(f"\n⚡ Void Bot Builder v**{BOT_VERSION}**")
    return "\n".join(lines)


async def _show_howto(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    msg = (
        f"📖 **HOW VOID BOT BUILDER WORKS**\n\n"
        f"{DIVIDER_BOLD}\n\n"
        f"**STEP 1️⃣ — Create Your Bot**\n"
        f"┣ Open [@BotFather](https://t.me/BotFather)\n"
        f"┣ Send /newbot → fill details\n"
        f"┗ Copy the API token\n\n"
        f"**STEP 2️⃣ — Paste Token**\n"
        f"┣ Tap ➕ Add New Bot\n"
        f"┗ Paste token — verified instantly ✅\n\n"
        f"**STEP 3️⃣ — Choose Template**\n"
        f"┣ 💎 Polygon Auto Pay Bot\n"
        f"┣ 🎁 Refer & Earn\n"
        f"┣ 🚀 Advanced Refer & Earn\n"
        f"┣ 🎯 Quiz Bot\n"
        f"┣ 📢 Broadcast Bot\n"
        f"┣ 👋 Group Welcome Bot\n"
        f"┣ 🎰 Lucky Draw Bot\n"
        f"┗ 🛒 Mini Shop Bot\n\n"
        f"**STEP 4️⃣ — Live in Seconds! 🎉**\n"
        f"┗ Manage from My Bots panel\n\n"
        f"{DIVIDER_BOLD}\n"
        f"❓ Support: [@VoidSupport](https://t.me/VoidSupport)"
    )
    await update.callback_query.edit_message_text(msg, reply_markup=back_kb(), parse_mode="Markdown")
    return MAIN_MENU


async def _show_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.callback_query.answer("⛔ Admins only!", show_alert=True)
        return MAIN_MENU
    s   = db.get_global_stats()
    msg = (
        f"👑 **VOID ADMIN PANEL**\n\n"
        f"{DIVIDER_BOLD}\n"
        f"🌍 Bots: {s['total_bots']}  🟢 Running: {s['running_bots']}\n"
        f"👥 Users: {s['total_users']}  🚀 Today: {s['today_deploys']}\n"
        f"{DIVIDER_BOLD}"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 All Bots",        callback_data="admin_allbots"),
         InlineKeyboardButton("♻️ Restart All",     callback_data="admin_restart_all")],
        [InlineKeyboardButton("📊 Full Stats",      callback_data="stats"),
         InlineKeyboardButton("📢 Broadcast",       callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 Back",            callback_data="main_menu")],
    ])
    await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="Markdown")
    return MAIN_MENU


async def _admin_allbots(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        await update.callback_query.answer("⛔", show_alert=True)
        return MAIN_MENU
    all_bots = db.get_all_bots()
    lines    = [f"📋 **All Bots ({len(all_bots)})**\n"]
    for b in all_bots[:20]:
        icon = "🟢" if b["status"] == "running" else "🔴"
        lines.append(f"{icon} @{b['username']} — {b['template_name']}")
    if len(all_bots) > 20:
        lines.append(f"\n...and {len(all_bots)-20} more")
    await update.callback_query.edit_message_text(
        "\n".join(lines), reply_markup=back_kb("admin"), parse_mode="Markdown"
    )
    return MAIN_MENU


# ══════════════════════════════════════════════════════════════════════════════
#                              🏁  MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    logger.info("⚡ Void Bot Builder starting...")
    db.init()

    app = Application.builder().token(BUILDER_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start",   cmd_start),
            CommandHandler("addbot",  cmd_addbot),
            CommandHandler("mybots",  cmd_mybots),
        ],
        states={
            MAIN_MENU: [
                CallbackQueryHandler(cb_router),
            ],
            AWAIT_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, msg_token),
                CallbackQueryHandler(cb_router),
            ],
            SELECT_TEMPLATE: [
                CallbackQueryHandler(cb_template_select),
            ],
            CONFIRM_DEPLOY: [
                CallbackQueryHandler(cb_confirm),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("stats", cmd_stats))

    async def post_init(application):
        await application.bot.set_my_commands([
            ("start",  "⚡ Main menu"),
            ("addbot", "➕ Deploy a new bot"),
            ("mybots", "🤖 Manage your bots"),
            ("stats",  "📊 Global statistics"),
            ("help",   "❓ Help guide"),
        ])
        await bot_mgr.restart_all_running(application)
        logger.info("✅ Void Bot Builder is LIVE!")

    app.post_init = post_init
    logger.info("🚀 Polling started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
