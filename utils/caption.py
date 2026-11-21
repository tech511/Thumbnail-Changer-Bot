"""Caption style helpers."""

import html

MAX_CAPTION = 1024

# style key -> Telegram HTML tag (None = keep caption exactly as sent)
CAPTION_STYLES = {
    "none": None,
    "bold": "b",
    "italic": "i",
    "mono": "code",
    "underline": "u",
    "strike": "s",
    "spoiler": "tg-spoiler",
    "quote": "blockquote",
}


def style_caption(text, style):
    """Return an HTML-styled caption, or None when no styling applies."""
    tag = CAPTION_STYLES.get(style)

    if not text or not tag:
        return None

    safe = html.escape(text[:MAX_CAPTION])
    return f"<{tag}>{safe}</{tag}>"
