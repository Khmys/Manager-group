import logging
from telegram import Bot
from telegram.ext import Application, ContextTypes
from .rss_command import (
    get_all_subscriptions,
    scrape_posts,
    get_seen_ids,
    mark_seen,
    update_last_check,
)

logger = logging.getLogger(__name__)


async def check_all_subscriptions(app: Application):
    """Inaitwa kila saa — inakagua sites zote na kutuma updates."""
    bot: Bot = app.bot
    all_subs = await get_all_subscriptions()

    if not all_subs:
        return

    total_new = 0
    logger.info(f"[RSS] Inaanza — subscriptions: {len(all_subs)}")

    for entry in all_subs:
        chat_id = entry["chat_id"]
        sub = entry["sub"]
        url = sub["url"]
        site_name = sub["name"]

        try:
            _, posts = await scrape_posts(url)
        except Exception as e:
            logger.warning(f"[RSS] Imeshindwa {url}: {e}")
            continue

        seen = await get_seen_ids(chat_id, url)
        new_posts = [p for p in posts if p["id"] not in seen]

        await update_last_check(chat_id, url)

        if not new_posts:
            continue

        logger.info(f"[RSS] Mpya {len(new_posts)} — {site_name} → {chat_id}")
        total_new += len(new_posts)

        for post in new_posts[:5]:
            try:
                await bot.send_message(
                    chat_id=int(chat_id),
                    text=(
                        f"🆕 <b>{site_name}</b>\n\n"
                        f"📰 {post['title']}\n\n"
                        f"🔗 <a href='{post['link']}'>Soma zaidi</a>"
                    ),
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
            except Exception as e:
                logger.warning(f"[RSS] Kutuma kumeshindwa {chat_id}: {e}")

        if len(new_posts) > 5:
            try:
                await bot.send_message(
                    chat_id=int(chat_id),
                    text=(
                        f"📌 <b>{site_name}</b> ina posts "
                        f"<b>{len(new_posts) - 5}</b> zaidi mpya.\n"
                        f"Tembelea: <a href='{url}'>{url}</a>"
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        await mark_seen(chat_id, url, [p["id"] for p in new_posts])

    logger.info(f"[RSS] Imekamilika — posts mpya: {total_new}")


def setup_scheduler(app: Application, interval_minutes: int = 60):
    """Weka scheduler — iitwe mara moja tu ndani ya main.py."""

    async def _job_callback(context: ContextTypes.DEFAULT_TYPE):
        await check_all_subscriptions(app)

    app.job_queue.run_repeating(
        callback=_job_callback,
        interval=interval_minutes * 60,
        first=30,
        name="rss_checker",
    )
    logger.info(f"[RSS] Scheduler imewaka — kila dakika {interval_minutes}.")
