import logging
from datetime import datetime, timezone
from telegram import Bot
from telegram.ext import Application
from rss.rss_command import (
    load_db,
    save_db,
    scrape_posts,
    get_seen_ids,
    mark_seen,
)

logger = logging.getLogger(__name__)


async def check_all_subscriptions(app: Application):
    """Inaitwa kila saa — inakagua sites zote na kutuma updates."""
    db = load_db()
    bot: Bot = app.bot

    if not db:
        return

    logger.info(f"[RSS] Inaanza — watumiaji: {len(db)}")

    for chat_id, subscriptions in db.items():
        for sub in subscriptions:
            url = sub["url"]
            site_name = sub["name"]

            try:
                _, posts = await scrape_posts(url)
            except Exception as e:
                logger.warning(f"[RSS] Imeshindwa {url}: {e}")
                continue

            seen = get_seen_ids(chat_id, url)
            new_posts = [p for p in posts if p["id"] not in seen]

            if not new_posts:
                continue

            logger.info(f"[RSS] Mpya {len(new_posts)} — {site_name} → {chat_id}")

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

            mark_seen(chat_id, url, [p["id"] for p in new_posts])
            _update_last_check(chat_id, url)

    logger.info("[RSS] Imekamilika.")


def _update_last_check(chat_id: str, url: str):
    db = load_db()
    for sub in db.get(chat_id, []):
        if sub["url"] == url:
            sub["last_check"] = datetime.now(timezone.utc).isoformat()
            break
    save_db(db)


def setup_scheduler(app: Application, interval_minutes: int = 60):
    """Weka scheduler — iitwe mara moja tu ndani ya main.py."""
    app.job_queue.run_repeating(
        callback=lambda context: check_all_subscriptions(app),
        interval=interval_minutes * 60,
        first=30,
        name="rss_checker",
    )
    logger.info(f"[RSS] Scheduler imewaka — kila dakika {interval_minutes}.")
