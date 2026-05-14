import json
import os
import hashlib
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ContextTypes
from urllib.parse import urlparse

# ── Database ────────────────────────────────────────────────────────
DB_FILE = os.path.join(os.path.dirname(__file__), "rss_subscriptions.json")


def load_db() -> dict:
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def get_user_subs(chat_id: str) -> list:
    return load_db().get(chat_id, [])


def add_subscription(chat_id: str, url: str, site_name: str) -> bool:
    """Rudisha False kama URL ipo tayari."""
    db = load_db()
    if chat_id not in db:
        db[chat_id] = []
    for sub in db[chat_id]:
        if sub["url"] == url:
            return False
    db[chat_id].append({
        "url": url,
        "name": site_name,
        "seen_ids": [],
        "last_check": None,
    })
    save_db(db)
    return True


def remove_subscription(chat_id: str, url: str) -> bool:
    """Rudisha False kama URL haipatikani."""
    db = load_db()
    if chat_id not in db:
        return False
    before = len(db[chat_id])
    db[chat_id] = [s for s in db[chat_id] if s["url"] != url]
    if len(db[chat_id]) == before:
        return False
    save_db(db)
    return True


def mark_seen(chat_id: str, url: str, post_ids: list):
    db = load_db()
    for sub in db.get(chat_id, []):
        if sub["url"] == url:
            sub["seen_ids"] = list(set(sub["seen_ids"] + post_ids))[-100:]
            break
    save_db(db)


def get_seen_ids(chat_id: str, url: str) -> set:
    for sub in get_user_subs(chat_id):
        if sub["url"] == url:
            return set(sub.get("seen_ids", []))
    return set()


# ── Scraper ─────────────────────────────────────────────────────────

def make_post_id(title: str, link: str) -> str:
    raw = f"{title.strip().lower()}{link.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


def _detect_platform(url: str) -> str:
    """Tambua platform kutoka URL."""
    domain = urlparse(url).netloc.lower()
    if "jamiiforums.com" in domain:
        return "xenforo"
    if "naijaforum" in domain or "kenyatalk" in domain:
        return "xenforo"
    if "trtafrika.com" in domain:
        return "trtafrika"
    return "generic"


def _is_valid_thread_link(href: str, base_url: str) -> bool:
    """Angalia kama link ni thread halisi ya XenForo."""
    parsed_base = urlparse(base_url)
    parsed_href = urlparse(href)
    # Lazima iwe same domain
    if parsed_href.netloc and parsed_href.netloc != parsed_base.netloc:
        return False
    # XenForo threads zina /threads/ kwenye path
    return "/threads/" in href


async def scrape_posts(url: str) -> tuple[str, list[dict]]:
    """
    Scrape posts kutoka website yoyote.
    Rudisha (site_name, [{"title", "link", "id"}])
    """
    platform = _detect_platform(url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
        except Exception:
            await page.goto(url, wait_until="load", timeout=45000)

        # Jina la site
        site_name = urlparse(url).netloc.replace("www.", "")
        title_tag = await page.query_selector("title")
        if title_tag:
            raw = await title_tag.inner_text()
            site_name = raw.split("|")[0].split("-")[0].strip() or site_name

        posts = []
        seen_links = set()
        parsed_base = urlparse(url)

        # ── TRT Afrika ───────────────────────────────────────────────
        if platform == "trtafrika":
            # Links zote zenye /article/ kwenye href
            elements = await page.query_selector_all("a[href*='/article/']")

            for el in elements:
                title = (await el.inner_text()).strip()
                href = await el.get_attribute("href")

                if not title or not href or len(title) < 10:
                    continue

                # Fanya absolute URL
                if href.startswith("/"):
                    href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"

                # Futa duplicates — TRT inaonyesha link moja mara nyingi
                href = href.split("?")[0]
                if href in seen_links:
                    continue
                seen_links.add(href)

                posts.append({
                    "title": title,
                    "link": href,
                    "id": make_post_id(title, href),
                })

                if len(posts) >= 15:
                    break

        # ── XenForo (JamiiForums, n.k.) ─────────────────────────────
        if platform == "xenforo":
            # XenForo inatumia <a> za moja kwa moja zenye href ya /threads/
            # Zinaweza kuwa kwenye: featured, latest posts, trending
            XENFORO_SELECTORS = [
                # Featured content
                ".block-container a[href*='/threads/']",
                # Latest posts / whats new
                ".structItem-title a[href*='/threads/']",
                ".contentRow-title a[href*='/threads/']",
                # Trending
                "a[href*='/threads/']",
            ]

            for selector in XENFORO_SELECTORS:
                elements = await page.query_selector_all(selector)
                if not elements:
                    continue

                for el in elements:
                    title = (await el.inner_text()).strip()
                    href = await el.get_attribute("href")

                    if not title or not href or len(title) < 5:
                        continue

                    # Fanya absolute URL
                    if href.startswith("/"):
                        href = f"{parsed_base.scheme}://{parsed_base.netloc}{href}"

                    # Hakikisha ni thread halisi
                    if not _is_valid_thread_link(href, url):
                        continue

                    # Futa query strings (page numbers, n.k.)
                    href = href.split("?")[0].rstrip("/") + "/"

                    if href in seen_links:
                        continue
                    seen_links.add(href)

                    posts.append({
                        "title": title,
                        "link": href,
                        "id": make_post_id(title, href),
                    })

                if len(posts) >= 10:
                    break

        # ── Generic (blogu, news sites, n.k.) ───────────────────────
        else:
            POST_SELECTORS = [
                "article h2 a", "article h3 a",
                ".post h2 a", ".post h3 a",
                ".entry-title a", ".post-title a",
                "h2.title a", "h3.title a",
                ".article-title a", ".news-title a",
                ".posts-list h2 a", ".blog-list h2 a",
                "main h2 a", "main h3 a",
                "#main h2 a", "#content h2 a",
            ]

            for selector in POST_SELECTORS:
                elements = await page.query_selector_all(selector)
                if not elements:
                    continue

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

                    posts.append({
                        "title": title,
                        "link": href,
                        "id": make_post_id(title, href),
                    })

                if posts:
                    break

        await browser.close()
        return site_name, posts


# ── Telegram Handlers ────────────────────────────────────────────────

async def rss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rss                   → Msaada
    /rss <url>             → Fuatilia site
    /rss list              → Orodha ya sites
    /rss stop <url>        → Acha kufuatilia
    /rss check             → Kagua updates sasa hivi
    """
    msg = update.message
    chat_id = str(msg.chat_id)
    args = context.args

    # /rss bila args
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

    # /rss list
    if subcommand == "list":
        subs = get_user_subs(chat_id)
        if not subs:
            await msg.reply_text(
                "📭 Hufuatilii site yoyote bado.\n\n"
                "Tumia /rss https://site.com kuanza."
            )
            return
        lines = ["📡 <b>Sites unazofuatilia:</b>\n"]
        for i, sub in enumerate(subs, 1):
            lines.append(f"{i}. <b>{sub['name']}</b>\n   <code>{sub['url']}</code>")
        await msg.reply_text("\n".join(lines), parse_mode="HTML")
        return

    # /rss stop <url>
    if subcommand == "stop":
        if len(args) < 2:
            await msg.reply_text("⚠️ Toa URL. Mfano: /rss stop https://site.com")
            return
        removed = remove_subscription(chat_id, args[1])
        if removed:
            await msg.reply_text(
                f"🛑 Umesimama kufuatilia:\n<code>{args[1]}</code>",
                parse_mode="HTML",
            )
        else:
            await msg.reply_text("⚠️ URL hiyo haipatikani kwenye orodha yako.")
        return

    # /rss check
    if subcommand == "check":
        subs = get_user_subs(chat_id)
        if not subs:
            await msg.reply_text("📭 Hufuatilii site yoyote bado.")
            return
        await msg.reply_text("🔄 Ninakagua updates...")
        total = 0
        for sub in subs:
            total += await _check_and_send(chat_id, sub, bot=msg)
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

    added = add_subscription(chat_id, url, site_name)
    if not added:
        await wait_msg.edit_text(
            f"ℹ️ Tayari unafuatilia <b>{site_name}</b>.\n\n"
            "Tumia /rss check kuangalia updates.",
            parse_mode="HTML",
        )
        return

    # Weka alama posts za sasa kama seen — zisiripotiwe mara ya kwanza
    mark_seen(chat_id, url, [p["id"] for p in posts])

    await wait_msg.edit_text(
        f"✅ Umefuatilia <b>{site_name}</b>!\n\n"
        f"📊 Posts zilizopatikana: <b>{len(posts)}</b>\n"
        f"🕐 Utapata updates kila saa kiotomatiki.\n\n"
        f"Tumia /rss list kuona orodha yako.",
        parse_mode="HTML",
    )


async def _check_and_send(chat_id: str, sub: dict, bot) -> int:
    """Kagua site moja na tuma posts mpya. Rudisha idadi ya posts mpya."""
    try:
        _, posts = await scrape_posts(sub["url"])
    except Exception:
        return 0

    seen = get_seen_ids(chat_id, sub["url"])
    new_posts = [p for p in posts if p["id"] not in seen]

    if not new_posts:
        return 0

    for post in new_posts[:5]:
        try:
            await bot.reply_text(
                f"🆕 <b>{sub['name']}</b>\n\n"
                f"📰 {post['title']}\n\n"
                f"🔗 <a href='{post['link']}'>Soma zaidi</a>",
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
        except Exception:
            pass

    if len(new_posts) > 5:
        await bot.reply_text(
            f"📌 <b>{sub['name']}</b> ina posts <b>{len(new_posts) - 5}</b> zaidi mpya.\n"
            f"Tembelea: <a href='{sub['url']}'>{sub['url']}</a>",
            parse_mode="HTML",
        )

    mark_seen(chat_id, sub["url"], [p["id"] for p in new_posts])
    return len(new_posts)
