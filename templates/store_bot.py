"""
templates/store_bot.py
=======================
Advanced Digital Store Bot
- Sell items/services via Telegram
- Payment: UPI (manual verify) + Crypto (admin sets wallet address)
- Admin manages: products, categories, prices, stock, payment methods
- Order queue with approval flow
- Delivery: admin sends file/message to buyer after approval
- Full keyboard UI with back/cancel on every screen
- No "buy" errors — every edge case handled
"""
from __future__ import annotations

import logging
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
    "id":          "store_bot",
    "name":        "Digital Store",
    "emoji":       "🛒",
    "category":    "Commerce",
    "description": "Sell items/services with UPI & Crypto payments, full admin panel",
    "features":    [
        "Product catalog with categories",
        "UPI manual payment + verify flow",
        "Crypto wallet payment (BTC/ETH/USDT)",
        "Admin manages products, stock, prices",
        "Order queue with approve/reject",
        "Auto-deliver digital goods after approval",
        "Order history for buyers",
        "Admin broadcast & revenue stats",
    ],
    "complexity":  "Advanced",
    "best_for":    "Digital product sellers, service providers",
    "stars":       5,
    "new":         True,
}

UPI_PATTERN = re.compile(r'^[\w.\-]{2,256}@[a-zA-Z]{2,64}$')

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main(is_admin=False):
    buttons = [
        [InlineKeyboardButton("🛍 Browse Products", callback_data="store_browse"),
         InlineKeyboardButton("📦 My Orders", callback_data="store_my_orders")],
        [InlineKeyboardButton("💳 Payment Methods", callback_data="store_payment_info"),
         InlineKeyboardButton("ℹ️ About Store", callback_data="store_about")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="store_admin")])
    return InlineKeyboardMarkup(buttons)

def kb_back(target="store_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=target)]])

def kb_cancel(target="store_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data=target)]])

def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Add Product", callback_data="adm_add_product"),
         InlineKeyboardButton("📋 List Products", callback_data="adm_list_products")],
        [InlineKeyboardButton("🏦 Set UPI ID", callback_data="adm_set_upi"),
         InlineKeyboardButton("₿ Set Crypto Wallet", callback_data="adm_set_crypto")],
        [InlineKeyboardButton("📋 Pending Orders", callback_data="adm_pending_orders"),
         InlineKeyboardButton("📈 Revenue Stats", callback_data="adm_stats")],
        [InlineKeyboardButton("📨 Broadcast", callback_data="adm_broadcast"),
         InlineKeyboardButton("🗑 Delete Product", callback_data="adm_del_product")],
        [InlineKeyboardButton("🔔 Order Channel", callback_data="adm_set_order_ch"),
         InlineKeyboardButton("✏️ Edit Product", callback_data="adm_edit_product")],
        [InlineKeyboardButton("⬅️ Back", callback_data="store_main")],
    ])

def kb_pay_method(product_id, amount):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏦 Pay via UPI", callback_data=f"pay_upi_{product_id}_{amount}")],
        [InlineKeyboardButton("₿ Pay via Crypto", callback_data=f"pay_crypto_{product_id}_{amount}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"store_product_{product_id}")],
    ])

def kb_verify_payment(order_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ I've Paid — Submit for Verification", callback_data=f"pay_verify_{order_id}")],
        [InlineKeyboardButton("❌ Cancel Order", callback_data=f"pay_cancel_{order_id}")],
    ])

# ── DB helpers ────────────────────────────────────────────────────────────────

async def db_get_setting(db, bot_id, key, default=None):
    row = await db.fetchone("SELECT value FROM store_settings WHERE bot_id=? AND key=?", (bot_id, key))
    return row["value"] if row else default

async def db_set_setting(db, bot_id, key, value):
    await db.execute("""
        INSERT INTO store_settings(bot_id,key,value) VALUES(?,?,?)
        ON CONFLICT(bot_id,key) DO UPDATE SET value=excluded.value
    """, (bot_id, key, str(value)))
    await db.commit()

async def db_ensure_user(db, uid, username):
    await db.execute("""
        INSERT OR IGNORE INTO store_users(user_id,username,joined_at)
        VALUES(?,?,?)
    """, (uid, username or "", datetime.utcnow().isoformat()))
    await db.commit()

async def db_get_categories(db, bot_id):
    return await db.fetchall(
        "SELECT DISTINCT category FROM store_products WHERE bot_id=? AND active=1", (bot_id,)
    )

async def db_get_products(db, bot_id, category=None):
    if category:
        return await db.fetchall(
            "SELECT * FROM store_products WHERE bot_id=? AND active=1 AND category=?", (bot_id, category)
        )
    return await db.fetchall("SELECT * FROM store_products WHERE bot_id=? AND active=1", (bot_id,))

async def db_get_product(db, pid):
    row = await db.fetchone("SELECT * FROM store_products WHERE id=?", (pid,))
    return dict(row) if row else None

async def db_create_order(db, uid, product_id, amount, method) -> int:
    cur = await db.execute("""
        INSERT INTO store_orders(user_id, product_id, amount, pay_method, status, created_at)
        VALUES(?,?,?,?,?,?)
    """, (uid, product_id, amount, method, "pending_payment", datetime.utcnow().isoformat()))
    await db.commit()
    return cur.lastrowid

# ── Template ──────────────────────────────────────────────────────────────────

class Template(BaseTemplate):

    # ── /start ────────────────────────────────────────────────────────────────
    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        await db_ensure_user(self.db, uid, update.effective_user.username)
        store_name = await db_get_setting(self.db, self.bot_id, "store_name", "Our Store")
        store_desc = await db_get_setting(self.db, self.bot_id, "store_desc", "Welcome! Browse our products below.")
        await update.message.reply_text(
            f"🛒 *{store_name}*\n\n{store_desc}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(self.is_admin(uid))
        )

    # ── Callback router ───────────────────────────────────────────────────────
    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        data = q.data
        await db_ensure_user(self.db, uid, q.from_user.username)

        # ── Main navigation ────────────────────────────────────────────────
        if data == "store_main":
            ctx.user_data.clear()
            store_name = await db_get_setting(self.db, self.bot_id, "store_name", "Our Store")
            await q.edit_message_text(
                f"🛒 *{store_name}*\n\nBrowse our products:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(self.is_admin(uid))
            )

        elif data == "store_browse":
            await self._show_categories(q)

        elif data.startswith("store_cat_"):
            cat = data.replace("store_cat_", "")
            await self._show_products(q, cat)

        elif data.startswith("store_product_"):
            pid = int(data.replace("store_product_", ""))
            await self._show_product(q, pid)

        elif data.startswith("store_buy_"):
            pid = int(data.replace("store_buy_", ""))
            await self._start_buy(q, uid, pid, ctx)

        elif data.startswith("pay_upi_"):
            parts = data.split("_")
            pid, amount = int(parts[2]), float(parts[3])
            await self._pay_upi(q, uid, pid, amount, ctx)

        elif data.startswith("pay_crypto_"):
            parts = data.split("_")
            pid, amount = int(parts[2]), float(parts[3])
            await self._pay_crypto(q, uid, pid, amount, ctx)

        elif data.startswith("pay_verify_"):
            order_id = int(data.replace("pay_verify_", ""))
            await self._verify_payment(q, uid, order_id, ctx)

        elif data.startswith("pay_cancel_"):
            order_id = int(data.replace("pay_cancel_", ""))
            await self.db.execute(
                "UPDATE store_orders SET status='cancelled' WHERE id=? AND user_id=?", (order_id, uid)
            )
            await self.db.commit()
            await q.edit_message_text("❌ Order cancelled.", reply_markup=kb_back())

        elif data == "store_my_orders":
            await self._show_my_orders(q, uid)

        elif data == "store_payment_info":
            await self._show_payment_info(q)

        elif data == "store_about":
            store_name = await db_get_setting(self.db, self.bot_id, "store_name", "Our Store")
            store_desc = await db_get_setting(self.db, self.bot_id, "store_desc", "Quality products at great prices.")
            await q.edit_message_text(
                f"ℹ️ *About {store_name}*\n\n{store_desc}\n\n"
                f"💬 For support, contact the admin.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back()
            )

        # ── Admin ──────────────────────────────────────────────────────────
        elif data == "store_admin":
            if not self.is_admin(uid):
                await q.answer("⛔ Not authorized", show_alert=True)
                return
            await q.edit_message_text("🔧 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=kb_admin())

        elif data.startswith("adm_"):
            if not self.is_admin(uid):
                await q.answer("⛔ Not authorized", show_alert=True)
                return
            await self._handle_admin_cb(q, uid, ctx, data)

        # ── Admin order actions ────────────────────────────────────────────
        elif data.startswith("order_approve_"):
            if not self.is_admin(uid): return
            order_id = int(data.replace("order_approve_", ""))
            await self._approve_order(q, uid, order_id, ctx)

        elif data.startswith("order_reject_"):
            if not self.is_admin(uid): return
            order_id = int(data.replace("order_reject_", ""))
            await self._reject_order(q, order_id)

    # ── Store screens ─────────────────────────────────────────────────────────

    async def _show_categories(self, q):
        cats = await db_get_categories(self.db, self.bot_id)
        if not cats:
            await q.edit_message_text(
                "🛍 No products available yet. Check back soon!",
                reply_markup=kb_back()
            )
            return
        buttons = []
        for c in cats:
            cat = c["category"]
            buttons.append([InlineKeyboardButton(f"📂 {cat}", callback_data=f"store_cat_{cat}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="store_main")])
        await q.edit_message_text(
            "🛍 *Browse Products*\n\nSelect a category:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def _show_products(self, q, category: str):
        products = await db_get_products(self.db, self.bot_id, category)
        if not products:
            await q.edit_message_text("📭 No products in this category.", reply_markup=kb_back("store_browse"))
            return
        buttons = []
        for p in products:
            stock_label = f" [Out of Stock]" if p["stock"] == 0 else ""
            buttons.append([InlineKeyboardButton(
                f"{p['name']} — ₹{p['price']:.0f}{stock_label}",
                callback_data=f"store_product_{p['id']}"
            )])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="store_browse")])
        await q.edit_message_text(
            f"📂 *{category}*\n\nSelect a product:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def _show_product(self, q, pid: int):
        p = await db_get_product(self.db, pid)
        if not p:
            await q.edit_message_text("❌ Product not found.", reply_markup=kb_back("store_browse"))
            return
        stock_text = "✅ In Stock" if p["stock"] > 0 or p["stock"] == -1 else "❌ Out of Stock"
        text = (
            f"📦 *{p['name']}*\n\n"
            f"{p['description']}\n\n"
            f"💰 Price: ₹{p['price']:.2f}\n"
            f"📊 Status: {stock_text}\n"
            f"🏷 Category: {p['category']}"
        )
        buttons = []
        if p["stock"] != 0:
            buttons.append([InlineKeyboardButton("🛒 Buy Now", callback_data=f"store_buy_{pid}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"store_cat_{p['category']}")])
        await q.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                   reply_markup=InlineKeyboardMarkup(buttons))

    async def _start_buy(self, q, uid, pid: int, ctx):
        p = await db_get_product(self.db, pid)
        if not p or p["stock"] == 0:
            await q.edit_message_text("❌ Product unavailable.", reply_markup=kb_back("store_browse"))
            return
        upi = await db_get_setting(self.db, self.bot_id, "upi_id", None)
        crypto = await db_get_setting(self.db, self.bot_id, "crypto_wallet", None)
        if not upi and not crypto:
            await q.edit_message_text(
                "❌ No payment methods configured yet. Contact admin.",
                reply_markup=kb_back("store_browse")
            )
            return
        buttons = []
        if upi:
            buttons.append([InlineKeyboardButton("🏦 Pay via UPI", callback_data=f"pay_upi_{pid}_{p['price']}")])
        if crypto:
            buttons.append([InlineKeyboardButton("₿ Pay via Crypto", callback_data=f"pay_crypto_{pid}_{p['price']}")])
        buttons.append([InlineKeyboardButton("⬅️ Back", callback_data=f"store_product_{pid}")])
        await q.edit_message_text(
            f"🛒 *{p['name']}*\n💰 Total: ₹{p['price']:.2f}\n\nSelect payment method:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    async def _pay_upi(self, q, uid, pid, amount, ctx):
        upi = await db_get_setting(self.db, self.bot_id, "upi_id", None)
        if not upi:
            await q.edit_message_text("❌ UPI not available.", reply_markup=kb_back())
            return
        order_id = await db_create_order(self.db, uid, pid, amount, "UPI")
        ctx.user_data["pending_order"] = order_id
        ctx.user_data["pay_step"] = "waiting_utr"
        await q.edit_message_text(
            f"🏦 *UPI Payment*\n\n"
            f"Amount: ₹{amount:.2f}\n"
            f"Pay to UPI: `{upi}`\n\n"
            f"After paying:\n"
            f"1. Note your UTR/Transaction ID from UPI app\n"
            f"2. Click *I've Paid* below\n"
            f"3. Send your UTR when asked",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_verify_payment(order_id)
        )

    async def _pay_crypto(self, q, uid, pid, amount, ctx):
        wallet = await db_get_setting(self.db, self.bot_id, "crypto_wallet", None)
        crypto_type = await db_get_setting(self.db, self.bot_id, "crypto_type", "USDT (TRC20)")
        if not wallet:
            await q.edit_message_text("❌ Crypto not available.", reply_markup=kb_back())
            return
        order_id = await db_create_order(self.db, uid, pid, amount, "Crypto")
        ctx.user_data["pending_order"] = order_id
        ctx.user_data["pay_step"] = "waiting_txhash"
        await q.edit_message_text(
            f"₿ *Crypto Payment*\n\n"
            f"Amount: ₹{amount:.2f} equivalent\n"
            f"Send *{crypto_type}* to:\n`{wallet}`\n\n"
            f"After sending:\n"
            f"1. Copy your Transaction Hash/ID\n"
            f"2. Click *I've Paid* below\n"
            f"3. Send your TX hash when asked",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_verify_payment(order_id)
        )

    async def _verify_payment(self, q, uid, order_id, ctx):
        row = await self.db.fetchone("SELECT * FROM store_orders WHERE id=? AND user_id=?", (order_id, uid))
        if not row:
            await q.answer("Order not found.", show_alert=True)
            return
        ctx.user_data["pending_order"] = order_id
        ctx.user_data["pay_step"] = "waiting_utr" if row["pay_method"] == "UPI" else "waiting_txhash"
        label = "UTR/Transaction ID" if row["pay_method"] == "UPI" else "Transaction Hash"
        await q.edit_message_text(
            f"✅ *Payment Submitted*\n\n"
            f"Please send your *{label}* now so we can verify your payment:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data=f"pay_cancel_{order_id}")
            ]])
        )

    async def _show_my_orders(self, q, uid):
        rows = await self.db.fetchall(
            "SELECT o.*, p.name as product_name FROM store_orders o "
            "LEFT JOIN store_products p ON p.id=o.product_id "
            "WHERE o.user_id=? ORDER BY o.created_at DESC LIMIT 10",
            (uid,)
        )
        if not rows:
            await q.edit_message_text("📦 No orders yet.", reply_markup=kb_back())
            return
        status_icons = {
            "pending_payment": "⏳",
            "pending_approval": "🔍",
            "approved": "✅",
            "rejected": "❌",
            "cancelled": "🚫",
            "delivered": "📬",
        }
        lines = ["📦 *Your Orders*\n"]
        for r in rows:
            icon = status_icons.get(r["status"], "❓")
            lines.append(
                f"{icon} #{r['id']} — {r['product_name'] or 'N/A'}\n"
                f"   ₹{r['amount']:.2f} | {r['pay_method']} | {r['status']}\n"
                f"   _{r['created_at'][:10]}_"
            )
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    async def _show_payment_info(self, q):
        upi = await db_get_setting(self.db, self.bot_id, "upi_id", None)
        crypto = await db_get_setting(self.db, self.bot_id, "crypto_wallet", None)
        crypto_type = await db_get_setting(self.db, self.bot_id, "crypto_type", "USDT (TRC20)")
        lines = ["💳 *Payment Methods*\n"]
        if upi:
            lines.append(f"🏦 UPI: `{upi}`")
        if crypto:
            lines.append(f"₿ {crypto_type}: `{crypto}`")
        if not upi and not crypto:
            lines.append("No payment methods configured yet.")
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=kb_back())

    # ── Message handler ───────────────────────────────────────────────────────
    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        text = (update.message.text or "").strip()
        await db_ensure_user(self.db, uid, update.effective_user.username)
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="store_main")]])
        back_admin_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="store_admin")]])

        # ── Admin multi-step inputs ────────────────────────────────────────
        adm_action = ctx.user_data.get("adm_action")
        if adm_action and self.is_admin(uid):
            await self._handle_admin_input(update, ctx, adm_action, text, back_admin_kb)
            return

        # ── Payment UTR/TxHash submission ──────────────────────────────────
        pay_step = ctx.user_data.get("pay_step")
        order_id = ctx.user_data.get("pending_order")
        if pay_step in ("waiting_utr", "waiting_txhash") and order_id:
            if len(text) < 8:
                await update.message.reply_text(
                    "❌ Transaction ID too short. Please enter a valid ID:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("❌ Cancel", callback_data=f"pay_cancel_{order_id}")
                    ]])
                )
                return
            await self.db.execute(
                "UPDATE store_orders SET tx_ref=?, status='pending_approval' WHERE id=?",
                (text, order_id)
            )
            await self.db.commit()

            # Notify order channel
            row = await self.db.fetchone(
                "SELECT o.*, p.name as pname FROM store_orders o "
                "LEFT JOIN store_products p ON p.id=o.product_id WHERE o.id=?",
                (order_id,)
            )
            order_ch = await db_get_setting(self.db, self.bot_id, "order_channel", None)
            if order_ch and row:
                uname = update.effective_user.username or f"uid:{uid}"
                try:
                    await update.get_bot().send_message(
                        order_ch,
                        f"🛒 *New Order #{order_id}*\n\n"
                        f"Product: {row['pname']}\n"
                        f"Amount: ₹{row['amount']:.2f}\n"
                        f"Method: {row['pay_method']}\n"
                        f"Ref: `{text}`\n"
                        f"User: @{uname} (`{uid}`)",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ Approve", callback_data=f"order_approve_{order_id}"),
                             InlineKeyboardButton("❌ Reject", callback_data=f"order_reject_{order_id}")]
                        ])
                    )
                except Exception as e:
                    logger.error("Order channel notify: %s", e)

            ctx.user_data.clear()
            await update.message.reply_text(
                f"✅ *Payment reference submitted!*\n\n"
                f"Order #{order_id} is under review.\n"
                f"⏳ You'll be notified once approved.",
                parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb
            )
            return

        # ── Admin delivery message ─────────────────────────────────────────
        deliver_order = ctx.user_data.get("deliver_order_id")
        if deliver_order and self.is_admin(uid):
            row = await self.db.fetchone("SELECT * FROM store_orders WHERE id=?", (deliver_order,))
            if row:
                try:
                    # Forward the message/file to buyer
                    await update.message.copy_to(
                        row["user_id"],
                        caption=f"📬 *Your Order #{deliver_order} has been delivered!*\n\n"
                                f"Thank you for your purchase! 🎉",
                    )
                    await self.db.execute(
                        "UPDATE store_orders SET status='delivered' WHERE id=?", (deliver_order,)
                    )
                    await self.db.commit()
                    ctx.user_data.clear()
                    await update.message.reply_text(
                        f"✅ Order #{deliver_order} delivered to buyer.",
                        reply_markup=back_admin_kb
                    )
                except Exception as e:
                    await update.message.reply_text(f"❌ Delivery failed: {e}", reply_markup=back_admin_kb)
            return

    # ── Admin callbacks ───────────────────────────────────────────────────────
    async def _handle_admin_cb(self, q, uid, ctx, data: str):
        back_admin_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="store_admin")]])

        prompt_map = {
            "adm_set_upi":       ("set_upi",         "🏦 Enter UPI ID (e.g. name@upi):"),
            "adm_set_crypto":    ("set_crypto",       "₿ Enter steps:\n1. Crypto type (e.g. USDT TRC20)\n2. Wallet address\n\nFormat: TYPE|ADDRESS"),
            "adm_set_order_ch":  ("set_order_ch",     "🔔 Enter order notification channel ID:"),
            "adm_broadcast":     ("broadcast",        "📨 Send broadcast message:"),
        }
        if data in prompt_map:
            action, prompt = prompt_map[data]
            ctx.user_data["adm_action"] = action
            await q.edit_message_text(prompt, reply_markup=back_admin_kb)
            return

        if data == "adm_add_product":
            ctx.user_data["adm_action"] = "add_product_name"
            ctx.user_data["new_product"] = {}
            await q.edit_message_text(
                "📦 *Add New Product*\n\nStep 1/5: Enter product *name*:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_admin_kb
            )

        elif data == "adm_list_products":
            products = await db_get_products(self.db, self.bot_id)
            if not products:
                await q.edit_message_text("📭 No products yet.", reply_markup=back_admin_kb)
                return
            lines = ["📋 *All Products*\n"]
            for p in products:
                stock = "∞" if p["stock"] == -1 else str(p["stock"])
                lines.append(f"#{p['id']} {p['name']} — ₹{p['price']} | Stock: {stock} | {p['category']}")
            await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=back_admin_kb)

        elif data == "adm_del_product":
            products = await db_get_products(self.db, self.bot_id)
            if not products:
                await q.edit_message_text("📭 No products.", reply_markup=back_admin_kb)
                return
            buttons = [[InlineKeyboardButton(f"🗑 #{p['id']} {p['name']}", callback_data=f"adm_delconfirm_{p['id']}")]
                       for p in products]
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="store_admin")])
            await q.edit_message_text("Select product to delete:", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("adm_delconfirm_"):
            pid = int(data.replace("adm_delconfirm_", ""))
            await self.db.execute("UPDATE store_products SET active=0 WHERE id=?", (pid,))
            await self.db.commit()
            await q.edit_message_text(f"✅ Product #{pid} removed.", reply_markup=back_admin_kb)

        elif data == "adm_edit_product":
            products = await db_get_products(self.db, self.bot_id)
            if not products:
                await q.edit_message_text("📭 No products.", reply_markup=back_admin_kb)
                return
            buttons = [[InlineKeyboardButton(f"✏️ #{p['id']} {p['name']}", callback_data=f"adm_edit_pick_{p['id']}")]
                       for p in products]
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="store_admin")])
            await q.edit_message_text("Select product to edit:", reply_markup=InlineKeyboardMarkup(buttons))

        elif data.startswith("adm_edit_pick_"):
            pid = int(data.replace("adm_edit_pick_", ""))
            ctx.user_data["adm_action"] = "edit_product_field"
            ctx.user_data["edit_pid"] = pid
            await q.edit_message_text(
                f"✏️ Product #{pid}\n\nWhat to edit?",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Price", callback_data=f"adm_editfield_price_{pid}"),
                     InlineKeyboardButton("📦 Stock", callback_data=f"adm_editfield_stock_{pid}")],
                    [InlineKeyboardButton("📝 Description", callback_data=f"adm_editfield_desc_{pid}")],
                    [InlineKeyboardButton("⬅️ Back", callback_data="store_admin")],
                ])
            )

        elif data.startswith("adm_editfield_"):
            parts = data.split("_")
            field = parts[2]
            pid = int(parts[3])
            ctx.user_data["adm_action"] = f"edit_field_{field}"
            ctx.user_data["edit_pid"] = pid
            prompts = {"price": "Enter new price (₹):", "stock": "Enter new stock (-1 = unlimited):", "desc": "Enter new description:"}
            await q.edit_message_text(prompts.get(field, "Enter value:"), reply_markup=back_admin_kb)

        elif data == "adm_pending_orders":
            rows = await self.db.fetchall(
                "SELECT o.*, p.name as pname FROM store_orders o "
                "LEFT JOIN store_products p ON p.id=o.product_id "
                "WHERE o.status='pending_approval' ORDER BY o.created_at ASC LIMIT 10"
            )
            if not rows:
                await q.edit_message_text("✅ No pending orders.", reply_markup=back_admin_kb)
                return
            buttons = []
            lines = ["📋 *Pending Orders*\n"]
            for r in rows:
                lines.append(
                    f"#{r['id']} — {r['pname']} | ₹{r['amount']:.2f} | {r['pay_method']}\nRef: `{r['tx_ref']}`"
                )
                buttons.append([
                    InlineKeyboardButton(f"✅ #{r['id']}", callback_data=f"order_approve_{r['id']}"),
                    InlineKeyboardButton(f"❌ #{r['id']}", callback_data=f"order_reject_{r['id']}")
                ])
            buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="store_admin")])
            await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=InlineKeyboardMarkup(buttons))

        elif data == "adm_stats":
            total_users = (await self.db.fetchone("SELECT COUNT(*) AS c FROM store_users"))["c"]
            total_orders = (await self.db.fetchone(
                "SELECT COUNT(*) AS c FROM store_orders WHERE status IN ('approved','delivered')"
            ))["c"]
            revenue = (await self.db.fetchone(
                "SELECT COALESCE(SUM(amount),0) AS s FROM store_orders WHERE status IN ('approved','delivered')"
            ))["s"]
            await q.edit_message_text(
                f"📈 *Revenue Stats*\n\n"
                f"👥 Users: {total_users}\n"
                f"✅ Completed Orders: {total_orders}\n"
                f"💰 Total Revenue: ₹{revenue:.2f}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_admin_kb
            )

    async def _approve_order(self, q, uid, order_id, ctx):
        row = await self.db.fetchone(
            "SELECT o.*, p.name as pname, p.stock as pstock FROM store_orders o "
            "LEFT JOIN store_products p ON p.id=o.product_id WHERE o.id=?",
            (order_id,)
        )
        if not row or row["status"] not in ("pending_approval", "pending_payment"):
            await q.answer("Already processed.", show_alert=True)
            return
        await self.db.execute("UPDATE store_orders SET status='approved' WHERE id=?", (order_id,))
        # Deduct stock if not unlimited
        if row["pstock"] > 0:
            await self.db.execute(
                "UPDATE store_products SET stock=stock-1 WHERE id=? AND stock>0", (row["product_id"],)
            )
        await self.db.commit()

        # Notify buyer
        try:
            await q.get_bot().send_message(
                row["user_id"],
                f"✅ *Order #{order_id} Approved!*\n\n"
                f"Product: {row['pname']}\n"
                f"Your purchase is being processed. You'll receive your product shortly! 🎉",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

        # Ask admin for delivery content
        ctx.user_data["deliver_order_id"] = order_id
        await q.edit_message_text(
            f"✅ Order #{order_id} approved!\n\n"
            f"Now send the *delivery content* (message, file, link) to deliver to the buyer:\n"
            f"_(Or skip if physical/manual delivery)_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⏭ Skip Delivery", callback_data="store_admin")]
            ])
        )

    async def _reject_order(self, q, order_id):
        row = await self.db.fetchone("SELECT * FROM store_orders WHERE id=?", (order_id,))
        if not row:
            return
        await self.db.execute("UPDATE store_orders SET status='rejected' WHERE id=?", (order_id,))
        await self.db.commit()
        try:
            await q.get_bot().send_message(
                row["user_id"],
                f"❌ *Order #{order_id} Rejected*\n\n"
                f"Your payment could not be verified. Contact admin for help.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        await q.edit_message_text(
            f"❌ Order #{order_id} rejected.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="store_admin")]])
        )

    async def _handle_admin_input(self, update, ctx, action, text, back_kb):
        uid = update.effective_user.id

        if action == "set_upi":
            if not UPI_PATTERN.match(text):
                await update.message.reply_text("❌ Invalid UPI ID. Try: name@upi", reply_markup=back_kb)
                ctx.user_data.clear()
                return
            await db_set_setting(self.db, self.bot_id, "upi_id", text)
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ UPI set to `{text}`",
                                             parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb)

        elif action == "set_crypto":
            if "|" in text:
                parts = text.split("|", 1)
                ctype, wallet = parts[0].strip(), parts[1].strip()
            else:
                ctype, wallet = "USDT (TRC20)", text.strip()
            await db_set_setting(self.db, self.bot_id, "crypto_type", ctype)
            await db_set_setting(self.db, self.bot_id, "crypto_wallet", wallet)
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ Crypto set:\nType: {ctype}\nWallet: `{wallet}`",
                                             parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb)

        elif action == "set_order_ch":
            await db_set_setting(self.db, self.bot_id, "order_channel", text)
            ctx.user_data.clear()
            await update.message.reply_text(f"✅ Order channel set to `{text}`",
                                             parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb)

        elif action == "broadcast":
            users = await self.db.fetchall("SELECT user_id FROM store_users")
            sent = failed = 0
            for u in users:
                try:
                    await update.get_bot().send_message(u["user_id"], text)
                    sent += 1
                except Exception:
                    failed += 1
            ctx.user_data.clear()
            await update.message.reply_text(f"📨 Sent: {sent}, Failed: {failed}", reply_markup=back_kb)

        # ── Add product multi-step ─────────────────────────────────────────
        elif action == "add_product_name":
            ctx.user_data["new_product"]["name"] = text
            ctx.user_data["adm_action"] = "add_product_desc"
            await update.message.reply_text(
                f"✅ Name: {text}\n\nStep 2/5: Enter *description*:",
                parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb
            )

        elif action == "add_product_desc":
            ctx.user_data["new_product"]["description"] = text
            ctx.user_data["adm_action"] = "add_product_price"
            await update.message.reply_text(
                "Step 3/5: Enter *price* (₹):",
                parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb
            )

        elif action == "add_product_price":
            try:
                price = float(text)
                ctx.user_data["new_product"]["price"] = price
                ctx.user_data["adm_action"] = "add_product_stock"
                await update.message.reply_text(
                    "Step 4/5: Enter *stock* (-1 for unlimited):",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb
                )
            except ValueError:
                await update.message.reply_text("❌ Enter a valid price number.")

        elif action == "add_product_stock":
            try:
                stock = int(text)
                ctx.user_data["new_product"]["stock"] = stock
                ctx.user_data["adm_action"] = "add_product_category"
                await update.message.reply_text(
                    "Step 5/5: Enter *category* name (e.g. Digital, Courses, Subscriptions):",
                    parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb
                )
            except ValueError:
                await update.message.reply_text("❌ Enter a valid stock number (-1 for unlimited).")

        elif action == "add_product_category":
            np = ctx.user_data.get("new_product", {})
            np["category"] = text
            await self.db.execute("""
                INSERT INTO store_products(bot_id, name, description, price, stock, category, active)
                VALUES(?,?,?,?,?,?,1)
            """, (self.bot_id, np["name"], np["description"], np["price"], np["stock"], np["category"]))
            await self.db.commit()
            ctx.user_data.clear()
            await update.message.reply_text(
                f"✅ *Product Added!*\n\n"
                f"Name: {np['name']}\nPrice: ₹{np['price']}\nCategory: {np['category']}",
                parse_mode=ParseMode.MARKDOWN, reply_markup=back_kb
            )

        # ── Edit product fields ────────────────────────────────────────────
        elif action.startswith("edit_field_"):
            field = action.replace("edit_field_", "")
            pid = ctx.user_data.get("edit_pid")
            try:
                if field == "price":
                    val = float(text)
                    await self.db.execute("UPDATE store_products SET price=? WHERE id=?", (val, pid))
                elif field == "stock":
                    val = int(text)
                    await self.db.execute("UPDATE store_products SET stock=? WHERE id=?", (val, pid))
                elif field == "desc":
                    await self.db.execute("UPDATE store_products SET description=? WHERE id=?", (text, pid))
                await self.db.commit()
                ctx.user_data.clear()
                await update.message.reply_text(f"✅ Product #{pid} updated.", reply_markup=back_kb)
            except ValueError:
                await update.message.reply_text("❌ Invalid value. Try again.")

    # ── build_app ─────────────────────────────────────────────────────────────
    async def build_app(self) -> Application:
        for ddl in [
            """CREATE TABLE IF NOT EXISTS store_users (
                user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', joined_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS store_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT, bot_id INTEGER,
                name TEXT, description TEXT, price REAL, stock INTEGER DEFAULT -1,
                category TEXT DEFAULT 'General', active INTEGER DEFAULT 1)""",
            """CREATE TABLE IF NOT EXISTS store_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                product_id INTEGER, amount REAL, pay_method TEXT,
                tx_ref TEXT DEFAULT '', status TEXT DEFAULT 'pending_payment',
                created_at TEXT)""",
            """CREATE TABLE IF NOT EXISTS store_settings (
                bot_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(bot_id,key))""",
        ]:
            await self.db.execute(ddl)
        await self.db.commit()

        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("admin", self._cmd_admin))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(
            (filters.TEXT | filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO) & ~filters.COMMAND,
            self.on_message
        ))
        return app

    async def _cmd_admin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Not authorized.")
            return
        await update.message.reply_text("🔧 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                         reply_markup=kb_admin())
