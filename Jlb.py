from playwright.async_api import async_playwright
from telegram import Update
from telegram.ext import ContextTypes

NOISE_TEXTS = {
    "table of contents",
    "sign in with google to post a comment",
    "no comments yet. be the first!",
    "write a comment",
    "post comment",
}


def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


async def get_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message

    if not context.args:
        await original_message.reply_text("⚠️ Toa URL. Mfano: /get https://example.com")
        return

    url = context.args[0]

    if not is_url(url):
        await original_message.reply_text("⚠️ URL si sahihi. Lazima ianze na http:// au https://")
        return

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0"
            )

            await page.goto(url, wait_until="networkidle", timeout=60000)

            # Title
            h1 = await page.query_selector("h1")
            title = await h1.inner_text() if h1 else "Hakuna title"
            title = title.strip()

            # Paragraphs
            paragraphs = await page.query_selector_all("p")
            lines = []
            for p_el in paragraphs:
                text = (await p_el.inner_text()).strip()
                if text and text.lower() not in NOISE_TEXTS:
                    lines.append(text)

            await browser.close()

        content = "\n\n".join(lines)

        if not content:
            await original_message.reply_text("⚠️ Imeshindwa kupata content.")
            return

        full_text = f"<b>{title}</b>\n\n{content}"

        if len(full_text) > 4096:
            full_text = full_text[:4090] + "..."

        await original_message.reply_text(full_text, parse_mode="HTML")

    except Exception as e:
        await original_message.reply_text(f"❌ Hitilafu: {e}")
