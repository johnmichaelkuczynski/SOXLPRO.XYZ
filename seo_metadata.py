import json
import logging
from pathlib import Path


CANONICAL_URL = "https://soxlpro.xyz/"
PUBLISHER_URL = "https://zhisystems.ai/"
STRUCTURED_DATA_MARKER = "<!-- SOXL structured data -->"


def structured_data_script() -> str:
    publisher_id = f"{PUBLISHER_URL}#organization"
    structured_data = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": f"{CANONICAL_URL}#website",
                "url": CANONICAL_URL,
                "name": "SOXL Analysis",
                "description": (
                    "Quantitative analysis and probability tools for the "
                    "SOXL 3× semiconductor ETF."
                ),
                "publisher": {"@id": publisher_id},
                "inLanguage": "en-US",
            },
            {
                "@type": "Organization",
                "@id": publisher_id,
                "name": "ZHI Systems",
                "url": PUBLISHER_URL,
                "logo": "https://zhisystems.ai/zhi-systems-logo.png",
                "sameAs": [PUBLISHER_URL],
            },
            {
                "@type": "WebApplication",
                "@id": f"{CANONICAL_URL}#application",
                "name": "SOXL Analysis",
                "url": CANONICAL_URL,
                "applicationCategory": "FinanceApplication",
                "applicationSubCategory": "Investment research and market analysis",
                "operatingSystem": "Web browser",
                "publisher": {"@id": publisher_id},
            },
        ],
    }
    return (
        f"{STRUCTURED_DATA_MARKER}<script type=\"application/ld+json\">"
        f"{json.dumps(structured_data, ensure_ascii=False, separators=(',', ':'))}"
        "</script>"
    )


def inject_structured_data() -> bool:
    """Inject JSON-LD into the Streamlit document shell idempotently."""
    try:
        import streamlit

        index_path = Path(streamlit.__file__).parent / "static" / "index.html"
        html = index_path.read_text()
        if STRUCTURED_DATA_MARKER in html:
            return True
        if "<head>" not in html:
            logging.warning(
                "Structured data: could not find <head> tag in %s — patch skipped.",
                index_path,
            )
            return False
        index_path.write_text(
            html.replace("<head>", f"<head>{structured_data_script()}", 1)
        )
        logging.info("Structured data injected into %s", index_path)
        return True
    except Exception as exc:
        logging.warning("Structured data injection failed: %s", exc)
        return False