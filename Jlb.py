from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ContextTypes
from telegraph.aio import Telegraph
from bs4 import BeautifulSoup
from urllib.parse import urljoin

NOISE_TEXTS = {
    "table of contents",
    "sign in with google to post a comment",
    "no comments yet. be the first!",
    "write a comment",
    "post comment",
    "home",
    "products",
    "comparisons",
    "brands",
    "news",
    "categories",
    "related posts",
    "recent posts",
    "popular posts",
    "share",
    "advertisement",
    "menu",
    "search",
    "next post",
    "previous post",
    "recommended",
}

telegraph = Telegraph(access_token="522e083178bb4d7511cc1784c3f849b9e71164cdac06d08812181c1945dc")

ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "s", "a",
    "p", "br", "h3", "h4", "ul", "ol", "li",
    "blockquote", "pre", "code", "img"
}


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def clean_html(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    def process_node(tag):
        from bs4 import NavigableString, Tag

        if isinstance(tag, NavigableString):
            return str(tag)

        if not isinstance(tag, Tag):
            return ""

        name = tag.name.lower() if tag.name else ""

        # Ondoa sections zisizotakiwa
        if name in {
            "script", "style", "nav", "footer",
            "aside", "form", "button", "input",
            "header", "menu", "noscript"
        }:
            return ""

        # Ondoa classes zenye dalili za noise
        classes = " ".join(tag.get("class", [])).lower()
        ids = str(tag.get("id", "")).lower()

        blocked_keywords = [
            "menu", "nav", "header", "footer",
            "sidebar", "widget", "comment",
            "share", "related", "promo",
            "advert", "breadcrumb",
            "newsletter", "popup"
        ]

        if any(word in classes for word in blocked_keywords) or any(
            word in ids for word in blocked_keywords
        ):
            return ""

        # Picha
        if name == "img":
            src = tag.get("src", "").strip()
            alt = tag.get("alt", "").lower()

            # Ondoa logo/profile icons
            if any(x in alt for x in ["logo", "icon", "avatar", "profile"]):
                return ""

            if not src:
                return ""

            src = urljoin(base_url, src)

            if src.startswith("http"):
                return f'<img src="{src}"/>'

            return ""

        # Links
        if name == "a":
            href = tag.get("href", "").strip()
            inner = "".join(process_node(child) for child in tag.children)

            if href:
                href = urljoin(base_url, href)

            if href.startswith("http") and inner.strip():
                return f'<a href="{href}">{inner}</a>'

            return inner

        # Children
        inner = "".join(process_node(child) for child in tag.children)

        if not inner.strip():
            return ""

        # Map tags
        tag_map = {
            "strong": "b",
            "em": "i",
            "h1": "h3",
            "h2": "h3",
            "h5": "h4",
            "h6": "h4",
        }

        mapped = tag_map.get(name, name)

        if mapped in ALLOWED_TAGS:
            return f"<{mapped}>{inner}</{mapped}>"

        return inner

    parts = []

    # Tafuta sehemu kuu ya article
    main = (
        soup.find("article")
        or soup.find("main")
        or soup.find(class_=lambda c: c and any(
            x in str(c).lower()
            for x in [
                "post-content",
                "article-content",
                "entry-content",
                "post-body",
                "article-body",
                "content"
            ]
        ))
        or soup.body
    )

    if not main:
        return ""

    for tag in main.find_all(
        [
            "p", "h2", "h3", "h4",
            "ul", "ol", "blockquote",
            "pre", "img"
        ],
        recursive=True
    ):
        cleaned = process_node(tag)

        if not cleaned.strip():
            continue

        # Ruhusu picha tu meaningful
        if cleaned.startswith("<img"):
            parts.append(cleaned)
            continue

        plain = BeautifulSoup(
            cleaned,
            "html.parser"
        ).get_text().strip().lower()

        # Chuja noise
        if (
            plain
            and plain not in NOISE_TEXTS
            and len(plain) > 25
        ):
            parts.append(cleaned)

    return "".join(parts)


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message

    if not context.args:
        await original_message.reply_text(
            "⚠️ Toa URL. Mfano: /get https://example.com"
        )
        return

    url = context.args[0]

    if not is_url(url):
        await original_message.reply_text(
            "⚠️ URL si sahihi. Lazima ianze na http:// au https://"
        )
        return

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            page = await browser.new_page(
                user_agent="Mozilla/5.0"
            )

            await page.goto(
                url,
                wait_until="networkidle",
                timeout=60000
            )

            # Title
            h1 = await page.query_selector("h1")
            title = (
                (await h1.inner_text()).strip()
                if h1 else "Habari"
            )

            # Jaribu article/main kwanza
            content_element = (
                await page.query_selector("article")
                or await page.query_selector("main")
                or await page.query_selector("body")
            )

            if not content_element:
                await browser.close()
                await original_message.reply_text(
                    "⚠️ Imeshindwa kupata content."
                )
                return

            body_html = await content_element.inner_html()

            await browser.close()

        html_content = clean_html(
            body_html,
            base_url=url
        )

        if not html_content.strip():
            await original_message.reply_text(
                "⚠️ Imeshindwa kupata content."
            )
            return

        # Telegraph size limit
        if len(html_content.encode("utf-8")) > 64000:
            html_content = html_content[:60000] + "<p>... (imekatwa)</p>"

        # Create Telegraph page
        page_data = await telegraph.create_page(
            title=title,
            html_content=html_content,
        )

        telegraph_url = f"https://telegra.ph/{page_data['path']}"

        await original_message.reply_text(
            f"📄 <b>{title}</b>\n\n"
            f"🔗 <a href='{telegraph_url}'>Soma hapa (Instant View)</a>",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )

    except Exception as e:
        await original_message.reply_text(
            f"❌ Hitilafu: {e}"
        )         if href:
                href = urljoin(base_url, href)

            if href.startswith("http") and inner.strip():
                return f'<a href="{href}">{inner}</a>'

            return inner

        # Process watoto
        inner = "".join(process_node(child) for child in tag.children)

        if not inner.strip():
            return ""

        # Mapping
        tag_map = {
            "strong": "b",
            "em": "i",
            "h1": "h3",
            "h2": "h3",
            "h5": "h4",
            "h6": "h4",
        }

        mapped = tag_map.get(name, name)

        if mapped in ALLOWED_TAGS:
            return f"<{mapped}>{inner}</{mapped}>"

        return inner

    parts = []

    for tag in soup.find_all(
        [
            "p", "h2", "h3", "h4",
            "ul", "ol", "blockquote",
            "pre", "img"
        ],
        recursive=True
    ):
        cleaned = process_node(tag)

        if cleaned.strip():
            # Kama ni picha, iingize moja kwa moja
            if cleaned.startswith("<img"):
                parts.append(cleaned)
                continue

            plain = BeautifulSoup(
                cleaned,
                "html.parser"
            ).get_text().strip().lower()

            if (
                plain
                and plain not in NOISE_TEXTS
                and len(plain) > 10
            ):
                parts.append(cleaned)

    return "".join(parts)


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message

    if not context.args:
        await original_message.reply_text(
            "⚠️ Toa URL. Mfano: /get https://example.com"
        )
        return

    url = context.args[0]

    if not is_url(url):
        await original_message.reply_text(
            "⚠️ URL si sahihi. Lazima ianze na http:// au https://"
        )
        return

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)

            page = await browser.new_page(
                user_agent="Mozilla/5.0"
            )

            await page.goto(
                url,
                wait_until="networkidle",
                timeout=60000
            )

            # Title
            h1 = await page.query_selector("h1")
            title = (
                (await h1.inner_text()).strip()
                if h1 else "Habari"
            )

            # Body content
            body = await page.query_selector("body")

            if not body:
                await browser.close()
                await original_message.reply_text(
                    "⚠️ Imeshindwa kupata content."
                )
                return

            body_html = await body.inner_html()

            await browser.close()

        # Safisha content
        html_content = clean_html(
            body_html,
            base_url=url
        )

        if not html_content.strip():
            await original_message.reply_text(
                "⚠️ Imeshindwa kupata content."
            )
            return

        # Telegraph size limit
        if len(html_content.encode("utf-8")) > 64000:
            html_content = html_content[:60000] + "<p>... (imekatwa)</p>"

        # Create Telegraph page
        page_data = await telegraph.create_page(
            title=title,
            html_content=html_content,
        )

        telegraph_url = f"https://telegra.ph/{page_data['path']}"

        await original_message.reply_text(
            f"📄 <b>{title}</b>\n\n"
            f"🔗 <a href='{telegraph_url}'>Soma hapa (Instant View)</a>",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )

    except Exception as e:
        await original_message.reply_text(
            f"❌ Hitilafu: {e}"
        )
