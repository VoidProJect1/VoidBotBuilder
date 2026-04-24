"""
templates/file_converter.py
============================
File Converter & Compressor Bot
- PDF → Images (PNG/JPG per page) — popular in India for student notes
- Image compression (reduce file size)
- File rename (rename any document/media)
- PDF merge (combine multiple PDFs)
- Image to PDF conversion
- Admin: set max file size, broadcast, stats
- Full keyboard UI with back/cancel on every step
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Document
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

from templates.base import BaseTemplate

logger = logging.getLogger(__name__)

TEMPLATE_INFO = {
    "id":          "file_converter",
    "name":        "File Converter & Compressor",
    "emoji":       "📁",
    "category":    "Utility",
    "description": "Convert PDFs to images, compress files, rename & merge — perfect for students",
    "features":    [
        "PDF → Images (PNG/JPG, all pages)",
        "Image compression (reduce size)",
        "File rename (any file type)",
        "Multiple images → PDF",
        "PDF merge (send multiple PDFs)",
        "Admin: max file size, broadcast",
        "Works great for sharing notes",
    ],
    "complexity":  "Intermediate",
    "best_for":    "Students, teachers, office workers in India",
    "stars":       5,
    "new":         True,
}

MAX_FILE_MB_DEFAULT = 20

# ── Keyboards ─────────────────────────────────────────────────────────────────

def kb_main(is_admin=False):
    buttons = [
        [InlineKeyboardButton("📄 PDF → Images", callback_data="fc_pdf_to_img"),
         InlineKeyboardButton("🗜 Compress Image", callback_data="fc_compress")],
        [InlineKeyboardButton("✏️ Rename File", callback_data="fc_rename"),
         InlineKeyboardButton("📑 Images → PDF", callback_data="fc_img_to_pdf")],
        [InlineKeyboardButton("🔗 Merge PDFs", callback_data="fc_merge_pdf"),
         InlineKeyboardButton("ℹ️ Help", callback_data="fc_help")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("🔧 Admin Panel", callback_data="fc_admin")])
    return InlineKeyboardMarkup(buttons)

def kb_back(target="fc_main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=target)]])

def kb_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="fc_main")]])

def kb_img_format():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 PNG (Better Quality)", callback_data="fc_pdf_fmt_png"),
         InlineKeyboardButton("📷 JPG (Smaller Size)", callback_data="fc_pdf_fmt_jpg")],
        [InlineKeyboardButton("⬅️ Back", callback_data="fc_main")],
    ])

def kb_compress_quality():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 High Compression (smaller)", callback_data="fc_cmp_30"),
         InlineKeyboardButton("🟡 Medium", callback_data="fc_cmp_60")],
        [InlineKeyboardButton("🟢 Low Compression (better quality)", callback_data="fc_cmp_85")],
        [InlineKeyboardButton("⬅️ Back", callback_data="fc_main")],
    ])

def kb_admin():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Set Max File Size (MB)", callback_data="fc_adm_maxsize"),
         InlineKeyboardButton("📈 Stats", callback_data="fc_adm_stats")],
        [InlineKeyboardButton("📨 Broadcast", callback_data="fc_adm_broadcast")],
        [InlineKeyboardButton("⬅️ Back", callback_data="fc_main")],
    ])

# ── DB helpers ────────────────────────────────────────────────────────────────

async def db_ensure_user(db, uid, username):
    await db.execute("""
        INSERT OR IGNORE INTO fc_users (user_id, username, conversions)
        VALUES (?,?,0)
    """, (uid, username or ""))
    await db.commit()

async def db_get_setting(db, bot_id, key, default=None):
    row = await db.fetchone("SELECT value FROM fc_settings WHERE bot_id=? AND key=?", (bot_id, key))
    return row["value"] if row else default

async def db_set_setting(db, bot_id, key, value):
    await db.execute("""
        INSERT INTO fc_settings (bot_id,key,value) VALUES(?,?,?)
        ON CONFLICT(bot_id,key) DO UPDATE SET value=excluded.value
    """, (bot_id, key, str(value)))
    await db.commit()

async def db_inc_conversion(db, uid):
    await db.execute("UPDATE fc_users SET conversions=conversions+1 WHERE user_id=?", (uid,))
    await db.commit()

# ── Conversion helpers ────────────────────────────────────────────────────────

async def _install_deps():
    """Install pdf2image and Pillow if not present."""
    try:
        import pdf2image
        from PIL import Image
        return True
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "pdf2image", "Pillow",
                        "--break-system-packages", "-q"], capture_output=True)
        try:
            import pdf2image
            from PIL import Image
            return True
        except Exception:
            return False

async def pdf_to_images(pdf_bytes: bytes, fmt: str = "png") -> list[bytes]:
    """Convert PDF bytes to list of image bytes."""
    if not await _install_deps():
        raise RuntimeError("pdf2image not available")
    from pdf2image import convert_from_bytes
    images = convert_from_bytes(pdf_bytes, dpi=150, fmt=fmt.upper())
    result = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format=fmt.upper() if fmt.upper() != "JPG" else "JPEG",
                 quality=85 if fmt == "jpg" else None)
        result.append(buf.getvalue())
    return result

async def compress_image(image_bytes: bytes, quality: int = 60) -> bytes:
    """Compress image to reduce file size."""
    await _install_deps()
    from PIL import Image
    img = Image.open(io.BytesIO(image_bytes))
    buf = io.BytesIO()
    # Convert RGBA to RGB if needed for JPEG
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()

async def images_to_pdf(image_bytes_list: list[bytes]) -> bytes:
    """Convert list of images to a single PDF."""
    await _install_deps()
    from PIL import Image
    images = []
    for b in image_bytes_list:
        img = Image.open(io.BytesIO(b)).convert("RGB")
        images.append(img)
    if not images:
        raise ValueError("No images provided")
    buf = io.BytesIO()
    images[0].save(buf, format="PDF", save_all=True, append_images=images[1:])
    return buf.getvalue()

async def merge_pdfs(pdf_bytes_list: list[bytes]) -> bytes:
    """Merge multiple PDFs into one."""
    try:
        import pypdf
    except ImportError:
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "pypdf",
                        "--break-system-packages", "-q"], capture_output=True)
        import pypdf
    writer = pypdf.PdfWriter()
    for b in pdf_bytes_list:
        reader = pypdf.PdfReader(io.BytesIO(b))
        for page in reader.pages:
            writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

# ── Template ──────────────────────────────────────────────────────────────────

class Template(BaseTemplate):

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        await db_ensure_user(self.db, uid, update.effective_user.username)
        await update.message.reply_text(
            "📁 *File Converter & Compressor*\n\n"
            "Convert PDFs to images, compress files, rename, merge & more!\n"
            "Perfect for sharing notes 📚",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_main(self.is_admin(uid))
        )

    async def on_callback(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        uid = q.from_user.id
        data = q.data
        await db_ensure_user(self.db, uid, q.from_user.username)

        if data == "fc_main":
            ctx.user_data.clear()
            await q.edit_message_text(
                "📁 *File Converter & Compressor*\nChoose what you want to do:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(self.is_admin(uid))
            )

        elif data == "fc_pdf_to_img":
            ctx.user_data["action"] = "pdf_to_img"
            await q.edit_message_text(
                "📄 *PDF → Images*\n\nSend your PDF file (max size set by admin).\n"
                "Each page will be converted to a separate image.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel()
            )

        elif data == "fc_compress":
            ctx.user_data["action"] = "compress_wait_file"
            await q.edit_message_text(
                "🗜 *Image Compressor*\n\nSend your image (JPG/PNG) to compress:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel()
            )

        elif data.startswith("fc_cmp_"):
            quality = int(data.replace("fc_cmp_", ""))
            ctx.user_data["compress_quality"] = quality
            ctx.user_data["action"] = "compress_do"
            # Trigger compression if file already stored
            if ctx.user_data.get("compress_file"):
                await self._do_compress(q, uid, ctx)
            else:
                await q.edit_message_text(
                    "✅ Quality selected! Now send your image:",
                    reply_markup=kb_cancel()
                )

        elif data == "fc_rename":
            ctx.user_data["action"] = "rename_wait_file"
            await q.edit_message_text(
                "✏️ *Rename File*\n\nSend the file you want to rename:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel()
            )

        elif data == "fc_img_to_pdf":
            ctx.user_data["action"] = "img_to_pdf"
            ctx.user_data["img_list"] = []
            await q.edit_message_text(
                "📑 *Images → PDF*\n\nSend images one by one.\n"
                "When done, type /done to generate the PDF.\n\n"
                "Images will be added in the order you send them.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel()
            )

        elif data == "fc_merge_pdf":
            ctx.user_data["action"] = "merge_pdf"
            ctx.user_data["pdf_list"] = []
            await q.edit_message_text(
                "🔗 *Merge PDFs*\n\nSend PDFs one by one.\n"
                "When done, type /done to merge them.\n\n"
                "PDFs will be merged in the order you send them.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_cancel()
            )

        elif data == "fc_help":
            max_mb = await db_get_setting(self.db, self.bot_id, "max_file_mb", str(MAX_FILE_MB_DEFAULT))
            await q.edit_message_text(
                f"ℹ️ *How to Use*\n\n"
                f"📄 *PDF → Images*: Send PDF, get each page as image\n"
                f"🗜 *Compress*: Shrink image file size\n"
                f"✏️ *Rename*: Change filename of any file\n"
                f"📑 *Images → PDF*: Combine images into one PDF\n"
                f"🔗 *Merge PDFs*: Combine multiple PDFs\n\n"
                f"Max file size: {max_mb} MB\n\n"
                f"💡 Tip: Great for sharing notes as images or compressing photos!",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_back()
            )

        elif data == "fc_pdf_fmt_png":
            ctx.user_data["pdf_fmt"] = "png"
            await q.edit_message_text(
                "📄 PNG selected. Send your PDF file:",
                reply_markup=kb_cancel()
            )

        elif data == "fc_pdf_fmt_jpg":
            ctx.user_data["pdf_fmt"] = "jpg"
            await q.edit_message_text(
                "📄 JPG selected. Send your PDF file:",
                reply_markup=kb_cancel()
            )

        elif data == "fc_admin":
            if not self.is_admin(uid):
                await q.answer("⛔ Not authorized", show_alert=True)
                return
            await q.edit_message_text("🔧 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                       reply_markup=kb_admin())

        elif data == "fc_adm_maxsize":
            if not self.is_admin(uid): return
            ctx.user_data["adm_action"] = "set_maxsize"
            await q.edit_message_text("📦 Enter max file size in MB (e.g. 20):",
                                       reply_markup=InlineKeyboardMarkup([[
                                           InlineKeyboardButton("❌ Cancel", callback_data="fc_admin")
                                       ]]))

        elif data == "fc_adm_stats":
            if not self.is_admin(uid): return
            total = (await self.db.fetchone("SELECT COUNT(*) AS c FROM fc_users"))["c"]
            total_conv = (await self.db.fetchone("SELECT COALESCE(SUM(conversions),0) AS s FROM fc_users"))["s"]
            max_mb = await db_get_setting(self.db, self.bot_id, "max_file_mb", str(MAX_FILE_MB_DEFAULT))
            await q.edit_message_text(
                f"📈 *Stats*\n\nUsers: {total}\nTotal Conversions: {total_conv}\nMax File Size: {max_mb} MB",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="fc_admin")]])
            )

        elif data == "fc_adm_broadcast":
            if not self.is_admin(uid): return
            ctx.user_data["adm_action"] = "broadcast"
            await q.edit_message_text("📨 Send broadcast message:", reply_markup=kb_cancel())

    async def on_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        await db_ensure_user(self.db, uid, update.effective_user.username)
        action = ctx.user_data.get("action")
        back_kb = InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="fc_main")]])
        back_admin_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Admin", callback_data="fc_admin")]])

        # Admin text inputs
        adm_action = ctx.user_data.get("adm_action")
        if adm_action and self.is_admin(uid) and update.message.text:
            text = update.message.text.strip()
            if adm_action == "set_maxsize":
                try:
                    mb = int(text)
                    await db_set_setting(self.db, self.bot_id, "max_file_mb", str(mb))
                    ctx.user_data.clear()
                    await update.message.reply_text(f"✅ Max file size set to {mb} MB", reply_markup=back_admin_kb)
                except ValueError:
                    await update.message.reply_text("❌ Enter a valid number.")
            elif adm_action == "broadcast":
                users = await self.db.fetchall("SELECT user_id FROM fc_users")
                sent = failed = 0
                for u in users:
                    try:
                        await update.get_bot().send_message(u["user_id"], text)
                        sent += 1
                    except Exception:
                        failed += 1
                ctx.user_data.clear()
                await update.message.reply_text(f"📨 Sent: {sent}, Failed: {failed}", reply_markup=back_admin_kb)
            return

        # Rename — waiting for new name text
        if action == "rename_wait_name" and update.message.text:
            new_name = update.message.text.strip()
            file_id = ctx.user_data.get("rename_file_id")
            orig_name = ctx.user_data.get("rename_orig_name", "file")
            ext = Path(orig_name).suffix
            if not new_name.endswith(ext):
                new_name = new_name + ext
            ctx.user_data.clear()
            await update.message.reply_text("⏳ Renaming...")
            try:
                file_obj = await update.get_bot().get_file(file_id)
                file_bytes = await file_obj.download_as_bytearray()
                await update.message.reply_document(
                    document=io.BytesIO(bytes(file_bytes)),
                    filename=new_name,
                    caption=f"✅ Renamed to: `{new_name}`",
                    parse_mode=ParseMode.MARKDOWN
                )
                await db_inc_conversion(self.db, uid)
            except Exception as e:
                logger.error("Rename error: %s", e)
                await update.message.reply_text("❌ Rename failed.", reply_markup=back_kb)
            return

        # /done command for multi-file operations
        if update.message.text and update.message.text.strip() == "/done":
            if action == "img_to_pdf":
                await self._finish_img_to_pdf(update, uid, ctx)
            elif action == "merge_pdf":
                await self._finish_merge_pdf(update, uid, ctx)
            return

        # File/document/photo received
        if not (update.message.document or update.message.photo):
            return

        max_mb = int(await db_get_setting(self.db, self.bot_id, "max_file_mb", str(MAX_FILE_MB_DEFAULT)))

        if update.message.photo:
            photo = update.message.photo[-1]
            if photo.file_size and photo.file_size > max_mb * 1024 * 1024:
                await update.message.reply_text(f"❌ File too large. Max {max_mb} MB.", reply_markup=back_kb)
                return

            if action == "compress_wait_file":
                ctx.user_data["compress_file"] = photo.file_id
                await update.message.reply_text(
                    "🗜 Select compression level:",
                    reply_markup=kb_compress_quality()
                )
                ctx.user_data["action"] = "compress_pick_quality"
                return

            if action == "img_to_pdf":
                ctx.user_data.setdefault("img_list", []).append(photo.file_id)
                count = len(ctx.user_data["img_list"])
                await update.message.reply_text(
                    f"✅ Image {count} added. Send more or type /done to convert.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Cancel", callback_data="fc_main")]])
                )
                return

        if update.message.document:
            doc: Document = update.message.document
            if doc.file_size and doc.file_size > max_mb * 1024 * 1024:
                await update.message.reply_text(f"❌ File too large. Max {max_mb} MB.", reply_markup=back_kb)
                return

            fname = doc.file_name or "file"
            ext = Path(fname).suffix.lower()

            # PDF → Images
            if action == "pdf_to_img":
                if ext != ".pdf":
                    await update.message.reply_text("❌ Please send a PDF file.", reply_markup=back_kb)
                    return
                fmt = ctx.user_data.get("pdf_fmt")
                if not fmt:
                    ctx.user_data["pending_pdf_file"] = doc.file_id
                    await update.message.reply_text(
                        "📄 Select output format:", reply_markup=kb_img_format()
                    )
                    return
                await self._do_pdf_to_images(update, uid, ctx, doc.file_id, fmt)
                return

            if action == "pdf_to_img" and ctx.user_data.get("pdf_fmt") is None:
                ctx.user_data["pending_pdf_file"] = doc.file_id
                await update.message.reply_text("Select format:", reply_markup=kb_img_format())
                return

            # Image compression via document
            if action in ("compress_wait_file", "compress_do"):
                if ext not in (".jpg", ".jpeg", ".png", ".webp"):
                    await update.message.reply_text("❌ Send a JPG or PNG image.", reply_markup=back_kb)
                    return
                ctx.user_data["compress_file"] = doc.file_id
                if ctx.user_data.get("compress_quality"):
                    await self._do_compress_doc(update, uid, ctx)
                else:
                    await update.message.reply_text("🗜 Select compression level:", reply_markup=kb_compress_quality())
                    ctx.user_data["action"] = "compress_pick_quality"
                return

            # Rename
            if action == "rename_wait_file":
                ctx.user_data["rename_file_id"] = doc.file_id
                ctx.user_data["rename_orig_name"] = fname
                ctx.user_data["action"] = "rename_wait_name"
                await update.message.reply_text(
                    f"✏️ File: `{fname}`\n\nEnter the new filename (without extension, or with):",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb_cancel()
                )
                return

            # Merge PDFs
            if action == "merge_pdf":
                if ext != ".pdf":
                    await update.message.reply_text("❌ Please send PDF files only.", reply_markup=back_kb)
                    return
                ctx.user_data.setdefault("pdf_list", []).append(doc.file_id)
                count = len(ctx.user_data["pdf_list"])
                await update.message.reply_text(
                    f"✅ PDF {count} added. Send more or type /done to merge.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Cancel", callback_data="fc_main")]])
                )
                return

            # Images → PDF via document
            if action == "img_to_pdf" and ext in (".jpg", ".jpeg", ".png"):
                ctx.user_data.setdefault("img_list", []).append(doc.file_id)
                count = len(ctx.user_data["img_list"])
                await update.message.reply_text(
                    f"✅ Image {count} added. Send more or /done.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Cancel", callback_data="fc_main")]])
                )
                return

    async def _do_pdf_to_images(self, update, uid, ctx, file_id, fmt):
        msg = await update.message.reply_text("⏳ Converting PDF to images... This may take a moment.")
        try:
            file_obj = await update.get_bot().get_file(file_id)
            pdf_bytes = await file_obj.download_as_bytearray()
            images = await pdf_to_images(bytes(pdf_bytes), fmt)
            await msg.edit_text(f"📤 Sending {len(images)} image(s)...")
            for i, img_bytes in enumerate(images, 1):
                ext = "jpg" if fmt == "jpg" else "png"
                await update.message.reply_document(
                    document=io.BytesIO(img_bytes),
                    filename=f"page_{i:03d}.{ext}",
                    caption=f"Page {i}/{len(images)}"
                )
            await db_inc_conversion(self.db, uid)
            ctx.user_data.clear()
            await update.message.reply_text(
                f"✅ Done! {len(images)} pages converted.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="fc_main")]])
            )
        except Exception as e:
            logger.error("PDF to images error: %s", e)
            await msg.edit_text(
                "❌ Conversion failed. Make sure it's a valid PDF.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="fc_main")]])
            )

    async def _do_compress_doc(self, update, uid, ctx):
        file_id = ctx.user_data.get("compress_file")
        quality = ctx.user_data.get("compress_quality", 60)
        msg = await update.message.reply_text("⏳ Compressing...")
        try:
            file_obj = await update.get_bot().get_file(file_id)
            img_bytes = await file_obj.download_as_bytearray()
            original_size = len(img_bytes)
            compressed = await compress_image(bytes(img_bytes), quality)
            new_size = len(compressed)
            saving = (1 - new_size / original_size) * 100
            await update.message.reply_document(
                document=io.BytesIO(compressed),
                filename="compressed.jpg",
                caption=f"✅ Compressed!\nOriginal: {original_size//1024} KB\nNew: {new_size//1024} KB\nSaved: {saving:.1f}%"
            )
            await db_inc_conversion(self.db, uid)
            ctx.user_data.clear()
        except Exception as e:
            logger.error("Compress error: %s", e)
            await msg.edit_text("❌ Compression failed.", reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Menu", callback_data="fc_main")
            ]]))

    async def _do_compress(self, q, uid, ctx):
        """Compress when quality already selected from callback."""
        file_id = ctx.user_data.get("compress_file")
        quality = ctx.user_data.get("compress_quality", 60)
        await q.edit_message_text("⏳ Compressing...")
        try:
            file_obj = await q.get_bot().get_file(file_id)
            img_bytes = await file_obj.download_as_bytearray()
            original_size = len(img_bytes)
            compressed = await compress_image(bytes(img_bytes), quality)
            new_size = len(compressed)
            saving = (1 - new_size / original_size) * 100
            await q.message.reply_document(
                document=io.BytesIO(compressed),
                filename="compressed.jpg",
                caption=f"✅ Compressed!\nOriginal: {original_size//1024} KB\nNew: {new_size//1024} KB\nSaved: {saving:.1f}%"
            )
            await db_inc_conversion(self.db, uid)
            ctx.user_data.clear()
        except Exception as e:
            logger.error("Compress error: %s", e)
            await q.edit_message_text("❌ Compression failed.", reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Menu", callback_data="fc_main")
            ]]))

    async def _finish_img_to_pdf(self, update, uid, ctx):
        img_list = ctx.user_data.get("img_list", [])
        if not img_list:
            await update.message.reply_text("❌ No images added yet.", reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Menu", callback_data="fc_main")
            ]]))
            return
        msg = await update.message.reply_text(f"⏳ Converting {len(img_list)} image(s) to PDF...")
        try:
            all_bytes = []
            for fid in img_list:
                f = await update.get_bot().get_file(fid)
                all_bytes.append(bytes(await f.download_as_bytearray()))
            pdf_bytes = await images_to_pdf(all_bytes)
            await update.message.reply_document(
                document=io.BytesIO(pdf_bytes),
                filename="converted.pdf",
                caption=f"✅ {len(img_list)} image(s) merged into PDF!"
            )
            await db_inc_conversion(self.db, uid)
            ctx.user_data.clear()
        except Exception as e:
            logger.error("Img to PDF error: %s", e)
            await msg.edit_text("❌ Conversion failed.", reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Menu", callback_data="fc_main")
            ]]))

    async def _finish_merge_pdf(self, update, uid, ctx):
        pdf_list = ctx.user_data.get("pdf_list", [])
        if len(pdf_list) < 2:
            await update.message.reply_text("❌ Send at least 2 PDFs to merge.")
            return
        msg = await update.message.reply_text(f"⏳ Merging {len(pdf_list)} PDFs...")
        try:
            all_bytes = []
            for fid in pdf_list:
                f = await update.get_bot().get_file(fid)
                all_bytes.append(bytes(await f.download_as_bytearray()))
            merged = await merge_pdfs(all_bytes)
            await update.message.reply_document(
                document=io.BytesIO(merged),
                filename="merged.pdf",
                caption=f"✅ {len(pdf_list)} PDFs merged!"
            )
            await db_inc_conversion(self.db, uid)
            ctx.user_data.clear()
        except Exception as e:
            logger.error("Merge PDF error: %s", e)
            await msg.edit_text("❌ Merge failed.", reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏠 Menu", callback_data="fc_main")
            ]]))

    async def build_app(self) -> Application:
        for ddl in [
            """CREATE TABLE IF NOT EXISTS fc_users (
                user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', conversions INTEGER DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS fc_settings (
                bot_id INTEGER, key TEXT, value TEXT, PRIMARY KEY(bot_id,key))""",
        ]:
            await self.db.execute(ddl)
        await self.db.commit()

        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("start", self.cmd_start))
        app.add_handler(CommandHandler("done", self._cmd_done))
        app.add_handler(CommandHandler("admin", self._cmd_admin))
        app.add_handler(CallbackQueryHandler(self.on_callback))
        app.add_handler(MessageHandler(
            (filters.Document.ALL | filters.PHOTO | filters.TEXT) & ~filters.COMMAND,
            self.on_message
        ))
        return app

    async def _cmd_done(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        """Handle /done command for multi-file operations."""
        action = ctx.user_data.get("action")
        uid = update.effective_user.id
        if action == "img_to_pdf":
            await self._finish_img_to_pdf(update, uid, ctx)
        elif action == "merge_pdf":
            await self._finish_merge_pdf(update, uid, ctx)

    async def _cmd_admin(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ Not authorized.")
            return
        await update.message.reply_text("🔧 *Admin Panel*", parse_mode=ParseMode.MARKDOWN,
                                         reply_markup=kb_admin())
