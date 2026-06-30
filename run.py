#!/usr/bin/env python3
"""Daily AI x Product Substack agent. Orchestrates the full pipeline.

    gather -> rank -> research -> write -> quality gate -> publish -> notify

Run locally:   python run.py
Dry run:       DRY_RUN=true python run.py    (writes a draft file, never touches Substack)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from pipeline import config, gather, rank, research, write, quality_gate, publish, notify, state


def _decide_publish(gate: dict) -> bool:
    if config.PUBLISH_MODE == "auto":
        return True
    if config.PUBLISH_MODE == "draft":
        return False
    return bool(gate.get("passed"))  # "gate" mode


def _save_archive(date: str, article: dict, gate: dict, topic: dict) -> None:
    fm = [
        "---",
        f"title: {json.dumps(article['title'])}",
        f"subtitle: {json.dumps(article.get('subtitle',''))}",
        f"date: {date}",
        f"quality_score: {gate.get('overall')}",
        f"passed_gate: {gate.get('passed')}",
        f"tags: {json.dumps(article.get('tags', []))}",
        f"sources: {json.dumps(topic.get('source_urls', []))}",
        "---",
        "",
        article["body_markdown"],
    ]
    (config.POSTS_DIR / f"{date}.md").write_text("\n".join(fm), encoding="utf-8")


def main() -> int:
    # Make Windows-local dry runs safe when titles contain unicode.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print(f"=== Daily Substack agent :: {date} (UTC) ===")
    print(f"mode={config.PUBLISH_MODE}  model={config.MODEL}  dry_run={config.DRY_RUN}")

    problems = config.missing_required()
    if any("NVIDIA_API_KEY" in p for p in problems):
        print("FATAL: " + "; ".join(problems))
        return 1
    if problems:
        print("WARNING: " + "; ".join(problems))

    # 1. Gather
    candidates = gather.gather_all()
    if not candidates:
        print("No candidates found today. Nothing to write.")
        notify.emit({"date": date, "title": "(no candidates today)",
                     "gate": {}, "publish": {}})
        return 0

    # Hard de-dup: drop anything whose source URL we have already written about.
    history = state.load_history()
    seen_urls = {u for h in history for u in h.get("urls", [])}
    fresh = [c for c in candidates if c.get("url") not in seen_urls]
    if fresh:
        candidates = fresh
        print(f"  after history de-dup: {len(candidates)} candidates")

    # 2. Rank / pick
    topic = rank.pick_topic(candidates)
    print(f"\nChosen topic: {topic['working_title']}")
    print(f"Angle: {topic['angle']}")
    if not topic.get("source_urls"):
        print("Model found nothing worth writing today. Skipping.")
        notify.emit({"date": date, "title": "(no strong topic today)",
                     "gate": {}, "publish": {}})
        return 0

    if state.is_dup(topic["working_title"], history):
        print("NOTE: topic looks similar to a recent post; continuing anyway.")

    # 3. Research
    print("\nResearching sources...")
    context = research.build_context(topic)
    print(f"  context: {len(context)} chars")

    # 4. Write
    print("\nWriting draft...")
    article = write.write_article(topic, context)
    article = write.proofread(article)
    words = len(article["body_markdown"].split())
    print(f"  '{article['title']}' ({words} words)")

    # 5. Quality gate
    print("\nQuality gate...")
    gate = quality_gate.evaluate(article, topic, context)
    print(f"  score={gate['overall']}/{gate['threshold']}  passed={gate['passed']}")
    if gate.get("violations"):
        print(f"  violations: {gate['violations']}")

    # 6. Publish decision + push
    should_publish = _decide_publish(gate)
    print(f"\nPublish decision: {should_publish} (mode={config.PUBLISH_MODE})")
    pub = publish.push(article, should_publish=should_publish)
    if pub.get("error"):
        print(f"  Substack error: {pub['error']}")
    elif pub.get("published"):
        print(f"  PUBLISHED LIVE: {pub.get('draft_url')}")
    elif pub.get("dry_run"):
        print("  DRY RUN: skipped Substack.")
    else:
        print(f"  Saved as DRAFT for review: {pub.get('draft_url')}")

    # 7. Archive + remember + notify
    _save_archive(date, article, gate, topic)
    state.append_history(
        title=article["title"],
        topic=topic["working_title"],
        urls=topic.get("source_urls", []),
        published=bool(pub.get("published")),
    )
    notify.emit({
        "date": date,
        "title": article["title"],
        "subtitle": article.get("subtitle", ""),
        "words": words,
        "gate": gate,
        "publish": pub,
        "source_urls": topic.get("source_urls", []),
    })
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
