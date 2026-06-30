# Daily AI x Product Substack agent

An autonomous pipeline that, every day:

1. **Gathers** trending AI x Product signal from no-cookie sources (Hacker News,
   curated RSS, Reddit, GitHub trending) using `httpx` + **Scrapling**, plus the
   **agent-reach** discovery channels (Exa search, Jina web-to-markdown).
2. **Ranks** the candidates with an LLM editor and picks the single best topic,
   de-duplicating against everything it has written before.
3. **Researches** the topic by deep-fetching its sources with Scrapling.
4. **Writes** an essay in a fixed house voice (sharp, first-principles, no em dashes).
5. **Quality-gates** the draft: an LLM editor scores it on a rubric, and hard
   programmatic checks enforce the style rules.
6. **Publishes** to Substack: it always saves a draft, and auto-publishes only if
   the draft clears the quality threshold (configurable).
7. **Remembers** what it wrote (commits `state/` back) and posts a run summary.

The brain is **NVIDIA NIM** (OpenAI-compatible, free tier), model
`qwen/qwen3-next-80b-a3b-instruct`. The host is **GitHub Actions** on a daily
cron. Publishing goes through **Cloudflare WARP** for a trusted exit IP, since
Substack's Cloudflare blocks GitHub's datacenter IPs. Nothing runs on your machine,
and it costs nothing.

---

## How the pieces map to your stack

| You asked for | How it is used |
|---|---|
| **agent-reach** | Multi-platform discovery. In headless CI it runs its zero-config channels: Exa web search and Jina web-to-markdown (the same upstreams agent-reach orchestrates). `sources.web_search` shells out to the `agent-reach` CLI when `AGENT_REACH_ENABLED=true` and it is installed, otherwise it calls those upstreams directly. |
| **Scrapling** | Primary page fetcher in `sources.py` and `gather.github_trending`. Best at getting past anti-bot walls when pulling full article text for the writer. |
| **Substack** | `python-substack` (unofficial). Draft-first, publish-on-pass. The publish call is routed through a **Cloudflare WARP** SOCKS proxy (set up in the workflow) so it reaches Substack from a trusted IP. |

> **Honest constraint:** headless GitHub Actions has no browser cookies, so true
> Twitter/X and LinkedIn scraping does not run in the cloud. The daily signal comes
> from the no-cookie backbone above, which is plenty for the AI x Product niche.
> To add cookie-gated social, see [Adding social sources](#adding-social-sources).

---

## Setup (about 15 minutes)

### 1. Get the keys
- **NVIDIA API key** (required, free): sign in at <https://build.nvidia.com>, open any
  model, click **Get API Key**. It looks like `nvapi-...`.
- **Substack auth** (required): the robust path is a cookie string.
  1. Log in to Substack in your browser.
  2. Open DevTools > Network, refresh, click any request to `substack.com`.
  3. Right-click the request > **Copy** > **Copy as fetch (Node.js)**.
  4. From what you copied, grab the value of the `cookie:` header. That whole
     string (it contains `substack.sid=...`) is your `SUBSTACK_COOKIES_STRING`.
  - Your `SUBSTACK_PUBLICATION_URL` is e.g. `https://yourhandle.substack.com`.
- **Exa key** (optional, free, improves research): <https://exa.ai>.

### 2. Put this folder on GitHub
```bash
cd "C:/Users/gaura/Side hustle/daily-substack"
git init
git add .
git commit -m "Daily AI x Product Substack agent"
gh repo create daily-substack --private --source=. --push
```
(or create the repo on github.com and push the usual way.)

### 3. Add secrets
Repo > **Settings** > **Secrets and variables** > **Actions** > **New repository secret**:

| Secret | Required | Value |
|---|---|---|
| `NVIDIA_API_KEY` | yes | `nvapi-...` |
| `SUBSTACK_PUBLICATION_URL` | yes | `https://yourhandle.substack.com` |
| `SUBSTACK_COOKIES_STRING` | yes* | the cookie header string |
| `SUBSTACK_EMAIL` / `SUBSTACK_PASSWORD` | yes* | only if your account has a password instead of cookies |
| `EXA_API_KEY` | no | improves research |
| `NOTIFY_WEBHOOK` | no | Slack/Discord incoming webhook for run summaries |

\* Provide cookies **or** email+password. Cookies are recommended.

Optionally set non-secret **Variables** (same screen, Variables tab):
`PUBLISH_MODE` (`gate`/`draft`/`auto`), `QUALITY_THRESHOLD` (default `78`),
`NVIDIA_MODEL`, `NVIDIA_MODEL_REASON`.

### 4. Test it safely
- Go to **Actions** > **Daily Substack post** > **Run workflow**.
- Set **Dry run = true** the first time. It writes `state/posts/<date>.md` and
  never touches Substack. Read the run summary and the committed draft file.
- Then run again with **publish_mode = draft** to confirm Substack auth works
  (a draft appears in your Substack dashboard, nothing goes live).
- When you trust it, leave the daily cron on `gate`.

---

## Publish modes
- `gate` (default): always create a draft; auto-publish **only** if the quality
  score clears `QUALITY_THRESHOLD` and there are no hard fails. Otherwise it waits
  for you as a draft. This is the recommended balance of automation and safety.
- `draft`: never auto-publish. Every day you get a finished draft to review.
- `auto`: publish every day, no gate. Highest risk.

## Tuning
- **Voice:** edit `prompts/voice.md`. This is the highest-leverage file.
- **Sources / niche:** edit `RSS_FEEDS`, `HN_QUERIES`, `SUBREDDITS` in
  `pipeline/config.py`.
- **Schedule:** edit the `cron` in `.github/workflows/daily.yml`.
- **Strictness:** raise `QUALITY_THRESHOLD` to publish less, lower it to publish more.

## Adding social sources
To pull Twitter/X, Reddit (authenticated), or LinkedIn via agent-reach, you need
session cookies, which CI does not have. Two options:
1. Run `run.py` locally on a machine where you have run `agent-reach install` and
   exported cookies, set `AGENT_REACH_ENABLED=true`, and let `sources.web_search`
   / a new gatherer call the agent-reach CLI.
2. Export the cookies into a GitHub secret and load them in the workflow. This is
   fragile (cookies expire) and is best treated as a later upgrade.

## Cost / limits
NVIDIA's free tier is rate-limited (about 40 req/min) and credit-metered. This
pipeline makes roughly 3 to 5 model calls per day, well inside daily limits.
`python-substack` is unofficial and can break if Substack changes its internals;
that is the main maintenance risk. Keep `gate` mode on so a bad day stays a draft.

## Layout
```
run.py                     orchestrator
pipeline/config.py         all settings + env
pipeline/llm.py            NVIDIA NIM client
pipeline/sources.py        Scrapling + agent-reach/Exa/Jina fetch + search
pipeline/gather.py         HN + RSS + Reddit + GitHub trending
pipeline/rank.py           LLM editor picks today's topic
pipeline/research.py       deep-fetch the chosen sources
pipeline/write.py          LLM writes + style sanitizer
pipeline/quality_gate.py   LLM rubric + hard checks
pipeline/publish.py        Substack draft/publish
pipeline/notify.py         run summary + webhook
pipeline/state.py          dedupe memory (state/history.json)
prompts/voice.md           the house voice (edit me)
.github/workflows/daily.yml  the daily cron
```
