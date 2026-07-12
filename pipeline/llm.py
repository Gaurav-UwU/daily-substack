"""Thin wrapper around the NVIDIA NIM endpoint (OpenAI-compatible).

Only chat completions are used. We add retry/backoff for the free-tier
rate limit (40 req/min) and a tolerant JSON extractor, because not every
hosted model honours response_format={"type":"json_object"}.
"""
from __future__ import annotations

import json
import re
from typing import Any

from openai import OpenAI, APIConnectionError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from . import config

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if not config.NVIDIA_API_KEY:
            raise RuntimeError("NVIDIA_API_KEY is not set")
        # Per-request timeout so a stalled endpoint fails fast instead of
        # eating the whole CI budget. tenacity handles the retries.
        # Short per-request timeout so a slow/DEGRADED model fails over fast
        # instead of eating minutes. Retries are handled below.
        _client = OpenAI(
            base_url=config.NVIDIA_BASE_URL,
            api_key=config.NVIDIA_API_KEY,
            timeout=100.0,
            max_retries=0,
        )
    return _client


def _candidate_models(model: str | None) -> list[str]:
    """The requested model first, then the fallbacks (de-duplicated)."""
    out: list[str] = []
    for m in [model or config.MODEL, *config.NVIDIA_FALLBACK_MODELS]:
        if m and m not in out:
            out.append(m)
    return out


@retry(
    reraise=True,
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type(APIConnectionError),
)
def _call_once(messages: list[dict[str, str]], model: str, temperature: float,
               max_tokens: int) -> str:
    resp = client().chat.completions.create(
        model=model, messages=messages, temperature=temperature,
        top_p=0.9, max_tokens=max_tokens, stream=False,
    )
    return (resp.choices[0].message.content or "").strip()


def chat(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.6,
    max_tokens: int = 2048,
    json_mode: bool = False,   # kept for signature compatibility; unused
) -> str:
    """Return the assistant's text, failing over across models.

    NVIDIA's free tier drops individual hosted models into a DEGRADED state
    (HTTP 400) or makes them very slow. We try the requested model, then the
    fallbacks, so one bad model never kills the run.
    """
    requested = model or config.MODEL
    last_err: Exception | None = None
    for m in _candidate_models(model):
        try:
            out = _call_once(messages, m, temperature, max_tokens)
            if out.strip():
                if m != requested:
                    print(f"  [llm] fell back to {m}")
                return out
            last_err = ValueError("empty response")
            print(f"  [llm] {m} returned empty, trying next model")
        except Exception as e:  # noqa: BLE001 - fail over on any model error
            last_err = e
            print(f"  [llm] {m} failed ({type(e).__name__}: {str(e)[:90]}), trying next model")
    raise last_err or RuntimeError("all candidate models failed")


def chat_json(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 2048,
) -> Any:
    """Call the model and parse a JSON object/array out of the reply.

    We do NOT use response_format=json_object: several NVIDIA-hosted models
    (notably reasoning models) return empty content under it. Instead we ask
    for JSON in the prompt, extract robustly, and retry once on failure.
    """
    raw = chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
    if raw.strip():
        try:
            return _extract_json(raw)
        except ValueError:
            pass
    nudge = messages + [{
        "role": "user",
        "content": "Output ONLY the JSON object. No explanation, no markdown fences, no preamble.",
    }]
    raw2 = chat(nudge, model=model, temperature=0.2, max_tokens=max_tokens)
    return _extract_json(raw2)


def _extract_json(text: str) -> Any:
    """Pull the first valid JSON object or array out of a model reply."""
    text = text.strip()
    # Strip ```json ... ``` fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} or [...] block.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == opener:
                depth += 1
            elif text[i] == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"Could not parse JSON from model reply:\n{text[:500]}")
