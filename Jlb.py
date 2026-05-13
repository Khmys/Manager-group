import re
from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ContextTypes
from telegraph.aio import Telegraph
from bs4 import BeautifulSoup, NavigableString, Tag, Comment
from urllib.parse import urljoin

telegraph = Telegraph(access_token="522e083178bb4d7511cc1784c3f849b9e71164cdac06d08812181c1945dc")


NOISE_TEXTS = {
    "table of contents",
    "sign in with google to post a comment",
    "no comments yet. be the first!",
    "write a comment",
    "post comment",
}

ALLOWED_TAGS = {
    "p", "a", "b", "i", "u", "s",
    "h3", "h4", "br", "ul", "ol", "li",
    "blockquote", "pre", "code", "img"
}

UNWANTED_SELECTORS = [
    ".sharedaddy",
    ".jp-relatedposts",
    ".sd-sharing",
    "[class*='share']",
    ".wp-block-buttons",
    ".wp-block-button",
]

BLOCK_TAGS = {
    "p", "div", "section", "article", "aside",
    "header", "footer", "main", "nav",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "blockquote", "pre",
    "table", "thead", "tbody", "tr", "td", "th",
    "figure", "figcaption",
}

INLINE_TAGS = {
    "a", "b", "i", "u", "s", "strong", "em",
    "span", "code", "abbr", "mark",
}

SKIP_TAGS = {
    "script", "style", "nav", "footer", "aside",
    "form", "button", "input", "svg", "meta", "link",
    "head", "noscript", "iframe", "header",
    "picture", "source", "video", "audio",
    "select", "textarea", "label", "fieldset",
}

TAG_MAP = {
    "strong": "b",
    "em": "i",
    "h1": "h3",
    "h2": "h3",
    "h5": "h4",
    "h6": "h4",
}


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def is_noise_text(text: str) -> bool:
    """Angalia kama text ni noise/boilerplate."""
    cleaned = text.strip().lower()
    if not cleaned:
        return True
    if cleaned in NOISE_TEXTS:
        return True
    # Fupi sana na haina maana
    if len(cleaned) < 3:
        return True
    return False


def get_node_text(node) -> str:
    """Pata text yote kutoka node bila tags."""
    if isinstance(node, NavigableString):
        return str(node)
    return node.get_text(separator=" ", strip=True)


def process_node(node, base_url: str, soup: BeautifulSoup) -> list:
    """
    Traverse DOM node kwa node, isafishe na irudishe list ya
    nodes zilizosafishwa tayari kwa Telegraph.

    Strategy:
    - NavigableString  → rudisha text node moja kwa moja (baada ya kusafisha)
    - Comment          → skip kabisa
    - SKIP_TAGS        → skip tag na watoto wake wote
    - img              → normalize src, rudisha tag
    - a                → normalize href, process watoto wake recursively
    - INLINE_TAGS      → map jina, process watoto recursively
    - BLOCK_TAGS       → wrap content ya watoto katika tag inayofaa
    - Kingine chochote → unwrap: process watoto tu bila tag
    """

    # 1. Comment nodes — ziache kabisa
    if isinstance(node, Comment):
        return []

    # 2. Text nodes (NavigableString)
    if isinstance(node, NavigableString):
        text = str(node)
        # Safisha whitespace nyingi lakini hifadhi newlines muhimu
        text = re.sub(r'[^\S\n]+', ' ', text)
        if is_noise_text(text):
            return []
        return [NavigableString(text)]

    # Kutoka hapa node ni Tag
    if not isinstance(node, Tag):
        return []

    tag_name = node.name.lower() if node.name else ""

    # 3. Tags za hatari — skip kabisa pamoja na watoto
    if tag_name in SKIP_TAGS:
        return []

    # 4. Angalia kama node nzima ni noise kwa text yake
    node_text = get_node_text(node).strip().lower()
    if node_text in NOISE_TEXTS:
        return []

    # 5. Map tag kwenda Telegraph-compatible tag
    mapped_tag = TAG_MAP.get(tag_name, tag_name)

    # 6. Img — special handling
    if tag_name == "img":
        src = node.get("src", "").strip()
        if not src:
            return []
        full_src = urljoin(base_url, src)
        new_img = soup.new_tag("img", src=full_src)
        # Alt text kama ipo
        alt = node.get("alt", "").strip()
        if alt:
            new_img["alt"] = alt
        return [new_img]

    # 7. Process watoto recursively
    processed_children = []
    for child in node.children:
        processed_children.extend(process_node(child, base_url, soup))

    # Kama hakuna children zilizobaki baada ya kusafisha, rudisha empty
    if not processed_children:
        return []

    # 8. Anchor tags — normalize href, hifadhi tag
    if tag_name == "a":
        href = node.get("href", "").strip()
        if not href:
            # Link bila href — unwrap tu, rudisha content
            return processed_children
        full_href = urljoin(base_url, href)
        # Skip anchor za ndani ya ukurasa (jump links)
        if full_href.startswith("#"):
            return processed_children
        new_a = soup.new_tag("a", href=full_href)
        for child in processed_children:
            new_a.append(child.__copy__() if hasattr(child, '__copy__') else child)
        return [new_a]

    # 9. Inline tags — wrap watoto katika tag iliyomapwa
    if tag_name in INLINE_TAGS:
        if mapped_tag not in ALLOWED_TAGS:
            # Unwrap — rudisha content bila tag
            return processed_children
        new_tag = soup.new_tag(mapped_tag)
        for child in processed_children:
            new_tag.append(child)
        return [new_tag]

    # 10. Block tags — jenga tag mpya na watoto waliiosafishwa
    if tag_name in BLOCK_TAGS:
        # Determine final tag kwa Telegraph
        if mapped_tag in ALLOWED_TAGS:
            final_tag = mapped_tag
        elif tag_name in {"ul", "ol", "li"}:
            final_tag = tag_name  # hizi zinaruhusiwa moja kwa moja
        elif tag_name in {"table", "thead", "tbody", "tr", "td", "th"}:
            # Telegraph haipendi table — convert kuwa paragraphs
            result = []
            for child in processed_children:
                if isinstance(child, NavigableString):
                    text = str(child).strip()
                    if text:
                        p = soup.new_tag("p")
                        p.append(NavigableString(text))
                        result.append(p)
                else:
                    result.append(child)
            return result
        elif tag_name in {"figure", "figcaption"}:
            final_tag = "p"
        else:
            # Unwrap — content peke yake
            return processed_children

        new_tag = soup.new_tag(final_tag)
        for child in processed_children:
            new_tag.append(child)

        # Safisha: kama p/h3/h4 ina text tupu ya noise — skip
        inner_text = new_tag.get_text(strip=True).lower()
        if inner_text in NOISE_TEXTS or not inner_text:
            return []

        return [new_tag]

    # 11. Chochote kingine — unwrap, rudisha watoto tu
    return processed_children


def clean_html(html: str, base_url: str) -> str:
    html = re.sub(r'<\?xml[^>]*\?>', '', html)
    html = re.sub(r'<xml[^>]*>.*?</xml>', '', html, flags=re.DOTALL)

    soup = BeautifulSoup(html, "lxml")

    # Futa sections zisizohitajika kwanza
    for selector in UNWANTED_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    # Pata body au soup nzima
    body = soup.find("body") or soup

    # Tumia process_node() kwenye kila child wa body
    result_nodes = []
    for child in list(body.children):
        result_nodes.extend(process_node(child, base_url, soup))

    # Jenga HTML mpya kutoka nodes zilizosafishwa
    result_soup = BeautifulSoup("", "lxml")
    wrapper = result_soup.new_tag("div")
    for node in result_nodes:
        wrapper.append(node)

    return wrapper.decode_contents()


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

            await page.goto(url, wait_until="networkidle", timeout=60000)

            # Title
            h1 = await page.query_selector("h1")
            title = (await h1.inner_text()).strip() if h1 else "Habari"

            # Gundua platform
            is_firqatunnajia = "firqatunnajia.com" in url
            is_wordpress = await page.query_selector(
                "meta[name='generator'][content*='WordPress'], "
                "meta[name='generator'][content*='Elementor'], "
                "link[rel='https://api.w.org/']"
            )
            is_blogger = await page.query_selector(
                "meta[name='generator'][content*='Blogger']"
            )
            is_drupal = await page.query_selector(
                "meta[name='generator'][content*='Drupal'], "
                "meta[name='Generator'][content*='Drupal']"
            )
            is_medium = "medium.com" in url
            is_substack = "substack.com" in url

            # Selectors kulingana na platform
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
                    ".field-name-body .field-item",
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

            # Pata content element
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
                await original_message.reply_text("⚠️ Imeshindwa kupata content.")
                return

            body_html = await content_el.inner_html()
            await browser.close()

        html_content = clean_html(body_html, base_url=url)

        if not html_content.strip():
            await original_message.reply_text("⚠️ Imeshindwa kupata content.")
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
        await original_message.reply_text(f"❌ Hitilafu: {e}")
