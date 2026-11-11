"""String encoding for the documented Power Query CSV handoff."""


def csv_safe(value):
    if value is None:
        return ""
    text = str(value)
    if not text:
        return text
    stripped = text.lstrip(" \u3000")
    first = stripped[:1]
    if (text.startswith("TXT_") or first in "\t\r\n=+-@＝＋－＠"):
        return "TXT_" + text
    return text
