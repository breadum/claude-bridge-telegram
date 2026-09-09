"""Turn a session's first prompt into a short topic title via the Anthropic API.

Optional: only used when `anthropic_api_key` is configured. Any failure returns
None and the caller falls back to a truncated prompt.
"""

from __future__ import annotations

import httpx

_URL = "https://api.anthropic.com/v1/messages"
_PROMPT = (
    "Write a very short topic title (3 to 6 words) summarising this request. "
    "Reply with the title only — no quotes, no trailing period, same language "
    "as the request.\n\nRequest:\n{prompt}"
)


def summarize_title(
    prompt: str,
    *,
    api_key: str,
    model: str,
    timeout: float = 10.0,
) -> str | None:
    prompt = prompt.strip()
    if not prompt or not api_key:
        return None
    try:
        resp = httpx.post(
            _URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 40,
                "messages": [
                    {"role": "user", "content": _PROMPT.format(prompt=prompt[:2000])}
                ],
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        title = " ".join("".join(parts).split()).strip().strip('"').strip()
        return title or None
    except (httpx.HTTPError, ValueError, KeyError):
        return None
