"""Push the article to Substack as a draft, and publish it when allowed.

Uses the unofficial python-substack library. Cookie auth is preferred (most
Substack accounts are magic-link only and have no password). Always creates a
draft first; only publishes when the publish decision says so.
"""
from __future__ import annotations

from typing import Any

from . import config


def _api():
    from substack import Api
    if config.SUBSTACK_COOKIES_STRING:
        return Api(
            cookies_string=config.SUBSTACK_COOKIES_STRING,
            publication_url=config.SUBSTACK_PUBLICATION_URL,
        )
    if config.SUBSTACK_EMAIL and config.SUBSTACK_PASSWORD:
        return Api(
            email=config.SUBSTACK_EMAIL,
            password=config.SUBSTACK_PASSWORD,
            publication_url=config.SUBSTACK_PUBLICATION_URL,
        )
    raise RuntimeError("No Substack auth configured (cookies or email+password).")


def _draft_url(draft_id: Any) -> str:
    base = config.SUBSTACK_PUBLICATION_URL.rstrip("/")
    return f"{base}/publish/post/{draft_id}"


def push(article: dict[str, str], *, should_publish: bool) -> dict[str, Any]:
    """Create the draft and optionally publish, with a hard timeout guard."""
    if config.DRY_RUN:
        return {"dry_run": True, "published": False, "draft_id": None,
                "draft_url": None, "error": None}

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_do_push, article, should_publish)
        try:
            return future.result(timeout=150)
        except concurrent.futures.TimeoutError:
            return {"dry_run": False, "published": False, "draft_id": None,
                    "draft_url": None, "error": "Substack call timed out after 150s"}


def _do_push(article: dict[str, str], should_publish: bool) -> dict[str, Any]:
    from substack.post import Post

    try:
        api = _api()
        user_id = api.get_user_id()
        post = Post(
            title=article["title"],
            subtitle=article.get("subtitle", ""),
            user_id=user_id,
            audience="everyone",
        )
        try:
            post.from_markdown(article["body_markdown"], api=api)
        except TypeError:
            post.from_markdown(article["body_markdown"])

        draft = api.post_draft(post.get_draft())
        draft_id = draft.get("id") if isinstance(draft, dict) else None

        published = False
        if should_publish and draft_id is not None:
            api.prepublish_draft(draft_id)
            api.publish_draft(draft_id)
            published = True

        return {
            "dry_run": False,
            "published": published,
            "draft_id": draft_id,
            "draft_url": _draft_url(draft_id) if draft_id else None,
            "error": None,
        }
    except Exception as e:
        return {"dry_run": False, "published": False, "draft_id": None,
                "draft_url": None, "error": f"{type(e).__name__}: {e}"}
