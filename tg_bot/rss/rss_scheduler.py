import logging
from datetime import datetime, timezone
from telegram import Bot
from telegram.ext import Application, ContextTypes
from .rss_command import (
    load_db,
    save_db,
    scrape_posts,
    get_seen_ids,
    mark_seen,
)

logger = logging.getLogger(__name__)


async def check_all_subscriptions(app: Application):
    """
    Inaitwa kila saa — inakagua sites zote na kutuma updates.
    DB inasomwa mara moja tu na kusavewa mara moja mwishoni — ufanisi zaidi.
    """
    db = load_db()
    bot: Bot = app.bot

    if not db:
        return

    total_users = len(db)
    total_new = 0
    logger.info(f"[RSS] Inaanza — watumiaji: {total_users}")

    now_iso = datetime.now(timezone.utc).isoformat()
    db_dirty = False  # Fuatilia kama db imebadilika — save mara moja tu

    for chat_id, subscriptions in db.items():
        for sub in subscriptions:
            url = sub["url"]
            site_name = sub["name"]

            try:
                _, posts = await scrape_posts(url)
            except Exception as e:
                logger.warning(f"[RSS] Imeshindwa {url}: {e}")
                continue

            # Pata seen_ids kutoka db iliyo kwenye kumbukumbu (si disk)
            seen = get_seen_ids(chat_id, url, db=db)
            new_posts = [p for p in posts if p["id"] not in seen]

            # Sasisha last_check kwa kila site iliyokaguliwa
            sub["last_check"] = now_iso
            db_dirty = True

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

            # Sasisha seen_ids ndani ya db iliyo kwenye kumbukumbu
            mark_seen(chat_id, url, [p["id"] for p in new_posts], db=db)

    # Save mara moja tu baada ya loop nzima — si kila URL
    if db_dirty:
        save_db(db)

    logger.info(f"[RSS] Imekamilika — posts mpya: {total_new}")


def setup_scheduler(app: Application, interval_minutes: int = 60):
    """
    Weka scheduler — iitwe mara moja tu ndani ya main.py.
    Inaanza baada ya sekunde 30 ili bot iwe tayari kabla ya check ya kwanza.
    """

    # MAREKEBISHO: async function badala ya lambda
    async def _job_callback(context: ContextTypes.DEFAULT_TYPE):
        await check_all_subscriptions(app)

    app.job_queue.run_repeating(
        callback=_job_callback,
        interval=interval_minutes * 60,
        first=30,
        name="rss_checker",
    )
    logger.info(f"[RSS] Scheduler imewaka — kila dakika {interval_minutes}.")
