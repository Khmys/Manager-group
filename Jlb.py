import re
import httpx
from telegram import Update
from telegram.ext import ContextTypes
from telegraph.aio import Telegraph
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.async_api import async_playwright

telegraph = Telegraph(
    access_token="522e083178bb4d7511cc1784c3f849b9e71164cdac06d08812181c1945dc"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

NOISE_TEXTS = {
    "table of contents",
    "sign in with google to post a comment",
    "no comments yet. be the first!",
    "write a comment",
    "post comment",
    "related posts",
    "share this",
    "leave a reply",
}

ALLOWED_TAGS = {
    "p", "a", "b", "strong", "i", "em", "u",
    "s", "blockquote", "code", "pre",
    "ul", "ol", "li", "br", "img",
    "h3", "h4"
}

UNWANTED_SELECTORS = [
    ".breadcrumb",
    ".grid_4",
    ".region-sidebar-second",
    ".block-views",
    ".view-similarterms",
    ".region-footer",
    ".block-menu",
    ".block-block",
    ".block-superfish",
    ".sharedaddy",
    ".jp-relatedposts",
    ".sd-sharing",
    "[class*='share']",
    "[class*='related']",
    ".related-posts",
    ".post-navigation",
    ".nav-links",
    ".navigation",
    ".widget",
    ".sidebar",
    ".elementor-share-btn",
    "[class*='social']",
    ".elementor-social-icons-wrapper",
    ".elementor-counter",
    ".elementor-search-form__container",
    ".wp-block-buttons",
    ".wp-block-button",
    "#comments",
    ".comments-area",
    ".aps-container",
]

TOP_LEVEL_TAGS = {
    "p", "h2", "h3", "h4",
    "ul", "ol", "blockquote", "pre"
}


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def detect_platform(soup: BeautifulSoup, url: str):
    generator = soup.find("meta", attrs={"name": "generator"})
    gen_content = (generator.get("content", "") if generator else "").lower()

    if "wordpress" in gen_content or "elementor" in gen_content:
        return "wordpress"
    if soup.find("link", attrs={"rel": "https://api.w.org/"}):
        return "wordpress"
    if "blogger" in gen_content:
        return "blogger"
    if "drupal" in gen_content:
        return "drupal"
    if "medium.com" in url:
        return "medium"
    if "substack.com" in url:
        return "substack"
    return "generic"


def get_content_selectors(platform: str):
    selectors = {
        "wordpress": [
            ".elementor-widget-theme-post-content .elementor-widget-container",
            ".entry-content",
            ".post-content",
            "article .content",
            "article",
        ],
        "blogger": [
            ".post-body",
            ".entry-content",
            "#post-body",
            "article",
        ],
        "drupal": [
            ".field-name-body .field-item",
            ".field-name-body",
            ".node__content",
            "#main-content",
            ".region-content",
        ],
        "medium": [
            "article",
            ".meteredContent",
            "section",
        ],
        "substack": [
            ".body.markup",
            ".available-content",
            "article",
        ],
        "generic": [
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
        ],
    }
    return selectors.get(platform, selectors["generic"])


def find_content_element(soup: BeautifulSoup, selectors: list):
    for selector in selectors:
        el = soup.select_one(selector)
        if el:
            return el
    return soup.find("body")


def clean_html(html: str, base_url: str) -> str:
    html = re.sub(r'<\?xml[^>]*\?>', '', html)
    html = re.sub(r'<xml[^>]*>.*?</xml>', '', html, flags=re.DOTALL)

    soup = BeautifulSoup(html, "lxml")

    for selector in UNWANTED_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    for tag in soup.find_all(True):
        if tag.name.lower() in {
            "script", "style", "nav", "footer", "aside",
            "form", "button", "input", "xml", "svg",
            "meta", "link", "head", "noscript",
            "iframe", "canvas", "select", "textarea",
            "label", "header", "figure", "picture",
            "source", "video", "audio", "map", "area",
        }:
            tag.decompose()

    seen_images = set()

    def process_node(tag):
        from bs4 import NavigableString, Tag

        if isinstance(tag, NavigableString):
            return str(tag)

        if not isinstance(tag, Tag):
            return ""

        name = tag.name.lower()

        if name == "img":
            src = tag.get("src", "").strip()
            if not src:
                return ""

            src = urljoin(base_url, src)

            if src in seen_images:
                return ""

            seen_images.add(src)

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

        if mapped not in ALLOWED_TAGS:
            return inner

        return f"<{mapped}>{inner}</{mapped}>"

    parts = []

    for tag in soup.find_all(list(TOP_LEVEL_TAGS) + ["img"], recursive=True):
        if tag.name == "img":
            src = tag.get("src", "").strip()

            if src:
                src = urljoin(base_url, src)

                if src.startswith("http") and src not in seen_images:
                    seen_images.add(src)
                    parts.append(f'<img src="{src}"/>')
            continue

        if any(parent.name in TOP_LEVEL_TAGS for parent in tag.parents):
            continue

        cleaned = process_node(tag)

        if cleaned.strip():
            plain = BeautifulSoup(cleaned, "lxml").get_text().strip().lower()

            if (
                plain
                and plain not in NOISE_TEXTS
                and len(plain) > 10
            ):
                parts.append(cleaned)

    final = "".join(parts)

    soup_fix = BeautifulSoup(final, "lxml")

    return soup_fix.decode_contents()


async def fetch_with_httpx(url: str):
    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=30,
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def fetch_with_playwright(url: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        page = await browser.new_page(
            user_agent=HEADERS["User-Agent"]
        )

        await page.goto(
            url,
            wait_until="networkidle",
            timeout=60000
        )

        html = await page.content()

        await browser.close()

        return html


async def get_page_content(url: str):
    try:
        html = await fetch_with_httpx(url)
        return html
    except:
        return await fetch_with_playwright(url)


async def get_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
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
        html = await get_page_content(url)

        soup = BeautifulSoup(html, "lxml")

        title = (
            soup.find("h1").get_text(strip=True)
            if soup.find("h1")
            else soup.title.get_text(strip=True)
            if soup.title
            else "Habari"
        )

        platform = detect_platform(soup, url)

        selectors = get_content_selectors(platform)

        content_el = find_content_element(soup, selectors)

        if not content_el:
            await original_message.reply_text(
                "⚠️ Imeshindwa kupata content."
            )
            return

        html_content = clean_html(
            str(content_el),
            base_url=url
        )

        if not html_content.strip():
            await original_message.reply_text(
                "⚠️ Imeshindwa kupata content."
            )
            return

        if len(html_content.encode("utf-8")) > 64000:
            html_content = (
                html_content[:60000]
                + "<p>... (imekatwa)</p>"
            )

        page_data = await telegraph.create_page(
            title=title,
            html_content=html_content,
        )

        telegraph_url = (
            f"https://telegra.ph/{page_data['path']}"
        )

        await original_message.reply_text(
            f"📄 <b>{title}</b>\n\n"
            f"🔗 <a href='{telegraph_url}'>"
            f"Soma hapa (Instant View)</a>",
            parse_mode="HTML",
            disable_web_page_preview=False,
        )

    except httpx.HTTPError as e:
        await original_message.reply_text(
            f"❌ Hitilafu ya mtandao: {e}"
        )

    except Exception as e:
        await original_message.reply_text(
            f"❌ Hitilafu: {e}"
        )
