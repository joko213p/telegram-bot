import os
import re
import asyncio
import logging
import instaloader
import tempfile
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.environ["BOT_TOKEN"]

L = instaloader.Instaloader(
    download_videos=True,
    download_video_thumbnails=False,
    download_geotags=False,
    download_comments=False,
    save_metadata=False,
    compress_json=False,
    quiet=True,
)

IG_USER = os.environ.get("IG_USERNAME", "")
IG_PASS = os.environ.get("IG_PASSWORD", "")
if IG_USER and IG_PASS:
    try:
        L.login(IG_USER, IG_PASS)
        logger.info("✅ Connecté à Instagram")
    except Exception as e:
        logger.warning(f"⚠️ Connexion Instagram échouée : {e}")


def extract_username(text: str):
    patterns = [
        r"instagram\.com/([A-Za-z0-9_.]+)",
        r"^@?([A-Za-z0-9_.]+)$",
    ]
    for pat in patterns:
        m = re.search(pat, text.strip())
        if m:
            username = m.group(1).rstrip("/")
            if username not in ("p", "reel", "stories", "explore", "accounts"):
                return username
    return None


def choice_keyboard(username: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🎬 Reels", callback_data=f"reels|{username}"),
            InlineKeyboardButton("🖼️ Photos", callback_data=f"photos|{username}"),
        ],
        [
            InlineKeyboardButton("📖 Stories normales", callback_data=f"stories|{username}"),
            InlineKeyboardButton("⭐ Stories à la une", callback_data=f"highlights|{username}"),
        ],
        [
            InlineKeyboardButton("📦 Tout télécharger", callback_data=f"all|{username}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_file_safe(chat_id, context, path: Path, caption: str = ""):
    suffix = path.suffix.lower()
    try:
        if suffix in (".mp4", ".mov", ".webm"):
            with open(path, "rb") as f:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=f,
                    caption=caption[:1024] if caption else "",
                    supports_streaming=True,
                )
        elif suffix in (".jpg", ".jpeg", ".png", ".webp"):
            with open(path, "rb") as f:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=f,
                    caption=caption[:1024] if caption else "",
                )
    except Exception as e:
        logger.error(f"Erreur envoi {path.name}: {e}")
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Fichier trop lourd ou erreur : {path.name}")


async def download_reels(username, chat_id, context):
    await context.bot.send_message(chat_id, f"🎬 Téléchargement des Reels de @{username}…")
    try:
        profile = instaloader.Profile.from_username(L.context, username)
        with tempfile.TemporaryDirectory() as tmpdir:
            count = 0
            for post in profile.get_posts():
                if post.is_video:
                    L.download_post(post, target=tmpdir)
                    for f in sorted(Path(tmpdir).glob("*.mp4")):
                        await send_file_safe(chat_id, context, f, caption=f"🎬 Reel @{username}")
                        f.unlink(missing_ok=True)
                        count += 1
                    if count >= 30:
                        break
            if count == 0:
                await context.bot.send_message(chat_id, "❌ Aucun Reel trouvé (compte privé ou vide).")
            else:
                await context.bot.send_message(chat_id, f"✅ {count} Reel(s) envoyé(s) !")
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Erreur : {e}")


async def download_photos(username, chat_id, context):
    await context.bot.send_message(chat_id, f"🖼️ Téléchargement des Photos de @{username}…")
    try:
        profile = instaloader.Profile.from_username(L.context, username)
        with tempfile.TemporaryDirectory() as tmpdir:
            count = 0
            for post in profile.get_posts():
                if not post.is_video:
                    L.download_post(post, target=tmpdir)
                    files = list(Path(tmpdir).glob("*.jpg")) + list(Path(tmpdir).glob("*.png"))
                    for f in sorted(files):
                        await send_file_safe(chat_id, context, f, caption=f"🖼️ Photo @{username}")
                        f.unlink(missing_ok=True)
                        count += 1
                    if count >= 50:
                        break
            if count == 0:
                await context.bot.send_message(chat_id, "❌ Aucune photo trouvée (compte privé ou vide).")
            else:
                await context.bot.send_message(chat_id, f"✅ {count} photo(s) envoyée(s) !")
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Erreur : {e}")


async def download_stories(username, chat_id, context):
    if not (IG_USER and IG_PASS):
        await context.bot.send_message(
            chat_id,
            "⚠️ Les Stories nécessitent un compte Instagram.\n"
            "Ajoute IG_USERNAME et IG_PASSWORD dans Railway → Variables.",
        )
        return
    await context.bot.send_message(chat_id, f"📖 Téléchargement des Stories de @{username}…")
    try:
        profile = instaloader.Profile.from_username(L.context, username)
        with tempfile.TemporaryDirectory() as tmpdir:
            count = 0
            for story in L.get_stories(userids=[profile.userid]):
                for item in story.get_items():
                    L.download_storyitem(item, target=tmpdir)
                    for f in sorted(Path(tmpdir).iterdir()):
                        if f.suffix.lower() in (".mp4", ".jpg", ".jpeg", ".png"):
                            await send_file_safe(chat_id, context, f, caption=f"📖 Story @{username}")
                            f.unlink(missing_ok=True)
                            count += 1
            if count == 0:
                await context.bot.send_message(chat_id, "❌ Aucune story active trouvée.")
            else:
                await context.bot.send_message(chat_id, f"✅ {count} story(ies) envoyée(s) !")
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Erreur : {e}")


async def download_highlights(username, chat_id, context):
    if not (IG_USER and IG_PASS):
        await context.bot.send_message(
            chat_id,
            "⚠️ Les Stories à la une nécessitent un compte Instagram.\n"
            "Ajoute IG_USERNAME et IG_PASSWORD dans Railway → Variables.",
        )
        return
    await context.bot.send_message(chat_id, f"⭐ Téléchargement des Stories à la une de @{username}…")
    try:
        profile = instaloader.Profile.from_username(L.context, username)
        with tempfile.TemporaryDirectory() as tmpdir:
            count = 0
            for highlight in L.get_highlights(profile):
                for item in highlight.get_items():
                    L.download_storyitem(item, target=tmpdir)
                    for f in sorted(Path(tmpdir).iterdir()):
                        if f.suffix.lower() in (".mp4", ".jpg", ".jpeg", ".png"):
                            await send_file_safe(chat_id, context, f, caption=f"⭐ Highlight @{username} — {highlight.title}")
                            f.unlink(missing_ok=True)
                            count += 1
            if count == 0:
                await context.bot.send_message(chat_id, "❌ Aucune story à la une trouvée.")
            else:
                await context.bot.send_message(chat_id, f"✅ {count} média(s) envoyé(s) !")
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Erreur : {e}")


async def download_all(username, chat_id, context):
    await download_reels(username, chat_id, context)
    await download_photos(username, chat_id, context)
    await download_stories(username, chat_id, context)
    await download_highlights(username, chat_id, context)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Bonjour ! Je suis ton bot Instagram.\n\n"
        "📌 Envoie-moi un lien ou un pseudo Instagram :\n"
        "• https://www.instagram.com/nasa\n"
        "• @nasa\n"
        "• nasa\n\n"
        "Je te demanderai ensuite ce que tu veux télécharger 😊"
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Comment utiliser le bot :\n\n"
        "1️⃣ Envoie un lien ou pseudo Instagram\n"
        "2️⃣ Choisis ce que tu veux (Reels, Photos, Stories…)\n"
        "3️⃣ Le bot t'envoie tout directement ici !\n\n"
        "⚠️ Fonctionne uniquement avec les comptes publics.\n"
        "Les Stories nécessitent un compte Instagram configuré."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    username = extract_username(text)
    if not username:
        await update.message.reply_text(
            "❓ Lien non reconnu.\n\n"
            "Essaie :\n"
            "• https://www.instagram.com/nasa\n"
            "• @nasa\n"
            "• nasa"
        )
        return
    await update.message.reply_text(
        f"✅ Profil détecté : @{username}\n\nQue veux-tu télécharger ?",
        reply_markup=choice_keyboard(username),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action, username = query.data.split("|", 1)
    chat_id = query.effective_chat.id
    await query.edit_message_text(f"⏳ Téléchargement en cours pour @{username}…")

    if action == "reels":
        await download_reels(username, chat_id, context)
    elif action == "photos":
        await download_photos(username, chat_id, context)
    elif action == "stories":
        await download_stories(username, chat_id, context)
    elif action == "highlights":
        await download_highlights(username, chat_id, context)
    elif action == "all":
        await download_all(username, chat_id, context)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("🚀 Bot Instagram démarré !")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
