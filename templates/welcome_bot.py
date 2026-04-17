"""👋 Group Welcome Manager Bot"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import Application, CommandHandler, ChatMemberHandler, CallbackQueryHandler, ContextTypes
from .base import BaseBotTemplate

SCHEMA = """
CREATE TABLE IF NOT EXISTS wel_cfg_{bid} (key TEXT PRIMARY KEY, value TEXT);
"""
DW = "👋 Welcome to {group}, {name}! 🎉"; DF = "😢 Goodbye {name}!"; DR = "📋 Be respectful. No spam."

class WelcomeBot(BaseBotTemplate):
    TEMPLATE_ID="welcome_bot"; TEMPLATE_NAME="Group Welcome Manager"
    async def build_app(self):
        with self._conn() as c: c.execute(SCHEMA.replace("{bid}",str(self.bot_id)))
        app=Application.builder().token(self.token).build(); self.register_handlers(app); return app
    def _cfg(self,cid,k,default=""):
        with self._conn() as c:
            r=c.execute(f"SELECT value FROM wel_cfg_{self.bot_id} WHERE key=?",(f"{cid}_{k}",)).fetchone()
            return r[0] if r else default
    def _set(self,cid,k,v):
        with self._conn() as c: c.execute(f"INSERT OR REPLACE INTO wel_cfg_{self.bot_id}(key,value) VALUES(?,?)",(f"{cid}_{k}",v))
    async def _is_admin(self,u):
        if u.effective_chat.type=="private": return True
        m=await u.effective_chat.get_member(u.effective_user.id)
        return m.status in ["administrator","creator"]
    def register_handlers(self,app):
        for cmd,fn in [("start",self._start),("setwelcome",self._sw),("setfarewell",self._sf),
                        ("rules",self._rules),("setrules",self._sr),("mute",self._mute),
                        ("unmute",self._unmute),("ban",self._ban),("kick",self._kick)]:
            app.add_handler(CommandHandler(cmd,fn))
        app.add_handler(ChatMemberHandler(self._member,ChatMemberHandler.CHAT_MEMBER))
        app.add_handler(CallbackQueryHandler(self._cb))
    async def _start(self,u,ctx):
        await u.message.reply_text("👋 **Welcome Manager Bot**\n\nAdd me to a group as admin!\n\nCommands: /setwelcome /setfarewell /setrules /rules /mute /unmute /ban /kick",parse_mode="Markdown")
    async def _member(self,u,ctx):
        r=u.chat_member; chat=r.chat; nm=r.new_chat_member; om=r.old_chat_member
        if om.status in ["left","kicked"] and nm.status in ["member","restricted"]:
            msg=self._cfg(chat.id,"welcome",DW).format(name=f"**{nm.user.first_name}**",group=f"**{chat.title}**",username=f"@{nm.user.username}" if nm.user.username else nm.user.first_name)
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Rules",callback_data=f"rules_{chat.id}")]])
            await ctx.bot.send_message(chat.id,msg,reply_markup=kb,parse_mode="Markdown")
        elif om.status in ["member","restricted"] and nm.status=="left":
            msg=self._cfg(chat.id,"farewell",DF).format(name=f"**{nm.user.first_name}**",username=f"@{nm.user.username}" if nm.user.username else nm.user.first_name)
            await ctx.bot.send_message(chat.id,msg,parse_mode="Markdown")
    async def _sw(self,u,ctx):
        if not await self._is_admin(u): await u.message.reply_text("⛔ Admins only!"); return
        t=" ".join(ctx.args) if ctx.args else ""
        if not t: await u.message.reply_text("Usage: /setwelcome text (use {name},{group},{username})"); return
        self._set(u.effective_chat.id,"welcome",t); await u.message.reply_text(f"✅ Welcome message set!\nPreview: {t.format(name='**User**',group='**Group**',username='@user')}",parse_mode="Markdown")
    async def _sf(self,u,ctx):
        if not await self._is_admin(u): await u.message.reply_text("⛔ Admins only!"); return
        t=" ".join(ctx.args) if ctx.args else ""
        if not t: await u.message.reply_text("Usage: /setfarewell text"); return
        self._set(u.effective_chat.id,"farewell",t); await u.message.reply_text("✅ Farewell message set!")
    async def _rules(self,u,ctx):
        r=self._cfg(u.effective_chat.id,"rules",DR); await u.message.reply_text(f"📋 **Rules**\n\n{r}",parse_mode="Markdown")
    async def _sr(self,u,ctx):
        if not await self._is_admin(u): await u.message.reply_text("⛔ Admins only!"); return
        t=" ".join(ctx.args) if ctx.args else ""
        if not t: await u.message.reply_text("Usage: /setrules text"); return
        self._set(u.effective_chat.id,"rules",t); await u.message.reply_text("✅ Rules updated!")
    async def _mute(self,u,ctx):
        if not await self._is_admin(u) or not u.message.reply_to_message: await u.message.reply_text("⛔ Reply to a user to mute!"); return
        t=u.message.reply_to_message.from_user
        await ctx.bot.restrict_chat_member(u.effective_chat.id,t.id,ChatPermissions(can_send_messages=False))
        await u.message.reply_text(f"🔇 {t.first_name} muted.")
    async def _unmute(self,u,ctx):
        if not await self._is_admin(u) or not u.message.reply_to_message: return
        t=u.message.reply_to_message.from_user
        await ctx.bot.restrict_chat_member(u.effective_chat.id,t.id,ChatPermissions(can_send_messages=True,can_send_media_messages=True,can_send_other_messages=True))
        await u.message.reply_text(f"🔊 {t.first_name} unmuted.")
    async def _ban(self,u,ctx):
        if not await self._is_admin(u) or not u.message.reply_to_message: return
        t=u.message.reply_to_message.from_user
        await ctx.bot.ban_chat_member(u.effective_chat.id,t.id); await u.message.reply_text(f"🚫 {t.first_name} banned.")
    async def _kick(self,u,ctx):
        if not await self._is_admin(u) or not u.message.reply_to_message: return
        t=u.message.reply_to_message.from_user
        await ctx.bot.ban_chat_member(u.effective_chat.id,t.id); await ctx.bot.unban_chat_member(u.effective_chat.id,t.id)
        await u.message.reply_text(f"👢 {t.first_name} kicked.")
    async def _cb(self,u,ctx):
        q=u.callback_query; await q.answer()
        if q.data.startswith("rules_"):
            cid=int(q.data[6:]); r=self._cfg(cid,"rules",DR)
            await q.answer(f"📋 {r[:200]}",show_alert=True)
