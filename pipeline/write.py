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

FORMATTING IS REQUIRED: the body_markdown must have 3 to 5 `## ` subheadings,
a blank line between every paragraph, and paragraphs of only 2 to 4 sentences.
Do not return one unbroken block of text. In JSON, write real newlines as \\n.

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


def normalize_markdown(body: str) -> str:
    """Guarantee Substack-friendly spacing regardless of what the model returned."""
    text = (body or "").replace("\r\n", "\n")
    # Blank line before and after ## / ### headings.
    text = re.sub(r"(?<!\n)\n(#{1,3} )", r"\n\n\1", text)
    text = re.sub(r"(^|\n)(#{1,3} [^\n]+)\n(?!\n)", r"\1\2\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    # Last resort: a single unbroken block becomes readable paragraphs.
    if "\n\n" not in text and len(text) > 500:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        text = "\n\n".join(
            " ".join(sentences[i : i + 3]) for i in range(0, len(sentences), 3)
        )
    return text


def proofread(article: dict[str, str]) -> dict[str, str]:
    """Copy-edit + structure pass: fix typos AND ensure Substack-ready formatting.

    Fixes spelling/grammar and guarantees 3-5 ## sections with blank-line-separated
    short paragraphs. Guarded: on any failure it still normalizes spacing.
    """
    user = f"""You are an editor preparing this essay for Substack. Do two things
and nothing else:
1. Fix spelling, grammar, and typos.
2. Ensure clean structure: 3 to 5 `## ` subheadings, a blank line between every
   paragraph, and paragraphs of 2 to 4 sentences. If the text is one big block,
   break it into logical paragraphs and add subheadings.
Do NOT change the meaning, argument, voice, facts, or wording beyond this. No em dashes.

TITLE: {article['title']}
SUBTITLE: {article['subtitle']}
BODY:
{article['body_markdown']}

Return ONLY JSON: {{"title": "...", "subtitle": "...", "body_markdown": "..."}}
In the JSON, write real newlines as \\n."""
    try:
        result = llm.chat_json(
            [{"role": "system",
              "content": "You copy-edit and format essays for Substack without rewriting them."},
             {"role": "user", "content": user}],
            model=config.MODEL,
            temperature=0.2,
            max_tokens=3500,
        )
        body = sanitize(str(result.get("body_markdown") or article["body_markdown"]))
        title = sanitize(str(result.get("title") or article["title"]))
        subtitle = sanitize(str(result.get("subtitle") or article["subtitle"]))
        # If the editor truncated the body, keep the original text.
        if len(body.split()) < 0.8 * len(article["body_markdown"].split()):
            body = sanitize(article["body_markdown"])
            title = sanitize(article["title"])
            subtitle = sanitize(article["subtitle"])
        return {"title": title, "subtitle": subtitle,
                "body_markdown": normalize_markdown(body), "tags": article.get("tags", [])}
    except Exception as e:
        print(f"  [polish] skipped ({type(e).__name__})")
        return {**article, "body_markdown": normalize_markdown(article["body_markdown"])}


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
