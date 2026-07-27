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
        if not config.LLM_API_KEY:
            raise RuntimeError("No LLM key set (GROQ_API_KEY or NVIDIA_API_KEY)")
        # Short per-request timeout so a slow/degraded model fails over fast
        # instead of eating minutes. Failover across models is handled below.
        _client = OpenAI(
            base_url=config.LLM_BASE_URL,
            api_key=config.LLM_API_KEY,
            timeout=60.0,
            max_retries=0,
        )
    return _client


def _candidate_models(model: str | None) -> list[str]:
    """The requested model first, then the fallbacks (de-duplicated)."""
    out: list[str] = []
    for m in [model or config.MODEL, *config.FALLBACK_MODELS]:
        if m and m not in out:
            out.append(m)
    return out


def _call_once(messages: list[dict[str, str]], model: str, temperature: float,
               max_tokens: int) -> str:
    # One attempt. A timeout or error means this model is degraded, so the
    # caller fails over to the next model rather than retrying a bad one.
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
    """Iterate candidate models until one returns parseable JSON.

    A model that times out, returns empty, or returns unparseable JSON is
    abandoned for the next fallback (with one firmer 'JSON only' nudge per
    model), so a single degraded model never fails the whole step.
    """
    nudge = {
        "role": "user",
        "content": "Output ONLY the JSON object. No explanation, no markdown fences, no preamble.",
    }
    first = (model or config.MODEL)
    last_err: Exception | None = None
    for m in _candidate_models(model):
        for msgs, temp in ((messages, temperature), (messages + [nudge], 0.2)):
            try:
                raw = _call_once(msgs, m, temp, max_tokens)
            except Exception as e:  # noqa: BLE001 - degraded model, fail over
                last_err = e
                print(f"  [llm-json] {m} call failed ({type(e).__name__}), next model")
                break  # do not nudge a model that could not even respond
            if not raw.strip():
                last_err = ValueError("empty response")
                break
            try:
                out = _extract_json(raw)
            except ValueError as pe:
                last_err = pe  # try the nudge, then the next model
                continue
            # Some models wrap the object in a one-element array; unwrap it.
            if isinstance(out, list):
                objs = [x for x in out if isinstance(x, dict)]
                out = objs[0] if objs else out
            if isinstance(out, dict):
                if m != first:
                    print(f"  [llm-json] used fallback {m}")
                return out
            last_err = ValueError("parsed JSON was not an object")
    raise last_err or RuntimeError("no candidate model produced valid JSON")


def _extract_json(text: str) -> Any:
    """Pull the first valid JSON object or array out of a model reply."""
    text = text.strip()
    # Drop reasoning traces some models emit before the answer.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
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
