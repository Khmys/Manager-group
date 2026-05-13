import json
import os
import hashlib
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ContextTypes
from urllib.parse import urlparse

# ── Database ya JSON (rahisi, bila SQLite) ──────────────────────────
DB_FILE = "rss_subscriptions.json"


def load_db() -> dict:
    """Pakia database kutoka file."""
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db: dict):
    """Hifadhi database kwenye file."""
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def get_user_subs(chat_id: str) -> list:
    """Pata subscriptions za user."""
    db = load_db()
    return db.get(chat_id, [])


def add_subscription(chat_id: str, url: str, site_name: str) -> bool:
    """Ongeza subscription mpya. Rudisha False kama ipo tayari."""
    db = load_db()
    if chat_id not in db:
        db[chat_id] = []

    # Angalia kama URL ipo tayari
    for sub in db[chat_id]:
        if sub["url"] == url:
            return False

    db[chat_id].append({
        "url": url,
        "name": site_name,
        "seen_ids": [],       # Hashes za posts zilizoonwa
        "last_check": None,
    })
    save_db(db)
    return True


def remove_subscription(chat_id: str, url: str) -> bool:
    """Ondoa subscription. Rudisha False kama haipatikani."""
    db = load_db()
    if chat_id not in db:
        return False

    original_len = len(db[chat_id])
    db[chat_id] = [s for s in db[chat_id] if s["url"] != url]

    if len(db[chat_id]) == original_len:
        return False

    save_db(db)
    return True


def mark_seen(chat_id: str, url: str, post_ids: list):
    """Weka alama posts zilizotumwa."""
    db = load_db()
    for sub in db.get(chat_id, []):
        if sub["url"] == url:
            # Hifadhi hashes 100 za mwisho tu (kuzuia file kukua sana)
            sub["seen_ids"] = list(set(sub["seen_ids"] + post_ids))[-100:]
            break
    save_db(db)


def get_seen_ids(chat_id: str, url: str) -> set:
    """Pata IDs za posts zilizoonwa."""
    for sub in get_user_subs(chat_id):
        if sub["url"] == url:
            return set(sub.get("seen_ids", []))
    return set()


# ── Scraper ya posts ────────────────────────────────────────────────

def make_post_id(title: str, link: str) -> str:
    """Tengeneza ID ya kipekee kwa post."""
    raw = f"{title.strip().lower()}{link.strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


async def scrape_posts(url: str) -> tuple[str, list[dict]]:
    """
    Scrape posts kutoka website.
    Rudisha (site_name, [{"title": ..., "link": ..., "id": ...}])
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception:
            await page.goto(url, wait_until="load", timeout=45000)

        # Jina la site
        site_name = urlparse(url).netloc.replace("www.", "")
        title_tag = await page.query_selector("title")
        if title_tag:
            raw_title = await title_tag.inner_text()
            # Futa suffix kama "| Teknolojia" au "- BBC"
            site_name = raw_title.split("|")[0].split("-")[0].strip() or site_name

        # ── Selectors za posts ──────────────────────────────────────
        # Jaribu selectors mbalimbali — zinazopatikana ndizo zinatumiwa
        POST_SELECTORS = [
            # Standard article selectors
            "article h2 a",
            "article h3 a",
            ".post h2 a",
            ".post h3 a",
            ".entry-title a",
            ".post-title a",
            # News sites
            "h2.title a",
            "h3.title a",
            ".article-title a",
            ".news-title a",
            # List pages
            ".posts-list h2 a",
            ".blog-list h2 a",
            # Fallback — links zinazoonekana kama headlines
            "main h2 a",
            "main h3 a",
            "#main h2 a",
            "#content h2 a",
        ]

        posts = []
        seen_links = set()

        for selector in POST_SELECTORS:
            elements = await page.query_selector_all(selector)
            if not elements:
                continue

            for el in elements:
                title = (await el.inner_text()).strip()
                href = await el.get_attribute("href")

                if not title or not href:
                    continue

                # Fanya absolute URL
                if href.startswith("/"):
                    parsed = urlparse(url)
                    href = f"{parsed.scheme}://{parsed.netloc}{href}"
                elif not href.startswith("http"):
                    continue

                # Zuia kurudia
                if href in seen_links:
                    continue
                seen_links.add(href)

                post_id = make_post_id(title, href)
                posts.append({
                    "title": title,
                    "link": href,
                    "id": post_id,
                })

            # Kama tumepata posts, acha kutafuta
            if posts:
                break

        await browser.close()
        return site_name, posts


# ── Telegraph instant view ──────────────────────────────────────────
# (optional — reuse get_command logic kwa post content)

async def get_site_name(url: str) -> str:
    """Pata jina la site bila scraping posts."""
    parsed = urlparse(url)
    return parsed.netloc.replace("www.", "")


# ── Telegram command handlers ───────────────────────────────────────

async def rss_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /rss <url>         → Fuatilia site
    /rss list          → Orodha ya sites
    /rss stop <url>    → Acha kufuatilia
    /rss check         → Angalia updates sasa hivi
    """
    msg = update.message
    chat_id = str(msg.chat_id)
    args = context.args

    # ── /rss (bila args) ────────────────────────────────────────────
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

    # ── /rss list ───────────────────────────────────────────────────
    if subcommand == "list":
        subs = get_user_subs(chat_id)
        if not subs:
            await msg.reply_text("📭 Hufuatilii site yoyote bado.\n\nTumia /rss https://site.com kuanza.")
            return

        lines = ["📡 <b>Sites unazofuatilia:</b>\n"]
        for i, sub in enumerate(subs, 1):
            lines.append(f"{i}. <b>{sub['name']}</b>\n   <code>{sub['url']}</code>")

        await msg.reply_text("\n".join(lines), parse_mode="HTML")
        return

    # ── /rss stop <url> ─────────────────────────────────────────────
    if subcommand == "stop":
        if len(args) < 2:
            await msg.reply_text("⚠️ Toa URL. Mfano: /rss stop https://site.com")
            return

        target_url = args[1]
        removed = remove_subscription(chat_id, target_url)

        if removed:
            await msg.reply_text(f"🛑 Umesimama kufuatilia:\n<code>{target_url}</code>", parse_mode="HTML")
        else:
            await msg.reply_text("⚠️ URL hiyo haipatikani kwenye orodha yako.")
        return

    # ── /rss check ──────────────────────────────────────────────────
    if subcommand == "check":
        subs = get_user_subs(chat_id)
        if not subs:
            await msg.reply_text("📭 Hufuatilii site yoyote bado.")
            return

        await msg.reply_text("🔄 Ninakagua updates...")
        total_new = 0

        for sub in subs:
            new_posts = await _check_single_site(chat_id, sub, msg)
            total_new += new_posts

        if total_new == 0:
            await msg.reply_text("✅ Hakuna updates mpya kwa sasa.")
        return

    # ── /rss <url> → Fuatilia ───────────────────────────────────────
    url = args[0]
    if not (url.startswith("http://") or url.startswith("https://")):
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

    # Ongeza subscription
    added = add_subscription(chat_id, url, site_name)

    if not added:
        await wait_msg.edit_text(
            f"ℹ️ Tayari unafuatilia <b>{site_name}</b>.\n\n"
            f"Tumia /rss check kuangalia updates.",
            parse_mode="HTML",
        )
        return

    # Weka alama posts za sasa kama "seen" (zisiripotiwe mara ya kwanza)
    seen_ids = [p["id"] for p in posts]
    mark_seen(chat_id, url, seen_ids)

    await wait_msg.edit_text(
        f"✅ Umefuatilia <b>{site_name}</b> kwa mafanikio!\n\n"
        f"📊 Posts zilizopatikana: <b>{len(posts)}</b>\n"
        f"🕐 Utapata updates kila saa moja kiotomatiki.\n\n"
        f"Tumia /rss list kuona orodha yako.",
        parse_mode="HTML",
    )


async def _check_single_site(chat_id: str, sub: dict, msg_obj) -> int:
    """
    Kagua site moja na tuma posts mpya.
    Rudisha idadi ya posts mpya zilizotumwa.
    """
    url = sub["url"]
    site_name = sub["name"]

    try:
        _, posts = await scrape_posts(url)
    except Exception:
        return 0

    seen = get_seen_ids(chat_id, url)
    new_posts = [p for p in posts if p["id"] not in seen]

    if not new_posts:
        return 0

    # Tuma posts mpya (max 5 kwa wakati mmoja ili kuepuka spam)
    for post in new_posts[:5]:
        try:
            await msg_obj.reply_text(
                f"🆕 <b>{site_name}</b>\n\n"
                f"📰 {post['title']}\n\n"
                f"🔗 <a href='{post['link']}'>Soma zaidi</a>",
                parse_mode="HTML",
                disable_web_page_preview=False,
            )
        except Exception:
            pass

    if len(new_posts) > 5:
        await msg_obj.reply_text(
            f"📌 <b>{site_name}</b> ina posts <b>{len(new_posts) - 5}</b> zaidi mpya.\n"
            f"Tembelea: <a href='{url}'>{url}</a>",
            parse_mode="HTML",
        )

    # Weka alama zote kama seen
    mark_seen(chat_id, url, [p["id"] for p in new_posts])
    return len(new_posts)

