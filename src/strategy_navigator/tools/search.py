"""Jina AI search + reader tool, Postgres-cached.

Replaces the ``jinaAiTool`` / ``httpRequestTool`` nodes. Every call is cached in
``sn_search_cache`` keyed by a hash of ``(op, query)`` for ``SN_JINA_CACHE_TTL_S``,
so a retried run — or two stages asking the same question in parallel — pays the
Jina cost once.

* :func:`jina_search` — ``s.jina.ai`` web search, returns ranked hits
* :func:`jina_read`   — ``r.jina.ai`` URL -> clean markdown
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from strategy_navigator.config import settings
from strategy_navigator.db.engine import session_scope
from strategy_navigator.db.repositories import SearchCacheRepository
from strategy_navigator.errors import SearchToolError
from strategy_navigator.logging import get_logger
from strategy_navigator.observability import span

log = get_logger(__name__)


@dataclass(slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    content: str | None = None


def _key(op: str, query: str) -> str:
    return hashlib.sha256(f"{op}::{query}".encode()).hexdigest()


async def _cached(op: str, query: str) -> dict | None:
    try:
        async with session_scope() as s:
            return await SearchCacheRepository(s).get(_key(op, query))
    except Exception as exc:  # cache is best-effort
        log.warning("search.cache_read_failed", error=str(exc))
        return None


async def _store(op: str, query: str, response: dict) -> None:
    try:
        async with session_scope() as s:
            await SearchCacheRepository(s).put(
                query_hash=_key(op, query),
                op=op,
                query=query,
                response=response,
                ttl_s=settings.jina_cache_ttl_s,
            )
    except Exception as exc:
        log.warning("search.cache_write_failed", error=str(exc))


def _headers() -> dict[str, str]:
    h = {"Accept": "application/json"}
    if settings.jina_api_key:
        h["Authorization"] = f"Bearer {settings.jina_api_key}"
    return h


@retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    wait=wait_exponential(multiplier=2, min=1, max=20),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def _get(url: str) -> dict:
    async with httpx.AsyncClient(timeout=settings.jina_timeout_s) as client:
        resp = await client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()


async def jina_search(query: str, *, top_k: int = 5) -> list[SearchHit]:
    if not query.strip():
        return []
    cached = await _cached("search", query)
    if cached is not None:
        log.debug("search.cache_hit", op="search", query=query)
        return [SearchHit(**h) for h in cached["hits"][:top_k]]

    with span("tool.jina.search", **{"jina.query": query}):
        try:
            data = await _get(f"{settings.jina_search_url}{httpx.URL(query)}")
        except httpx.HTTPError as exc:
            raise SearchToolError(f"Jina search failed for {query!r}: {exc}") from exc

    hits = [
        SearchHit(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("description", "") or item.get("snippet", ""),
            content=item.get("content"),
        )
        for item in (data.get("data") or [])
    ]
    await _store("search", query, {"hits": [h.__dict__ for h in hits]})
    log.info("search.done", op="search", query=query, hits=len(hits))
    return hits[:top_k]


async def jina_read(url: str) -> str:
    cached = await _cached("read", url)
    if cached is not None:
        log.debug("search.cache_hit", op="read", query=url)
        return cached["text"]

    with span("tool.jina.read", **{"jina.url": url}):
        try:
            data = await _get(f"{settings.jina_reader_url}{url}")
        except httpx.HTTPError as exc:
            raise SearchToolError(f"Jina read failed for {url!r}: {exc}") from exc

    text = (data.get("data") or {}).get("content", "") if isinstance(data.get("data"), dict) else ""
    await _store("read", url, {"text": text})
    log.info("search.done", op="read", query=url, chars=len(text))
    return text
