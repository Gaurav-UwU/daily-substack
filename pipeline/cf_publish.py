"""Cloudflare-bypassing Substack publisher.

Substack sits behind Cloudflare, which challenges requests from datacenter IPs
(GitHub Actions). The cookie/session is valid; the IP is what gets blocked. So
we drive a Camoufox stealth browser (the same engine Scrapling's StealthyFetcher
uses) to clear the challenge, then make the draft/publish API calls from INSIDE
the browser context, where they carry the right IP, cookies, and TLS fingerprint.

We only use python-substack's Post class for payload construction (pure, no
network). The user id comes from the substack.lli JWT, so no pre-flight API call
is needed.
"""
from __future__ import annotations

import base64
import json
from typing import Any

from . import config


def _user_id_from_cookies(cookie_str: str) -> int | None:
    """Decode the substack.lli JWT to read the userId without any API call."""
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if pair.startswith("substack.lli="):
            token = pair.split("=", 1)[1]
            try:
                payload_b64 = token.split(".")[1]
                payload_b64 += "=" * (-len(payload_b64) % 4)  # fix padding
                data = json.loads(base64.urlsafe_b64decode(payload_b64))
                return int(data.get("userId"))
            except Exception:
                return None
    return None


def _browser_cookies(cookie_str: str) -> list[dict[str, Any]]:
    """Cookies for the browser context. Skip cf_* so Camoufox earns fresh ones."""
    out = []
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        name = name.strip()
        if name.startswith(("cf_", "__cf")):
            continue
        out.append({"name": name, "value": value.strip(),
                    "domain": ".substack.com", "path": "/"})
    return out


def _build_payload(article: dict[str, str], user_id: int) -> str:
    from substack.post import Post
    post = Post(
        title=article["title"],
        subtitle=article.get("subtitle", ""),
        user_id=user_id,
        audience="everyone",
    )
    post.from_markdown(article["body_markdown"])
    return json.dumps(post.get_draft())


_JS = """
async (args) => {
  const payload = JSON.parse(args.payloadJson);
  const r = await fetch('/api/v1/drafts', {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify(payload),
    credentials: 'include',
  });
  const txt = await r.text();
  if (!r.ok) return {ok: false, stage: 'draft', status: r.status, body: txt.slice(0, 300)};
  let draft;
  try { draft = JSON.parse(txt); } catch (e) { return {ok: false, stage: 'draft-parse', body: txt.slice(0, 300)}; }
  const id = draft.id;
  let published = false;
  if (args.shouldPublish && id) {
    await fetch(`/api/v1/drafts/${id}/prepublish`, {credentials: 'include'});
    const p = await fetch(`/api/v1/drafts/${id}/publish`, {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({send: false, share_automatically: false}),
      credentials: 'include',
    });
    if (!p.ok) return {ok: false, stage: 'publish', status: p.status, id: id, body: (await p.text()).slice(0, 300)};
    published = true;
  }
  return {ok: true, id: id, published: published};
}
"""


def browser_push(article: dict[str, str], *, should_publish: bool) -> dict[str, Any]:
    """Create the draft (and optionally publish) via a stealth browser."""
    cookie_str = config.SUBSTACK_COOKIES_STRING
    if not cookie_str:
        return _err("cf bypass needs SUBSTACK_COOKIES_STRING")

    user_id = _user_id_from_cookies(cookie_str)
    if not user_id:
        return _err("could not read user id from substack.lli cookie")

    try:
        payload_json = _build_payload(article, user_id)
    except Exception as e:
        return _err(f"payload build failed: {type(e).__name__}: {e}")

    pub_root = config.SUBSTACK_PUBLICATION_URL.rstrip("/")

    try:
        from camoufox.sync_api import Camoufox
    except Exception as e:
        return _err(f"camoufox not available: {e}")

    cookies = _browser_cookies(cookie_str)
    result = None
    last_err = None
    # geoip=True is stealthier but needs the extra db; fall back without it.
    for geoip in (True, False):
        try:
            print(f"  [cf] launching stealth browser (geoip={geoip})...")
            with Camoufox(headless=True, geoip=geoip, humanize=False) as browser:
                # no_viewport: Camoufox manages its own spoofed screen; setting a
                # fixed viewport triggers a setDefaultViewport protocol error.
                page = browser.new_page(no_viewport=True)
                page.context.add_cookies(cookies)
                # Navigate to the API path itself so Cloudflare issues a challenge
                # we can SOLVE via a full navigation (a fetch cannot solve one).
                # This grants cf_clearance for the host, which the POST then carries.
                page.goto(pub_root + "/api/v1/drafts",
                          wait_until="domcontentloaded", timeout=60000)
                # Wait for the Cloudflare interstitial to clear.
                for _ in range(25):
                    title = (page.title() or "").lower()
                    if "just a moment" not in title and "attention required" not in title:
                        break
                    page.wait_for_timeout(1500)
                page.wait_for_timeout(3000)
                # Back to an HTML page (cf_clearance is now set) for a clean JS
                # context to run the fetch from.
                page.goto(pub_root, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(1500)
                print("  [cf] challenge cleared, calling Substack API...")
                result = page.evaluate(_JS, {"payloadJson": payload_json,
                                             "shouldPublish": should_publish})
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            print(f"  [cf] attempt with geoip={geoip} failed: {last_err}")

    if result is None:
        return _err(f"browser flow failed: {last_err}")
    if not result.get("ok"):
        return _err(f"substack api via browser failed: {json.dumps(result)[:300]}")

    draft_id = result.get("id")
    return {
        "dry_run": False,
        "published": bool(result.get("published")),
        "draft_id": draft_id,
        "draft_url": f"{pub_root}/publish/post/{draft_id}" if draft_id else None,
        "error": None,
        "via": "cf-bypass",
    }


def _err(msg: str) -> dict[str, Any]:
    return {"dry_run": False, "published": False, "draft_id": None,
            "draft_url": None, "error": msg, "via": "cf-bypass"}
