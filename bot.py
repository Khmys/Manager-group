import os
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes



#WebHook
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route





# Chukua token kutoka environment variable
TOKEN = os.getenv("Token")
OWNER_ID = int(os.getenv("OWNER_ID", "654648997"))
ERROR_GROUP_ID = int(os.getenv("ERROR_GROUP_ID", "-1002158955567"))

URL = os.getenv("URL")
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

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

            # Anzisha task ya kufuta ujumbe baada ya muda
            asyncio.create_task(kufuta_ujumbe(sent_message, context))

        except Exception as e:
            error_message = f"Hitilafu wakati wa kutuma ujumbe wa kukaribisha: {e}"
            await bot.send_message(chat_id=ERROR_GROUP_ID, text=error_message)

async def kufuta_ujumbe(sent_message, context: ContextTypes.DEFAULT_TYPE, delay: int = 60):
    """Futa ujumbe baada ya sekunde fulani (chaguo-msingi: 60)."""
    await asyncio.sleep(delay)
    try:
        await sent_message.delete()
    except Exception as e:
        error_message = f"Hitilafu wakati wa kufuta ujumbe: {e}"
        await context.bot.send_message(chat_id=ERROR_GROUP_ID, text=error_message)






async def delete_left_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Hakikisha ni ujumbe wa mtu kuondoka
        if update.message.left_chat_member:
            left_mem = update.effective_message.left_chat_member
            bot = context.bot
            
            if left_mem:
                # Ignore bot being kicked
                if left_mem.id == bot.id:
                    return

            # Give the owner a special goodbye
            if left_mem.id == OWNER_ID:
                await update.effective_message.reply_html(f"Kwaheri  {left_mem.mention_html()} 👑")
                return
                
        
            await update.message.delete()
    except Exception as e:
        error_message = f"Hitilafu wakati wa kufuta ujumbe: {e}"
        await context.bot.send_message(chat_id=ERROR_GROUP_ID, text=error_message)







async def telegram(request: Request) -> Response:
    """Shughulikia webhook requests kutoka Telegram"""
    data = await request.json()
    await app.update_queue.put(Update.de_json(data=data, bot=app.bot))
    return Response()


async def main():
    global app  # ili itumike ndani ya `telegram()`
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, delete_left_message))
    
    # Tengeneza Starlette app
    starlette_app = Starlette(
        routes=[
            Route("/telegram", telegram, methods=["POST"]),
        ]
    )

    # Tengeneza uvicorn server
    webserver = uvicorn.Server(
        config=uvicorn.Config(
            app=starlette_app,
            host="0.0.0.0",
            port=PORT,
            log_level="info"
        )
    )

    # Weka webhook
    await app.bot.set_webhook(url=f"{URL}/telegram")

    # Anzisha bot na webserver
    async with app:
        await app.start()
        await webserver.serve()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
