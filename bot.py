import os
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route
import uvicorn
from Jlb import get_command

from rss.rss_command import rss_command
from rss.rss_scheduler import setup_scheduler

OWNER_ID = int(os.getenv("OWNER_ID", "654648997"))
ERROR_GROUP_ID = int(os.getenv("ERROR_GROUP_ID", "-1002158955567"))
BOT_TOKEN = "8063489420:AAGq0Ulkx1fY2EPA_FIKTg42e3hNBMyciqM"
URL = os.getenv("URL", "https://web-production-abe9c.up.railway.app")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

app = None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Habari! Mimi ni bot wako 😊")


async def welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    bot = context.bot
    new_members = update.effective_message.new_chat_members

    for member in new_members:
        if member.id == bot.id:
            continue
        try:
            sent_message = await message.reply_text(
                f"Karibu sana {member.mention_html()} kwenye group letu! 🎉",
                parse_mode="HTML"
            )
            asyncio.create_task(kufuta_ujumbe(sent_message, context))
        except Exception as e:
            await bot.send_message(chat_id=ERROR_GROUP_ID, text=f"Hitilafu: {e}")


async def kufuta_ujumbe(sent_message, context: ContextTypes.DEFAULT_TYPE, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await sent_message.delete()
    except Exception as e:
        await context.bot.send_message(chat_id=ERROR_GROUP_ID, text=f"Hitilafu: {e}")


async def delete_left_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.left_chat_member:
            left_mem = update.effective_message.left_chat_member
            bot = context.bot

            if left_mem.id == bot.id:
                return

            if left_mem.id == OWNER_ID:
                await update.effective_message.reply_html(
                    f"Kwaheri 🙌 {left_mem.mention_html()} 👑"
                )
                return

            await update.message.delete()
    except Exception as e:
        await context.bot.send_message(chat_id=ERROR_GROUP_ID, text=f"Hitilafu: {e}")


async def telegram_webhook(request: Request):
    data = await request.json()
    await app.update_queue.put(Update.de_json(data, app.bot))
    return Response()


async def main():
    global app

    app = Application.builder().token(BOT_TOKEN).build()

    # Sajili handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("get", get_command))
    
        # ── Handlers ───────
    app.add_handler(CommandHandler("rss", rss_command))

    # ── Washa RSS Scheduler ──
    setup_scheduler(app, interval_minutes=60)  # Kagua kila saa 1
    
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, delete_left_message))

    starlette_app = Starlette(
        routes=[Route("/telegram", telegram_webhook, methods=["POST"])]
    )

    server = uvicorn.Server(
        uvicorn.Config(
            app=starlette_app,
            host="0.0.0.0",
            port=PORT,
            log_level="info"
        )
    )

    await app.bot.set_webhook(f"{URL}/telegram")

    async with app:
        await app.start()
        await server.serve()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
