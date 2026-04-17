"""
🛒 MINI SHOP BOT
Full Telegram-based mini e-commerce store.
Products, cart, orders, admin panel.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from .base import BaseBotTemplate

SCHEMA = """
CREATE TABLE IF NOT EXISTS shop_products_{bid} (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT,
    price REAL, category TEXT DEFAULT 'General', stock INTEGER DEFAULT -1,
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS shop_cart_{bid} (
    id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, product_id INTEGER, qty INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS shop_orders_{bid} (
    id INTEGER PRIMARY KEY AUTOINCREMENT, uid INTEGER, username TEXT,
    items TEXT, total REAL, status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS shop_users_{bid} (uid INTEGER PRIMARY KEY, username TEXT, first_name TEXT);
CREATE TABLE IF NOT EXISTS shop_cfg_{bid} (key TEXT PRIMARY KEY, value TEXT);
"""

class MiniShopBot(BaseBotTemplate):
    TEMPLATE_ID="mini_shop"; TEMPLATE_NAME="Mini Shop Bot"

    async def build_app(self):
        with self._conn() as c:
            for s in SCHEMA.replace("{bid}",str(self.bot_id)).split(";"):
                if s.strip(): c.execute(s)
            c.execute(f"INSERT OR IGNORE INTO shop_cfg_{self.bot_id}(key,value) VALUES('owner_id','0')")
            # Seed with sample products
            if c.execute(f"SELECT COUNT(*) FROM shop_products_{self.bot_id}").fetchone()[0]==0:
                c.executemany(f"INSERT INTO shop_products_{self.bot_id}(name,description,price,category) VALUES(?,?,?,?)",[
                    ("📱 Premium Account","30-day premium access",9.99,"Digital"),
                    ("🎮 Game Coins","1000 in-game coins pack",4.99,"Gaming"),
                    ("📚 E-Book Bundle","5 bestselling ebooks",14.99,"Books"),
                    ("🎨 Design Pack","100 premium templates",19.99,"Creative"),
                ])
        app=Application.builder().token(self.token).build(); self.register_handlers(app); return app

    def _owner(self):
        with self._conn() as c:
            r=c.execute(f"SELECT value FROM shop_cfg_{self.bot_id} WHERE key='owner_id'").fetchone()
            return int(r[0]) if r else 0

    def _upsert(self,uid,uname,fname):
        with self._conn() as c:
            c.execute(f"INSERT INTO shop_users_{self.bot_id}(uid,username,first_name) VALUES(?,?,?) ON CONFLICT(uid) DO UPDATE SET username=excluded.username",(uid,uname,fname))

    def _products(self,cat=None):
        with self._conn() as c:
            if cat: return [dict(r) for r in c.execute(f"SELECT * FROM shop_products_{self.bot_id} WHERE active=1 AND category=?",(cat,))]
            return [dict(r) for r in c.execute(f"SELECT * FROM shop_products_{self.bot_id} WHERE active=1")]

    def _get_product(self,pid):
        with self._conn() as c:
            r=c.execute(f"SELECT * FROM shop_products_{self.bot_id} WHERE id=?",(pid,)).fetchone()
            return dict(r) if r else None

    def _cart(self,uid):
        with self._conn() as c:
            return [dict(r) for r in c.execute(f"SELECT c.*,p.name,p.price FROM shop_cart_{self.bot_id} c JOIN shop_products_{self.bot_id} p ON c.product_id=p.id WHERE c.uid=?",(uid,))]

    def _add_cart(self,uid,pid):
        with self._conn() as c:
            existing=c.execute(f"SELECT id FROM shop_cart_{self.bot_id} WHERE uid=? AND product_id=?",(uid,pid)).fetchone()
            if existing: c.execute(f"UPDATE shop_cart_{self.bot_id} SET qty=qty+1 WHERE uid=? AND product_id=?",(uid,pid))
            else: c.execute(f"INSERT INTO shop_cart_{self.bot_id}(uid,product_id) VALUES(?,?)",(uid,pid))

    def _clear_cart(self,uid):
        with self._conn() as c: c.execute(f"DELETE FROM shop_cart_{self.bot_id} WHERE uid=?",(uid,))

    def _place_order(self,uid,uname,items_txt,total):
        with self._conn() as c:
            cur=c.execute(f"INSERT INTO shop_orders_{self.bot_id}(uid,username,items,total) VALUES(?,?,?,?)",(uid,uname,items_txt,total))
            return cur.lastrowid

    def _orders(self,uid=None):
        with self._conn() as c:
            if uid: return [dict(r) for r in c.execute(f"SELECT * FROM shop_orders_{self.bot_id} WHERE uid=? ORDER BY created_at DESC LIMIT 10",(uid,))]
            return [dict(r) for r in c.execute(f"SELECT * FROM shop_orders_{self.bot_id} ORDER BY created_at DESC LIMIT 20")]

    def register_handlers(self,app):
        app.add_handler(CommandHandler("start",self._start))
        app.add_handler(CommandHandler("shop",self._shop_cmd))
        app.add_handler(CommandHandler("cart",self._cart_cmd))
        app.add_handler(CommandHandler("orders",self._orders_cmd))
        app.add_handler(CommandHandler("admin",self._admin))
        app.add_handler(CommandHandler("addproduct",self._add_product))
        app.add_handler(CallbackQueryHandler(self._cb))
        app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,self._handle_text))

    async def _start(self,u,ctx):
        user=u.effective_user; self._upsert(user.id,user.username or "",user.first_name or "User")
        if not self._owner():
            with self._conn() as c: c.execute(f"INSERT OR REPLACE INTO shop_cfg_{self.bot_id}(key,value) VALUES('owner_id',?)",(str(user.id),))
        products=self._products(); cart=self._cart(user.id)
        msg=(f"🛒 **MINI SHOP**\n\n👋 Hi **{user.first_name}**!\n\n"
             f"🛍️ Products Available: **{len(products)}**\n"
             f"🛒 Cart Items: **{len(cart)}**\n\n_Browse our catalog below!_")
        kb=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛍️ Browse Shop",callback_data="browse"),InlineKeyboardButton("🛒 My Cart",callback_data="view_cart")],
            [InlineKeyboardButton("📦 My Orders",callback_data="my_orders")],
        ])
        await u.message.reply_text(msg,reply_markup=kb,parse_mode="Markdown")

    async def _shop_cmd(self,u,ctx):
        products=self._products()
        if not products: await u.message.reply_text("📭 No products yet!"); return
        rows=[]; 
        for p in products: rows.append([InlineKeyboardButton(f"{p['name']} — ${p['price']:.2f}",callback_data=f"product_{p['id']}")])
        rows.append([InlineKeyboardButton("🛒 Cart",callback_data="view_cart")])
        await u.message.reply_text("🛍️ **PRODUCT CATALOG**\n\nChoose a product:",reply_markup=InlineKeyboardMarkup(rows),parse_mode="Markdown")

    async def _cart_cmd(self,u,ctx):
        uid=u.effective_user.id; cart=self._cart(uid)
        if not cart: await u.message.reply_text("🛒 Cart is empty!\n\n/shop to browse."); return
        total=sum(i["price"]*i["qty"] for i in cart)
        lines=["🛒 **YOUR CART**\n"]
        for i in cart: lines.append(f"• {i['name']} × {i['qty']} = ${i['price']*i['qty']:.2f}")
        lines.append(f"\n💰 **Total: ${total:.2f}**")
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Checkout",callback_data="checkout"),InlineKeyboardButton("🗑️ Clear",callback_data="clear_cart")]])
        await u.message.reply_text("\n".join(lines),reply_markup=kb,parse_mode="Markdown")

    async def _orders_cmd(self,u,ctx):
        orders=self._orders(u.effective_user.id)
        if not orders: await u.message.reply_text("📭 No orders yet!\n\n/shop to start shopping."); return
        lines=["📦 **MY ORDERS**\n"]
        for o in orders: lines.append(f"#{o['id']} | ${o['total']:.2f} | {o['status'].upper()}\n   {o['created_at'][:10]}")
        await u.message.reply_text("\n".join(lines),parse_mode="Markdown")

    async def _admin(self,u,ctx):
        uid=u.effective_user.id
        if uid!=self._owner(): await u.message.reply_text("⛔ Admin only!"); return
        products=self._products(); orders=self._orders()
        pending=sum(1 for o in orders if o["status"]=="pending")
        sales=sum(o["total"] for o in orders)
        msg=(f"👑 **SHOP ADMIN**\n\n📦 Products: {len(products)}\n"
             f"🛒 Total Orders: {len(orders)}\n⏳ Pending: {pending}\n💰 Total Sales: ${sales:.2f}\n\n"
             f"/addproduct Name | Description | Price | Category")
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("📋 All Orders",callback_data="admin_orders")]])
        await u.message.reply_text(msg,reply_markup=kb,parse_mode="Markdown")

    async def _add_product(self,u,ctx):
        uid=u.effective_user.id
        if uid!=self._owner(): await u.message.reply_text("⛔ Admin only!"); return
        args=" ".join(ctx.args) if ctx.args else ""
        parts=[p.strip() for p in args.split("|")]
        if len(parts)<3: await u.message.reply_text("Usage: /addproduct Name | Description | Price | Category"); return
        try:
            name,desc,price_s=parts[0],parts[1],parts[2]; cat=parts[3] if len(parts)>3 else "General"
            price=float(price_s)
            with self._conn() as c: c.execute(f"INSERT INTO shop_products_{self.bot_id}(name,description,price,category) VALUES(?,?,?,?)",(name,desc,price,cat))
            await u.message.reply_text(f"✅ Product added!\n\n📦 **{name}** — ${price:.2f}\n{cat}",parse_mode="Markdown")
        except Exception as e: await u.message.reply_text(f"❌ Error: {e}")

    async def _handle_text(self,u,ctx): pass

    async def _cb(self,u,ctx):
        q=u.callback_query; await q.answer(); d=q.data; uid=q.from_user.id
        self._upsert(uid,q.from_user.username or "",q.from_user.first_name or "User")
        if d=="browse":
            products=self._products(); rows=[]
            for p in products: rows.append([InlineKeyboardButton(f"{p['name']} — ${p['price']:.2f}",callback_data=f"product_{p['id']}")])
            rows.append([InlineKeyboardButton("🛒 Cart",callback_data="view_cart")])
            await q.edit_message_text("🛍️ **CATALOG**\nChoose a product:",reply_markup=InlineKeyboardMarkup(rows),parse_mode="Markdown")
        elif d.startswith("product_"):
            pid=int(d[8:]); p=self._get_product(pid)
            if not p: return
            msg=(f"📦 **{p['name']}**\n\n💬 {p['description']}\n\n💰 Price: **${p['price']:.2f}**\n📂 {p['category']}")
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Add to Cart",callback_data=f"add_{pid}"),InlineKeyboardButton("🔙 Back",callback_data="browse")]])
            await q.edit_message_text(msg,reply_markup=kb,parse_mode="Markdown")
        elif d.startswith("add_"):
            pid=int(d[4:]); self._add_cart(uid,pid); p=self._get_product(pid)
            await q.answer(f"✅ {p['name']} added to cart!",show_alert=True)
        elif d=="view_cart":
            cart=self._cart(uid)
            if not cart: await q.edit_message_text("🛒 Cart is empty!\n\nTap 🛍️ Browse to shop."); return
            total=sum(i["price"]*i["qty"] for i in cart)
            lines=["🛒 **YOUR CART**\n"]+[f"• {i['name']} × {i['qty']} = ${i['price']*i['qty']:.2f}" for i in cart]+[f"\n💰 **Total: ${total:.2f}**"]
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Checkout",callback_data="checkout"),InlineKeyboardButton("🗑️ Clear",callback_data="clear_cart")]])
            await q.edit_message_text("\n".join(lines),reply_markup=kb,parse_mode="Markdown")
        elif d=="clear_cart":
            self._clear_cart(uid); await q.edit_message_text("🗑️ Cart cleared!")
        elif d=="checkout":
            cart=self._cart(uid)
            if not cart: await q.edit_message_text("Cart is empty!"); return
            total=sum(i["price"]*i["qty"] for i in cart)
            items_txt=", ".join([f"{i['name']}×{i['qty']}" for i in cart])
            oid=self._place_order(uid,q.from_user.username or "",items_txt,total)
            self._clear_cart(uid)
            self.track_tx()
            await q.edit_message_text(f"✅ **Order Placed! #{oid}**\n\n💰 Total: ${total:.2f}\n📦 Items: {items_txt}\n\nAdmin will confirm shortly!",parse_mode="Markdown")
            owner=self._owner()
            if owner:
                try: await ctx.bot.send_message(owner,f"🔔 **New Order #{oid}**\n\n👤 @{q.from_user.username or uid}\n💰 ${total:.2f}\n📦 {items_txt}",parse_mode="Markdown")
                except: pass
        elif d=="my_orders":
            orders=self._orders(uid)
            if not orders: await q.edit_message_text("📭 No orders yet!"); return
            lines=["📦 **Orders:**\n"]+[f"#{o['id']} ${o['total']:.2f} [{o['status']}]" for o in orders]
            await q.edit_message_text("\n".join(lines),parse_mode="Markdown")
        elif d=="admin_orders":
            if uid!=self._owner(): return
            orders=self._orders()
            lines=["📋 **All Orders:**\n"]+[f"#{o['id']} @{o['username']} ${o['total']:.2f} [{o['status']}]" for o in orders[:10]]
            await q.edit_message_text("\n".join(lines),parse_mode="Markdown")
