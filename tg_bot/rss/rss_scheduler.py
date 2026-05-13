import json
import logging
from datetime import datetime, timezone
from telegram import Bot
from telegram.ext import Application
from rss_command import (
    load_db,
    save_db,
    scrape_posts,
    get_seen_ids,
    mark_seen,
)

logger = logging.getLogger(__name__)


async def check_all_subscriptions(app: Application):
    """
    Inaitwa kila saa na APScheduler.
    Inakagua sites zote za watumiaji wote na kutuma updates.
    """
    db = load_db()
    bot: Bot = app.bot

    if not db:
        return

    logger.info(f"[RSS Scheduler] Inaanza kukagua — watumiaji: {len(db)}")

    for chat_id, subscriptions in db.items():
        if not subscriptions:
            continue

        for sub in subscriptions:
            url = sub["url"]
            site_name = sub["name"]

            try:
                _, posts = await scrape_posts(url)
            except Exception as e:
                logger.warning(f"[RSS] Imeshindwa kuscrape {url}: {e}")
                continue

            if not posts:
                continue

            seen = get_seen_ids(chat_id, url)
            new_posts = [p for p in posts if p["id"] not in seen]

            if not new_posts:
                logger.info(f"[RSS] Hakuna mpya — {site_name} ({chat_id})")
                continue

            logger.info(f"[RSS] Posts mpya {len(new_posts)} — {site_name} ({chat_id})")

            # Tuma posts mpya
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
                    logger.warning(f"[RSS] Imeshindwa kutuma kwa {chat_id}: {e}")

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

            # Weka alama na update wakati wa ukaguzi
            mark_seen(chat_id, url, [p["id"] for p in new_posts])
            _update_last_check(chat_id, url)

    logger.info("[RSS Scheduler] Imekamilika.")


def _update_last_check(chat_id: str, url: str):
    """Update wakati wa ukaguzi wa mwisho."""
    db = load_db()
    for sub in db.get(chat_id, []):
        if sub["url"] == url:
            sub["last_check"] = datetime.now(timezone.utc).isoformat()
            break
    save_db(db)


def setup_scheduler(app: Application, interval_minutes: int = 60):
    """
    Weka scheduler kwenye Application ya PTB.
    Inaitwa mara moja wakati bot inaanzishwa.
    
    interval_minutes: Muda kati ya ukaguzi (default: saa 1)
    """
    job_queue = app.job_queue

    job_queue.run_repeating(
        callback=lambda context: check_all_subscriptions(app),
        interval=interval_minutes * 60,   # sekunde
        first=30,                          # Subiri sekunde 30 baada ya bot kuanza
        name="rss_checker",
    )

    logger.info(f"[RSS Scheduler] Imewashwa — ukaguzi kila dakika {interval_minutes}.")

