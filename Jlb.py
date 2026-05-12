import re
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
]



def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def clean_html(html: str, base_url: str) -> str:
    html = re.sub(r'<\?xml[^>]*\?>', '', html)
    html = re.sub(r'<xml[^>]*>.*?</xml>', '', html, flags=re.DOTALL)

    soup = BeautifulSoup(html, "lxml")

    # Futa sections zisizohitajika
    for selector in UNWANTED_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    # Futa tags hatari
    for tag in soup.find_all(True):
        if tag.name.lower() in {
            "script", "style", "nav", "footer", "aside",
            "form", "button", "input", "svg", "meta", "link",
            "head", "noscript", "iframe", "header", "figure",
            "picture", "source", "video", "audio",
        }:
            tag.decompose()

    # Rekebisha URLs
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src:
            img["src"] = urljoin(base_url, src)

    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href:
            a["href"] = urljoin(base_url, href)

    # Badilisha tags kwanza
    tag_map = {"strong": "b", "em": "i", "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4"}
    for tag in soup.find_all(list(tag_map.keys())):
        tag.name = tag_map.get(tag.name, tag.name)

    # Futa tags zisizoruhusiwa, hifadhi content
    for tag in soup.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()

    
    result = body.decode_contents()
    result = re.sub(r'&lt;', '<', result)
    result = re.sub(r'&gt;', '>', result)
    result = re.sub(r'&amp;', '&', result)
    
    body = soup.find("body") or soup
    return body.decode_contents()
    


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
        await original_message.reply_text(f"❌ Hitilafu: {e}")RLs
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if src:
            img["src"] = urljoin(base_url, src)

    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href:
            a["href"] = urljoin(base_url, href)

    # Badilisha tags kwanza
    tag_map = {"strong": "b", "em": "i", "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4"}
    for tag in soup.find_all(list(tag_map.keys())):
        tag.name = tag_map.get(tag.name, tag.name)

    # Futa tags zisizoruhusiwa, hifadhi content
    for tag in soup.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()

    
    result = body.decode_contents()
    result = re.sub(r'&lt;', '<', result)
    result = re.sub(r'&gt;', '>', result)
    result = re.sub(r'&amp;', '&', result)
    
    body = soup.find("body") or soup
    return body.decode_contents()
    


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
        await original_message.reply_text(f"❌ Hitilafu: {e}")l("img"):
        src = img.get("src", "")
        if src:
            img["src"] = urljoin(base_url, src)

    for a in soup.find_all("a"):
        href = a.get("href", "")
        if href:
            a["href"] = urljoin(base_url, href)

    # Badilisha tags kwanza
    tag_map = {"strong": "b", "em": "i", "h1": "h3", "h2": "h3", "h5": "h4", "h6": "h4"}
    for tag in soup.find_all(list(tag_map.keys())):
        tag.name = tag_map.get(tag.name, tag.name)

    # Futa tags zisizoruhusiwa, hifadhi content
    for tag in soup.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()

    body = soup.find("body") or soup
    return body.decode_contents()


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
