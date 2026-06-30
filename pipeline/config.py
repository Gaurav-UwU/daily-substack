"""Central configuration. Everything tunable lives here or in env vars."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
POSTS_DIR = STATE_DIR / "posts"
HISTORY_FILE = STATE_DIR / "history.json"
PROMPTS_DIR = ROOT / "prompts"
STATE_DIR.mkdir(exist_ok=True)
POSTS_DIR.mkdir(exist_ok=True)

# --- NVIDIA NIM (OpenAI-compatible) --------------------------------------
NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
# Model picks from a live bake-off (speed + quality on the free tier).
# Writer: qwen3-next-80b-a3b (best prose, ~17s/essay). DeepSeek V4 Pro had the
# best prose but times out on the free tier's low throughput, so it is unusable
# for a timed job. An empty env var falls back here, never to blank.
MODEL = os.getenv("NVIDIA_MODEL", "").strip() or "qwen/qwen3-next-80b-a3b-instruct"
# Judge for ranking + the quality gate. qwen3-next is a plain instruct model
# that returns clean JSON reliably; gpt-oss-120b reasons into a hidden channel
# and returned empty content on the complex ranking prompt.
MODEL_REASON = os.getenv("NVIDIA_MODEL_REASON", "").strip() or "qwen/qwen3-next-80b-a3b-instruct"

# --- Substack ------------------------------------------------------------
SUBSTACK_PUBLICATION_URL = os.getenv("SUBSTACK_PUBLICATION_URL", "").strip()
SUBSTACK_COOKIES_STRING = os.getenv("SUBSTACK_COOKIES_STRING", "").strip()
SUBSTACK_EMAIL = os.getenv("SUBSTACK_EMAIL", "").strip()
SUBSTACK_PASSWORD = os.getenv("SUBSTACK_PASSWORD", "").strip()

# --- Behaviour -----------------------------------------------------------
PUBLISH_MODE = os.getenv("PUBLISH_MODE", "gate").strip().lower()   # gate | draft | auto
QUALITY_THRESHOLD = int(os.getenv("QUALITY_THRESHOLD", "78"))
DRY_RUN = os.getenv("DRY_RUN", "false").strip().lower() in ("1", "true", "yes")

# --- Optional boosters ---------------------------------------------------
EXA_API_KEY = os.getenv("EXA_API_KEY", "").strip()
NOTIFY_WEBHOOK = os.getenv("NOTIFY_WEBHOOK", "").strip()
AGENT_REACH_ENABLED = os.getenv("AGENT_REACH_ENABLED", "false").strip().lower() in ("1", "true", "yes")

# --- Niche: AI x Product -------------------------------------------------
# Hacker News searches (Algolia API, no key, no cookies, always works in CI).
HN_QUERIES = [
    "AI product",
    "AI agents",
    "LLM product",
    "product management AI",
    "AI startup",
    "agentic",
]
HN_MIN_POINTS = 40          # ignore low-signal noise
HN_LOOKBACK_HOURS = 60

# Curated RSS feeds for the AI x Product angle. All public, no auth.
# Substack feeds are <publication>/feed. Add or remove freely.
RSS_FEEDS = [
    "https://www.lennysnewsletter.com/feed",
    "https://every.to/feed.xml",
    "https://www.ben-evans.com/benedictevans?format=rss",
    "https://blog.bytebytego.com/feed",
    "https://huggingface.co/blog/feed.xml",
    "https://openai.com/blog/rss.xml",
    "https://news.ycombinator.com/rss",
    "https://export.arxiv.org/rss/cs.HC",   # human-computer interaction
    "https://export.arxiv.org/rss/cs.AI",
    "https://www.producthunt.com/feed",
]

# Reddit public JSON (best-effort: Reddit may rate-limit CI IPs; non-fatal).
SUBREDDITS = [
    "ProductManagement",
    "artificial",
    "OpenAI",
    "LocalLLaMA",
    "ArtificialInteligence",
]
REDDIT_LOOKBACK = "day"     # hour | day | week

# How many recent posts to remember for de-duplication.
HISTORY_DEDUPE_WINDOW = 90

# Target article shape.
WORD_MIN = 650
WORD_MAX = 1100


def missing_required() -> list[str]:
    """Return a list of human-readable missing-config problems."""
    problems = []
    if not NVIDIA_API_KEY:
        problems.append("NVIDIA_API_KEY is not set")
    if not DRY_RUN:
        if not SUBSTACK_PUBLICATION_URL:
            problems.append("SUBSTACK_PUBLICATION_URL is not set")
        has_cookie = bool(SUBSTACK_COOKIES_STRING)
        has_login = bool(SUBSTACK_EMAIL and SUBSTACK_PASSWORD)
        if not (has_cookie or has_login):
            problems.append(
                "No Substack auth: set SUBSTACK_COOKIES_STRING "
                "(or SUBSTACK_EMAIL + SUBSTACK_PASSWORD)"
            )
    return problems
