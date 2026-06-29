"""Self-review gate. Decides whether today's draft is good enough to auto-publish."""
from __future__ import annotations

from typing import Any

from . import config, llm, write

SYSTEM = (
    "You are a brutally honest editor protecting the reputation of a Substack "
    "about AI and product. You would rather hold a mediocre post as a draft than "
    "publish something generic, wrong, or off-voice. Score honestly; most days a "
    "70 is fair. Reserve 85+ for genuinely sharp, specific, non-obvious writing."
)


def evaluate(article: dict[str, str], topic: dict[str, Any]) -> dict[str, Any]:
    # 1. Hard programmatic checks first. Any violation = automatic hold.
    violations = write.style_violations(article)

    # 2. LLM rubric score.
    user = f"""Evaluate this draft for publication.

TITLE: {article['title']}
SUBTITLE: {article['subtitle']}
ANGLE IT WAS MEANT TO HIT: {topic.get('angle','')}

BODY:
{article['body_markdown']}

Score each criterion 0-100, then give an overall weighted score.
Criteria:
- originality: is the take non-obvious, or is it a generic news recap?
- specificity: concrete examples, names, numbers vs vague hand-waving?
- voice: confident, sharp, first-principles, opinionated?
- structure: strong hook, clear through-line, memorable ending?
- credibility: any claim that looks fabricated, overreaching, or unsupported?
- reader_value: would a PM/founder be glad they read it?

Return ONLY JSON:
{{
  "scores": {{"originality": <int>, "specificity": <int>, "voice": <int>,
              "structure": <int>, "credibility": <int>, "reader_value": <int>}},
  "overall": <int 0-100>,
  "hard_fail": <true if any claim looks fabricated or it reads as spam/off-topic>,
  "reasons": "<2-3 sentences of honest critique>",
  "fixes": ["<the 1-3 edits that would most improve it>"]
}}"""

    result = llm.chat_json(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        model=config.MODEL_REASON,
        temperature=0.3,
        max_tokens=900,
    )

    overall = int(result.get("overall", 0) or 0)
    hard_fail = bool(result.get("hard_fail", False)) or bool(violations)
    passed = (overall >= config.QUALITY_THRESHOLD) and not hard_fail

    return {
        "overall": overall,
        "passed": passed,
        "hard_fail": hard_fail,
        "violations": violations,
        "reasons": result.get("reasons", ""),
        "fixes": result.get("fixes", []),
        "scores": result.get("scores", {}),
        "threshold": config.QUALITY_THRESHOLD,
    }
