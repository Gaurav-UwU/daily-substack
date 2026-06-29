"""Pick the single best topic for today from the gathered candidates."""
from __future__ import annotations

from typing import Any

from . import config, llm, state

SYSTEM = (
    "You are the editor of a daily Substack about the intersection of AI and "
    "product/strategy. You choose what is worth writing about today. You have "
    "ruthless taste: you reject generic, evergreen, or low-signal items and pick "
    "the one story with a strong, timely, non-obvious product or strategy angle."
)


def pick_topic(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    history = state.load_history()
    recent = state.recent_titles(history)

    # Trim the candidate list to keep the prompt cheap.
    short = candidates[:40]
    lines = []
    for i, c in enumerate(short):
        meta = f"[{c.get('source')}, score {c.get('score', 0)}]"
        snip = (c.get("snippet") or "").replace("\n", " ")[:160]
        lines.append(f"{i}. {c.get('title','')} {meta}\n   {c.get('url','')}\n   {snip}")
    candidate_block = "\n".join(lines) if lines else "(no candidates found today)"

    recent_block = "\n".join(f"- {t}" for t in recent[-40:]) or "(none yet)"

    user = f"""Today's candidate stories (AI x product space):

{candidate_block}

Topics already covered recently (DO NOT repeat or pick anything substantially similar):
{recent_block}

Pick the ONE best topic to write about today. Optimise for: timeliness, a strong
non-obvious product/strategy angle, and reader value for PMs, founders, and builders.
Prefer something with a concrete artifact (a launch, a number, a decision, a shift)
over vague trend pieces.

Return ONLY JSON with this shape:
{{
  "chosen_index": <int, the candidate number, or -1 if none are good>,
  "working_title": "<specific, provocative title>",
  "angle": "<2-3 sentences: the thesis and why it is non-obvious>",
  "why_now": "<1 sentence on timeliness>",
  "source_urls": ["<the 1-3 most relevant urls to research>"],
  "search_queries": ["<1-2 web search queries to find more context>"]
}}"""

    result = llm.chat_json(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        model=config.MODEL_REASON,
        temperature=0.5,
        max_tokens=900,
    )

    idx = result.get("chosen_index", -1)
    chosen = short[idx] if isinstance(idx, int) and 0 <= idx < len(short) else None

    urls = result.get("source_urls") or ([chosen["url"]] if chosen else [])
    return {
        "working_title": result.get("working_title", chosen["title"] if chosen else "Untitled"),
        "angle": result.get("angle", ""),
        "why_now": result.get("why_now", ""),
        "source_urls": [u for u in urls if u][:3],
        "search_queries": (result.get("search_queries") or [])[:2],
        "seed": chosen,
    }
