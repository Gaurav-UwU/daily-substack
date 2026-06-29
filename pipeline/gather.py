"""Discovery: pull trending AI x Product signal from no-cookie sources.

Backbone (always works in CI): Hacker News (Algolia API) + curated RSS.
Best-effort (may be rate-limited on CI IPs, never fatal): Reddit, GitHub trending.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from . import config, sources

UA = sources.UA
TIMEOUT = 25


def _now() -> float:
    return time.time()


# ------------------------------------------------------------- Hacker News
def hacker_news() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cutoff = int(_now() - config.HN_LOOKBACK_HOURS * 3600)
    seen: set[str] = set()
    for q in config.HN_QUERIES:
        try:
            r = httpx.get(
                "https://hn.algolia.com/api/v1/search_by_date",
                params={
                    "query": q,
                    "tags": "story",
                    "numericFilters": f"created_at_i>{cutoff},points>{config.HN_MIN_POINTS}",
                    "hitsPerPage": 15,
                },
                headers={"User-Agent": UA},
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            for h in r.json().get("hits", []):
                url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
                if url in seen:
                    continue
                seen.add(url)
                items.append({
                    "title": h.get("title", ""),
                    "url": url,
                    "score": int(h.get("points") or 0),
                    "comments": int(h.get("num_comments") or 0),
                    "source": "hackernews",
                    "snippet": "",
                })
        except Exception as e:
            print(f"  [hn] query {q!r} failed: {e}")
    return items


# -------------------------------------------------------------------- RSS
def rss() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc).timestamp() - config.HN_LOOKBACK_HOURS * 3600
    for feed_url in config.RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed_url, agent=UA)
            for e in parsed.entries[:12]:
                ts = None
                if getattr(e, "published_parsed", None):
                    ts = time.mktime(e.published_parsed)
                if ts and ts < cutoff:
                    continue
                summary = getattr(e, "summary", "") or ""
                items.append({
                    "title": getattr(e, "title", ""),
                    "url": getattr(e, "link", ""),
                    "score": 0,
                    "comments": 0,
                    "source": f"rss:{parsed.feed.get('title', feed_url)[:30]}",
                    "snippet": _strip_html(summary)[:280],
                })
        except Exception as e:
            print(f"  [rss] {feed_url} failed: {e}")
    return items


def _strip_html(text: str) -> str:
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "lxml").get_text(" ").strip()


# ----------------------------------------------------------------- Reddit
def reddit() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for sub in config.SUBREDDITS:
        try:
            r = httpx.get(
                f"https://www.reddit.com/r/{sub}/top.json",
                params={"t": config.REDDIT_LOOKBACK, "limit": 8},
                headers={"User-Agent": f"{UA} daily-substack/1.0"},
                timeout=TIMEOUT,
            )
            if r.status_code != 200:
                continue
            for c in r.json().get("data", {}).get("children", []):
                d = c.get("data", {})
                if d.get("score", 0) < 30:
                    continue
                items.append({
                    "title": d.get("title", ""),
                    "url": "https://reddit.com" + d.get("permalink", ""),
                    "score": int(d.get("score") or 0),
                    "comments": int(d.get("num_comments") or 0),
                    "source": f"reddit:r/{sub}",
                    "snippet": (d.get("selftext") or "")[:280],
                })
        except Exception as e:
            print(f"  [reddit] r/{sub} failed: {e}")
    return items


# -------------------------------------------------------- GitHub trending
def github_trending() -> list[dict[str, Any]]:
    """Scrapling-powered: what AI tooling is hot today. Best-effort."""
    try:
        html = sources._scrapling_html("https://github.com/trending?since=daily") \
            or sources._httpx_html("https://github.com/trending?since=daily")
        if not html:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        items = []
        for row in soup.select("article.Box-row")[:15]:
            a = row.select_one("h2 a")
            if not a:
                continue
            repo = a.get_text(" ", strip=True).replace(" ", "")
            desc = row.select_one("p")
            blob = f"{repo} {desc.get_text(' ', strip=True) if desc else ''}".lower()
            if not any(k in blob for k in ("ai", "llm", "agent", "ml", "gpt", "rag", "model")):
                continue
            items.append({
                "title": f"Trending repo: {repo}",
                "url": f"https://github.com/{repo}",
                "score": 0,
                "comments": 0,
                "source": "github-trending",
                "snippet": desc.get_text(" ", strip=True) if desc else "",
            })
        return items
    except Exception as e:
        print(f"  [github] trending failed: {e}")
        return []


# ------------------------------------------------------------------ all
def gather_all() -> list[dict[str, Any]]:
    print("Gathering candidates...")
    buckets = {
        "hackernews": hacker_news,
        "rss": rss,
        "reddit": reddit,
        "github": github_trending,
    }
    candidates: list[dict[str, Any]] = []
    for name, fn in buckets.items():
        got = fn()
        print(f"  {name}: {len(got)} items")
        candidates.extend(got)

    # De-dupe by URL, keep the highest-scoring instance.
    by_url: dict[str, dict[str, Any]] = {}
    for c in candidates:
        url = c.get("url", "")
        if not url:
            continue
        if url not in by_url or c.get("score", 0) > by_url[url].get("score", 0):
            by_url[url] = c
    deduped = sorted(by_url.values(), key=lambda x: x.get("score", 0), reverse=True)
    print(f"  total unique: {len(deduped)}")
    return deduped
