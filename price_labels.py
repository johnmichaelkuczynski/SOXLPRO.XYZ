"""Provider-neutral public labels; source validation and feeds stay unchanged."""
import re


def public_price_text(value):
    text = re.sub(r"/auth/schwab/connect", "the price-feed connection page",
                  str(value or ""), flags=re.IGNORECASE)
    return re.sub(r"\b(?:schwab|yahoo(?: finance)?)\b", "price feed",
                  text, flags=re.IGNORECASE)
