"""Deep-fetch the chosen topic's sources so the writer has real material."""
from __future__ import annotations

from typing import Any

from . import sources


def build_context(topic: dict[str, Any]) -> str:
    chunks: list[str] = []

    # 1. Full text of the chosen source URLs (Scrapling -> httpx -> jina).
    for url in topic.get("source_urls", []):
        text = sources.fetch_text(url, max_chars=5000)
        if text:
            chunks.append(f"### SOURCE: {url}\n{text}")
        else:
            print(f"  [research] no text from {url}")

    # 2. A couple of extra sources via the search channel (agent-reach/Exa).
    for q in topic.get("search_queries", []):
        for hit in sources.web_search(q, num=3):
            snip = hit.get("snippet", "")
            if snip:
                chunks.append(f"### SEARCH HIT: {hit.get('title','')} ({hit.get('url','')})\n{snip}")

    context = "\n\n".join(chunks)
    if len(context) > 14000:
        context = context[:14000]
    if not context:
        context = "(No external text could be fetched. Write from the title and angle only, and stay qualitative. Do not invent specifics.)"
    return context
