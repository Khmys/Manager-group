from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ContextTypes
from telegraph.aio import Telegraph
from bs4 import BeautifulSoup
from urllib.parse import urljoin

telegraph = Telegraph(access_token="522e083178bb4d7511cc1784c3f849b9e71164cdac06d08812181c1945dc")


NOISE_TEXTS = {
    "table of contents",
    "sign in with google to post a comment",
    "no comments yet. be the first!",
    "write a comment",
    "post comment",
    "turn on/off menu",
    "mshirikishe mwenzako",
    "copy",
    "related",
    "radio muhimu",
    "previous",
    "next",
    "share on telegram",
    "share on whatsapp",
    "share on facebook",
    "share on x",
    "print",
    "email a link to a friend",
}



# Moja tu - iliyosahihishwa na img
ALLOWED_TAGS = {
    "p", "a", "b", "strong", "i", "em", "u",
    "s", "blockquote", "code", "pre",
    "ul", "ol", "li", "br", "img"
}


# CSS selectors za sections zisizohitajika - zitafutwa kabisa
UNWANTED_SELECTORS = [
    # Share buttons
    ".sharedaddy",
    ".jp-relatedposts",
    ".sd-sharing",
    "[class*='share']",
    # Related posts
    "[class*='related']",
    ".related-posts",
    # Navigation prev/next
    ".post-navigation",
    ".nav-links",
    ".navigation",
    "[class*='navigation']",
    # Sidebar / widgets
    ".widget",
    ".sidebar",
    # Elementor extras
    ".elementor-share-btn",
    "[class*='social']",
    # Copy button area (firqatunnajia specific)
    ".wp-block-buttons",
    ".wp-block-button",
    # Comments
    "#comments",
    ".comments-area",
]


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def clean_html(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    
    # 1. Futa sections zote zisizohitajika kwanza (share, related, nav, n.k.)
    for selector in UNWANTED_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    for tag in soup.find_all(True):
        if tag.name and tag.name.lower() not in ALLOWED_TAGS:
            if tag.name.lower() in {
                "script", "style", "nav", "footer", "aside",
                "form", "button", "input", "xml", "svg", "meta",
                "link", "head", "noscript", "iframe", "canvas",
                "select", "textarea", "label", "header", "figure",
                "picture", "source", "video", "audio", "map", "area",
            }:
                tag.decompose()

    def process_node(tag):
        from bs4 import NavigableString, Tag

        if isinstance(tag, NavigableString):
            return str(tag)

        if not isinstance(tag, Tag):
            return ""

        name = tag.name.lower() if tag.name else ""

        if name == "img":
            src = tag.get("src", "").strip()
            if not src:
                return ""
            src = urljoin(base_url, src)
            if src.startswith("http"):
                return f'<img src="{src}"/>'
            return ""

        if name == "a":
            href = tag.get("href", "").strip()
            inner = "".join(process_node(child) for child in tag.children)
            if href:
                href = urljoin(base_url, href)
            if href.startswith("http") and inner.strip():
                return f'<a href="{href}">{inner}</a>'
            return inner

        inner = "".join(process_node(child) for child in tag.children)

        if not inner.strip():
            return ""

        tag_map = {
            "strong": "b",
            "em": "i",
            "h1": "h3",
            "h2": "h3",
            "h5": "h4",
            "h6": "h4",
        }

        mapped = tag_map.get(name, name)

        if not mapped or mapped not in ALLOWED_TAGS:
            return inner

        return f"<{mapped}>{inner}</{mapped}>"

    parts = []

    TOP_LEVEL_TAGS = {"p", "h2", "h3", "h4", "ul", "ol", "blockquote", "pre"}

    for tag in soup.find_all(list(TOP_LEVEL_TAGS) + ["img"], recursive=True):
        # Img - shughulikia moja kwa moja
        if tag.name == "img":
            src = tag.get("src", "").strip()
            if src:
                src = urljoin(base_url, src)
                if src.startswith("http"):
                    parts.append(f'<img src="{src}"/>')
            continue

        # Ruka tag ikiwa iko ndani ya top-level tag nyingine
        if any(parent.name in TOP_LEVEL_TAGS for parent in tag.parents):
            continue

        cleaned = process_node(tag)

        if cleaned.strip():
            plain = BeautifulSoup(cleaned, "html.parser").get_text().strip().lower()
            if plain and plain not in NOISE_TEXTS and len(plain) > 10:
                parts.append(cleaned)

    return "".join(parts)


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message

    if not context.args:
        await original_message.reply_text(
            "⚠️ Toa URL 🔗. Mfano: /get https://example.com"
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
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                try:
                    await page.goto(url, wait_until="commit", timeout=15000)
                except Exception:
                    await browser.close()
                    await original_message.reply_text(
                        "⚠️ Imeshindwa kufungua ukurasa. Jaribu tena baadaye."
                    )
                    return

            await page.wait_for_timeout(2000)
            

            h1 = await page.query_selector("h1")
            title = (
                (await h1.inner_text()).strip()
                if h1 else "Habari"
            )

            is_wordpress = await page.query_selector(
                "meta[name='generator'][content*='WordPress'], "
                "meta[name='generator'][content*='Elementor'], "
                "link[rel='https://api.w.org/']"
            )
            is_blogger = await page.query_selector(
                "meta[name='generator'][content*='Blogger']"
            )
            is_drupal = await page.query_selector(
                "meta[name='Generator'][content*='Drupal']"
            )
            is_medium = "medium.com" in url
            is_substack = "substack.com" in url
            is_firqatunnajia = "firqatunnajia.com" in url

            if is_firqatunnajia:
                content_selectors = [
                    ".elementor-widget-theme-post-content .elementor-widget-container",
                    ]
            
            elif is_wordpress:
                content_selectors = [
                    ".entry-content",
                    ".post-content",
                    "article .content",
                    "article",
                ]
            elif is_blogger:
                content_selectors = [
                    ".post-body",
                    ".entry-content",
                    "#post-body",
                    "article",
                ]
            elif is_drupal:
                content_selectors = [
                    ".field-items",
                    ".field-item",
                    ".node__content",
                    "#main-content",
                    ".region-content",
                ]
            elif is_medium:
                content_selectors = [
                    "article",
                    ".meteredContent",
                    "section",
                ]
            elif is_substack:
                content_selectors = [
                    ".body.markup",
                    ".available-content",
                    "article",
                ]
            
            
            else:
                content_selectors = [
                    "article",
                    ".entry-content",
                    ".post-content",
                    ".article-content",
                    "main article",
                    ".single-content",
                    "#content article",
                    ".content-area article",
                    ".site-content article",
                    "main",
                ]

            content_el = None
            for selector in content_selectors:
                el = await page.query_selector(selector)
                if el:
                    content_el = el
                    break

            if not content_el:
                content_el = await page.query_selector("body")

            if not content_el:
                await browser.close()
                await original_message.reply_text(
                    "⚠️ Imeshindwa kupata content."
                )
                return

            body_html = await content_el.inner_html()
            await browser.close()

        html_content = clean_html(body_html, base_url=url)

        if not html_content.strip():
            await original_message.reply_text(
                "⚠️ Imeshindwa kupata content."
            )
            return

        if len(html_content.encode("utf-8")) > 64000:
            html_content = html_content[:60000] + "<p>... (imekatwa)</p>"

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
