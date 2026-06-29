"""Fetching + search layer.

Scrapling is the primary page fetcher (great at getting past anti-bot walls).
For discovery we use the same upstream channels that agent-reach orchestrates:
  - Exa  -> semantic web search
  - Jina reader (r.jina.ai) -> any URL to clean markdown
If the `agent-reach` CLI is installed and enabled, we prefer it; otherwise we
call those upstreams directly. Every path degrades gracefully and never raises
into the pipeline, so a single flaky source can't break the daily post.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

import httpx
from bs4 import BeautifulSoup

from . import config

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
TIMEOUT = 25


# ---------------------------------------------------------------- page text
def _scrapling_html(url: str) -> str | None:
    """Fetch raw HTML via Scrapling, tolerant of version differences."""
    try:
        from scrapling.fetchers import Fetcher  # type: ignore
    except Exception:
        try:
            from scrapling import Fetcher  # type: ignore
        except Exception:
            return None
    try:
        page = Fetcher.get(url, timeout=TIMEOUT, stealthy_headers=True)
    except TypeError:
        page = Fetcher.get(url)
    except Exception:
        return None
    for attr in ("html_content", "body", "text"):
        val = getattr(page, attr, None)
        if isinstance(val, (bytes, bytearray)):
            val = val.decode("utf-8", "ignore")
        if isinstance(val, str) and len(val) > 200:
            return val
    text = str(page)
    return text if len(text) > 200 else None


def _httpx_html(url: str) -> str | None:
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, follow_redirects=True)
        if r.status_code == 200 and len(r.text) > 200:
            return r.text
    except Exception:
        return None
    return None


def _jina_markdown(url: str) -> str | None:
    """agent-reach's web channel: r.jina.ai returns clean markdown for any URL."""
    try:
        clean = url.split("://", 1)[-1]
        r = httpx.get(
            f"https://r.jina.ai/https://{clean}",
            headers={"User-Agent": UA},
            timeout=TIMEOUT,
            follow_redirects=True,
        )
        if r.status_code == 200 and len(r.text) > 200:
            return r.text
    except Exception:
        return None
    return None


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "form", "noscript", "aside"]):
        tag.decompose()
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def fetch_text(url: str, max_chars: int = 6000) -> str:
    """Return readable article text for a URL. Best-effort, never raises."""
    html = _scrapling_html(url) or _httpx_html(url)
    text = ""
    if html:
        text = _html_to_text(html)
    if len(text) < 400:
        md = _jina_markdown(url)
        if md and len(md) > len(text):
            text = md
    return text[:max_chars].strip()


# ----------------------------------------------------------------- search
def web_search(query: str, num: int = 6) -> list[dict[str, Any]]:
    """Semantic web search. Prefers agent-reach CLI, falls back to Exa, then []."""
    if config.AGENT_REACH_ENABLED and shutil.which("agent-reach"):
        out = _agent_reach_search(query, num)
        if out:
            return out
    if config.EXA_API_KEY:
        return _exa_search(query, num)
    return []


def _agent_reach_search(query: str, num: int) -> list[dict[str, Any]]:
    try:
        proc = subprocess.run(
            ["agent-reach", "search", query, "--limit", str(num), "--json"],
            capture_output=True, text=True, timeout=60,
        )
        data = json.loads(proc.stdout or "[]")
        items = data.get("results", data) if isinstance(data, dict) else data
        return [
            {"title": i.get("title", ""), "url": i.get("url", ""),
             "snippet": i.get("text", i.get("snippet", "")), "source": "agent-reach"}
            for i in items if i.get("url")
        ][:num]
    except Exception:
        return []


def _exa_search(query: str, num: int) -> list[dict[str, Any]]:
    try:
        r = httpx.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": config.EXA_API_KEY, "Content-Type": "application/json"},
            json={"query": query, "numResults": num, "type": "auto",
                  "contents": {"text": {"maxCharacters": 800}}},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        out = []
        for i in r.json().get("results", []):
            out.append({
                "title": i.get("title", ""),
                "url": i.get("url", ""),
                "snippet": (i.get("text") or "")[:800],
                "source": "exa",
            })
        return out
    except Exception:
        return []
