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
    """Create the draft and optionally publish.

    Tries the direct API first. If Cloudflare blocks it (the normal case on
    GitHub's datacenter IPs), falls back to the stealth-browser bypass.
    """
    if config.DRY_RUN:
        return {"dry_run": True, "published": False, "draft_id": None,
                "draft_url": None, "error": None}

    result = _try_requests(article, should_publish)
    if result.get("error") and _is_cloudflare(result["error"]):
        print("  [publish] direct call blocked by Cloudflare; using stealth bypass...")
        from . import cf_publish
        return cf_publish.browser_push(article, should_publish=should_publish)
    return result


def _is_cloudflare(err: str) -> bool:
    e = (err or "").lower()
    return any(s in e for s in (
        "just a moment", "cloudflare", "attention required",
        "enable javascript", "403", "challenge",
    ))


def _try_requests(article: dict[str, str], should_publish: bool) -> dict[str, Any]:
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(_do_push, article, should_publish)
        try:
            return future.result(timeout=120)
        except concurrent.futures.TimeoutError:
            return {"dry_run": False, "published": False, "draft_id": None,
                    "draft_url": None, "error": "direct Substack call timed out"}


import contextlib


@contextlib.contextmanager
def _warp_env():
    """Temporarily route requests (python-substack) through the WARP SOCKS proxy."""
    warp = config.WARP_PROXY
    if not warp:
        yield
        return
    import os
    keys = ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ[k] = warp
    print("  [publish] routing Substack through WARP proxy")
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _do_push(article: dict[str, str], should_publish: bool) -> dict[str, Any]:
    with _warp_env():
        return _do_push_inner(article, should_publish)


def _do_push_inner(article: dict[str, str], should_publish: bool) -> dict[str, Any]:
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
