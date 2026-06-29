"""Write the article in the house voice, then hard-enforce the style rules."""
from __future__ import annotations

import re
from typing import Any

from . import config, llm

VOICE = (config.PROMPTS_DIR / "voice.md").read_text(encoding="utf-8")

BANNED = [
    "delve", "tapestry", "in the realm of", "navigate the landscape",
    "game-changer", "game changer", "it's important to note", "in conclusion",
    "ever-evolving", "ever evolving", "the world of", "buckle up",
]


def sanitize(text: str) -> str:
    """Guarantee the hard rules regardless of what the model returned."""
    # Kill em/en dashes (brand rule). Replace with a comma+space, then tidy.
    text = text.replace(" — ", ", ").replace(" – ", ", ")
    text = text.replace("—", ", ").replace("–", ", ")
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r",\s*\.", ".", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def write_article(topic: dict[str, Any], context: str) -> dict[str, str]:
    user = f"""Write today's essay.

WORKING TITLE: {topic.get('working_title','')}
ANGLE / THESIS: {topic.get('angle','')}
WHY NOW: {topic.get('why_now','')}

RESEARCH MATERIAL (your only source of specific facts, names, and numbers):
---
{context}
---

Write the full essay following the voice guide exactly. Remember: no em dashes,
no clichés, no invented facts. Ground every specific in the research above.

Return ONLY JSON:
{{
  "title": "<final title, specific and provocative>",
  "subtitle": "<one-line dek>",
  "body_markdown": "<the full essay in markdown, {config.WORD_MIN}-{config.WORD_MAX} words>",
  "tags": ["<3-5 lowercase tags>"]
}}"""

    result = llm.chat_json(
        [{"role": "system", "content": VOICE}, {"role": "user", "content": user}],
        model=config.MODEL,
        temperature=0.7,
        max_tokens=3500,
    )

    title = sanitize(str(result.get("title", topic.get("working_title", "Untitled"))))
    subtitle = sanitize(str(result.get("subtitle", "")))
    body = sanitize(str(result.get("body_markdown", "")))
    tags = result.get("tags", []) or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]

    return {
        "title": title,
        "subtitle": subtitle,
        "body_markdown": body,
        "tags": [str(t).lower().strip() for t in tags][:5],
    }


def style_violations(article: dict[str, str]) -> list[str]:
    """Programmatic checks the quality gate can rely on."""
    problems = []
    blob = f"{article['title']}\n{article['subtitle']}\n{article['body_markdown']}"
    if "—" in blob or "–" in blob:
        problems.append("contains an em/en dash")
    low = blob.lower()
    for phrase in BANNED:
        if phrase in low:
            problems.append(f"banned phrase: {phrase!r}")
    words = len(article["body_markdown"].split())
    if words < config.WORD_MIN:
        problems.append(f"too short ({words} words, min {config.WORD_MIN})")
    if not article["title"].strip():
        problems.append("missing title")
    return problems
