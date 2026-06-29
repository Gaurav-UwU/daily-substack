"""Run summary -> console, GitHub Actions step summary, and optional webhook."""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from . import config


def summarize(report: dict[str, Any]) -> str:
    gate = report.get("gate", {})
    pub = report.get("publish", {})
    lines = [
        f"# Daily Substack run: {report.get('date','')}",
        "",
        f"**Title:** {report.get('title','(none)')}",
        f"**Subtitle:** {report.get('subtitle','')}",
        f"**Words:** {report.get('words', 0)}",
        "",
        f"**Quality score:** {gate.get('overall','?')} / {gate.get('threshold','?')}  "
        f"(passed: {gate.get('passed')})",
        f"**Editor notes:** {gate.get('reasons','')}",
    ]
    if gate.get("violations"):
        lines.append(f"**Style violations:** {', '.join(gate['violations'])}")
    if gate.get("fixes"):
        lines.append("**Suggested fixes:** " + "; ".join(gate["fixes"]))
    lines += [
        "",
        f"**Publish mode:** {config.PUBLISH_MODE}",
        f"**Published live:** {pub.get('published')}",
    ]
    if pub.get("draft_url"):
        lines.append(f"**Draft / edit link:** {pub['draft_url']}")
    if pub.get("error"):
        lines.append(f"**Substack error:** {pub['error']}")
    if report.get("source_urls"):
        lines.append("**Sources used:** " + ", ".join(report["source_urls"]))
    return "\n".join(lines)


def emit(report: dict[str, Any]) -> None:
    text = summarize(report)
    print("\n" + "=" * 60 + "\n" + text + "\n" + "=" * 60)

    # GitHub Actions: surface in the run summary panel.
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    # Optional webhook (Slack/Discord/etc. accept a {"text": ...} payload).
    if config.NOTIFY_WEBHOOK:
        try:
            httpx.post(config.NOTIFY_WEBHOOK, json={"text": text}, timeout=15)
        except Exception as e:
            print(f"  [notify] webhook failed: {e}")
