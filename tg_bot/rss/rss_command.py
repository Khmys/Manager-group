import hashlib
import os
from datetime import datetime, timezone
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ContextTypes
from urllib.parse import urlparse
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection

# ── Database (Motor - Async MongoDB) ────────────────────────────────
MONGO_URI = os.environ["MONGODB_URI"]
_client: AsyncIOMotorClient | None = None


def get_collection() -> AsyncIOMotorCollection:
    """Rudisha MongoDB collection — async, connection moja tu."""
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(
            MONGO_URI,
            serverSelectionTimeoutMS=10000,
            tls=True,
            tlsAllowInvalidCertificates=True,
        )
    return _client["rss_bot"]["subscriptions"]


async def get_user_subs(chat_id: str) -> list:
    doc = await get_collection().find_one({"chat_id": chat_id})
    return doc["subscriptions"] if doc else []


async def add_subscription(chat_id: str, url: str, site_name: str) -> bool:
    """Rudisha False kama URL ipo tayari."""
    col = get_collection()
    doc = await col.find_one({"chat_id": chat_id})

    if doc:
        for sub in doc["subscriptions"]:
            if sub["url"] == url:
                return False
        await col.update_one(
            {"chat_id": chat_id},
            {"$push": {"subscriptions": _new_sub(url, site_name)}},
        )
    else:
        await col.insert_one({
            "chat_id": chat_id,
            "subscriptions": [_new_sub(url, site_name)],
        })
    return True


def _new_sub(url: str, site_name: str) -> dict:
    return {
        "url": url,
        "name": site_name,
        "seen_ids": [],
        "last_check": None,
    }


async def remove_subscription(chat_id: str, url: str) -> bool:
    result = await get_collection().update_one(
        {"chat_id": chat_id},
        {"$pull": {"subscriptions": {"url": url}}},
    )
    return result.modified_count > 0


async def get_seen_ids(chat_id: str, url: str) -> set:
    doc = await get_collection().find_one(
        {"chat_id": chat_id, "subscriptions.url": url},
        {"subscriptions.$": 1},
    )
    if not doc or not doc.get("subscriptions"):
        return set()
    return set(doc["subscriptions"][0].get("seen_ids", []))


async def mark_seen(chat_id: str, url: str, post_ids: list):
    seen = await get_seen_ids(chat_id, url)
    combined = list(seen | set(post_ids))[-200:]
    await get_collection().update_one(
        {"chat_id": chat_id, "subscriptions.url": url},
        {"$set": {"subscriptions.$.seen_ids": combined}},
    )


async def update_last_check(chat_id: str, url: str):
    await get_collection().update_one(
        {"chat_id": chat_id, "subscriptions.url": url},
        {"$set": {"subscriptions.$.last_check": datetime.now(timezone.utc).isoformat()}},
    )


async def get_all_subscriptions() -> list[dict]:
    """Rudisha orodha ya {chat_id, sub} zote — kwa scheduler."""
    results = []
    async for doc in get_collection().find():
        chat_id = doc["chat_id"]
        for sub in doc.get("subscriptions", []):
            results.append({"chat_id": chat_id, "sub": sub})
    return results


# ── Scraper ─────────────────────────────────────────────────────────

def make_post_id(title: str, link: str) -> str:
    raw = f"{title.strip().lower()}{link.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


def _detect_platform(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if "jamiiforums.com" in domain:
        return "xenforo"
    if "naijaforum" in domain or "kenyatalk" in domain:
        return "xenforo"
    if "trtafrika.com" in domain:
        return "trtafrika"
    return "generic"


def _is_valid_thread_link(href: str, base_url: str) -> bool:
    parsed_base = urlparse(base_url)
    parsed_href = urlparse(href)
    if parsed_href.netloc and parsed_href.netloc != parsed_base.netloc:
        return False
    return "/threads/" in href


async def scrape_posts(url: str) -> tuple[str, list[dict]]:
    platform = _detect_platform(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
        except Exception:
            await page.goto(url, wait_until="load", timeout=45000)

        site_name = urlparse(url).netloc.replace("www.", "")
        title_tag = await page.query_selector("title")
        if title_tag:
            raw = await title_tag.inner_text()
            site_name = raw.split("|")[0].split("-")[0].strip() or site_name

        posts = []
        seen_links = set()
        parsed_base = urlparse(url)

        if platform == "trtafrika":
            elements = await page.query_selector_all("a[href*='/article/']")
            for el in elements:
                title = (await el.inner_text()).strip()
                href = await el.get_attribute("href")
                if not title or not href or len(title) < 10:
                    continue
                if href.startswith("/"):
                    href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
                href = href.split("?")[0]
                if href in seen_links:
                    continue
                seen_links.add(href)
                posts.append({"title": title, "link": href, "id": make_post_id(title, href)})
                if len(posts) >= 15:
                    break

        elif platform == "xenforo":
            SELECTORS = [
                ".block-container a[href*='/threads/']",
                ".structItem-title a[href*='/threads/']",
                ".contentRow-title a[href*='/threads/']",
                "a[href*='/threads/']",
            ]
            for selector in SELECTORS:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    title = (await el.inner_text()).strip()
                    href = await el.get_attribute("href")
                    if not title or not href or len(title) < 5:
                        continue
                    if href.startswith("/"):
                        href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
                    if not _is_valid_thread_link(href, url):
                        continue
                    href = href.split("?")[0].rstrip("/") + "/"
                    if href in seen_links:
                        continue
                    seen_links.add(href)
                    posts.append({"title": title, "link": href, "id": make_post_id(title, href)})
                if len(posts) >= 10:
                    break

        else:
            SELECTORS = [
                "article h2 a", "article h3 a",
                ".post h2 a", ".post h3 a",
                ".entry-title a", ".post-title a",
                "h2.title a", "h3.title a",
                ".article-title a", ".news-title a",
                "main h2 a", "main h3 a",
                "#main h2 a", "#content h2 a",
            ]
            for selector in SELECTORS:
                elements = await page.query_selector_all(selector)
                for el in elements:
                    title = (await el.inner_text()).strip()
                    href = await el.get_attribute("href")
                    if not title or not href:
                        continue
                    if href.startswith("/"):
                        href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"
                    elif not href.startswith("http"):
                        continue
                    if href in seen_links:
                        continue
                    seen_links.add(href)
                    posts.append({"title": title, "link": href, "id": make_post_id(title, href)})
                if posts:
                    break

        await browser.close()
        return site_name, posts


# ── Telegram Handlers ────────────────────────────────────────────────

async def rss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = str(msg.chat_id)
    args = context.args

    if not args:
        await msg.reply_text(
            "📡 <b>RSS Tracker</b>\n\n"
            "Amri zinazopatikana:\n"
            "• /rss <code>https://site.com</code> — Fuatilia site\n"
            "• /rss list — Orodha ya sites unazofuatilia\n"
            "• /rss stop <code>https://site.com</code> — Acha kufuatilia\n"
            "• /rss check — Angalia updates sasa hivi",
            parse_mode="HTML",
        )
        return

    subcommand = args[0].lower()

    if subcommand == "list":
        subs = await get_user_subs(chat_id)
        if not subs:
            await msg.reply_text("📭 Hufuatilii site yoyote bado.\n\nTumia /rss https://site.com kuanza.")
            return
        lines = ["📡 <b>Sites unazofuatilia:</b>\n"]
        for i, sub in enumerate(subs, 1):
            lines.append(f"{i}. <b>{sub['name']}</b>\n   <code>{sub['url']}</code>")
        await msg.reply_text("\n".join(lines), parse_mode="HTML")
        return

    if subcommand == "stop":
        if len(args) < 2:
            await msg.reply_text("⚠️ Toa URL. Mfano: /rss stop https://site.com")
            return
        removed = await remove_subscription(chat_id, args[1])
        if removed:
            await msg.reply_text(f"🛑 Umesimama kufuatilia:\n<code>{args[1]}</code>", parse_mode="HTML")
        else:
            await msg.reply_text("⚠️ URL hiyo haipatikani kwenye orodha yako.")
        return

    if subcommand == "check":
        subs = await get_user_subs(chat_id)
        if not subs:
            await msg.reply_text("📭 Hufuatilii site yoyote bado.")
            return
        await msg.reply_text("🔄 Ninakagua updates...")
        total = 0
        for sub in subs:
            total += await _check_and_send(chat_id, sub, bot=context.bot)
        if total == 0:
            await msg.reply_text("✅ Hakuna updates mpya kwa sasa.")
        return

    # /rss <url>
    url = args[0]
    if not url.startswith(("http://", "https://")):
        await msg.reply_text("⚠️ URL si sahihi. Lazima ianze na http:// au https://")
        return

    wait_msg = await msg.reply_text("🔄 Ninakagua site...")

    try:
        site_name, posts = await scrape_posts(url)
    except Exception as e:
        await wait_msg.edit_text(f"❌ Imeshindwa kukagua site: {e}")
        return

    if not posts:
        await wait_msg.edit_text(
            "⚠️ Imeshindwa kupata posts kutoka site hii.\n"
            "Site inaweza kuwa na muundo usiotarajiwa."
        )
        return

    added = await add_subscription(chat_id, url, site_name)
    if not added:
        await wait_msg.edit_text(
            f"ℹ️ Tayari unafuatilia <b>{site_name}</b>.\n\nTumia /rss check kuangalia updates.",
            parse_mode="HTML",
        )
        return

    await mark_seen(chat_id, url, [p["id"] for p in posts])

    await wait_msg.edit_text(
        f"✅ Umefuatilia <b>{site_name}</b>!\n\n"
        f"📊 Posts zilizopatikana: <b>{len(posts)}</b>\n"
        f"🕐 Utapata updates kila saa kiotomatiki.\n\n"
        f"Tumia /rss list kuona orodha yako.",
        parse_mode="HTML",
    )


async def _check_and_send(chat_id: str, sub: dict, bot) -> int:
    try:
        _, posts = await scrape_posts(sub["url"])
    except Exception:
        return 0

    seen = await get_seen_ids(chat_id, sub["url"])
    new_posts = [p for p in posts if p["id"] not in seen]

    if not new_posts:
        return 0

    for post in new_posts[:5]:
        try:
            await bot.send_message(
                chat_id=int(chat_id),
                text=(
                    f"🆕 <b>{sub['name']}</b>\n\n"
                    f"📰 {post['title']}\n\n"
                    f"🔗 <a href='{post['link']}'>Soma zaidi</a>"
                ),
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
        except Exception:
            pass

    if len(new_posts) > 5:
        try:
            await bot.send_message(
                chat_id=int(chat_id),
                text=(
                    f"📌 <b>{sub['name']}</b> ina posts "
                    f"<b>{len(new_posts) - 5}</b> zaidi mpya.\n"
                    f"Tembelea: <a href='{sub['url']}'>{sub['url']}</a>"
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await mark_seen(chat_id, sub["url"], [p["id"] for p in new_posts])
    await update_last_check(chat_id, sub["url"])
    return len(new_posts)
