"""Project document ingestion.

The n8n workflows pull files from S3 and run ``extractFromFile`` (PDF/TXT) before
summarising. Here we fetch by URL or S3 key and return plain text. PDF parsing is
delegated to Jina's reader (``r.jina.ai``) to avoid a native pdf dependency in
the image; override :func:`extract_document_text` if you'd rather use ``pypdf``.
"""

from __future__ import annotations

import httpx

from strategy_navigator.config import settings
from strategy_navigator.logging import get_logger
from strategy_navigator.tools.search import jina_read

log = get_logger(__name__)


def _s3_url(key: str) -> str:
    return f"https://{settings.s3_bucket}.s3.{settings.s3_region}.amazonaws.com/{key.lstrip('/')}"


async def extract_document_text(ref: str, *, max_chars: int = 60_000) -> str:
    """``ref`` is an https URL or a bare S3 key. Returns extracted text (truncated)."""
    url = ref if ref.startswith("http") else _s3_url(ref)
    lower = url.split("?", 1)[0].lower()

    if lower.endswith((".pdf", ".docx", ".pptx")):
        text = await jina_read(url)
    elif lower.endswith((".txt", ".md", ".csv", ".json")):
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text
    else:
        text = await jina_read(url)

    if len(text) > max_chars:
        log.info("document.truncated", ref=ref, original=len(text), kept=max_chars)
        text = text[:max_chars]
    return text
