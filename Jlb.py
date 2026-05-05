from playwright.async_api import async_playwright

    "write a comment",
    "post comment",
}


telegraph = Telegraph(access_token="522e083178bb4d7511cc1784c3f849b9e71164cdac06d08812181c1945dc")


# Tags zinazokubalika Telegraph
ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "s", "a",
    "p", "br", "h3", "h4", "ul", "ol", "li",
    "blockquote", "pre", "code", "img"
}




def is_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")




def clean_html(html: str, base_url: str) -> str:
    """Safisha HTML na kubakiza formatting + picha."""
    soup = BeautifulSoup(html, "html.parser")


    def process_node(tag):
        from bs4 import NavigableString, Tag


        if isinstance(tag, NavigableString):
            return str(tag)


        if not isinstance(tag, Tag):
            return ""


        name = tag.name.lower() if tag.name else ""


        # Ondoa tags zisizohitajika
        if name in {
            "script", "style", "nav", "footer",
            "aside", "form", "button", "input"
        }:
            return ""


        # Picha
        if name == "img":
            src = tag.get("src", "").strip()


            if not src:
                return ""


            # Rekebisha relative URLs
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


        # Process watoto
        inner = "".join(process_node(child) for child in tag.children)


        if not inner.strip():
            return ""


        # Mapping
        tag_map = {
            "strong": "b",
            "em": "i",


