"""Thin Anthropic API client for the debate.

Isolated on purpose: in --dry-run nothing here is called, so the whole pipeline
can be inspected with no key and no spend. The real path uses the official
`anthropic` SDK if installed, else a direct HTTPS call via requests.
"""
import json
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    ok: bool
    error: str = ""


class AnthropicClient:
    def __init__(self, api_key: str, model: str, max_tokens: int):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens

    def call(self, messages, system: str) -> LLMResponse:
        """Single completion. Returns text + real token usage."""
        if not self.api_key:
            return LLMResponse("", 0, 0, ok=False,
                               error="no ANTHROPIC key set")
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "system": system,
                    "messages": messages,
                },
                timeout=60,
            )
            if r.status_code != 200:
                return LLMResponse("", 0, 0, ok=False,
                                   error=f"HTTP {r.status_code}: {r.text[:200]}")
            data = r.json()
            text = "".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type") == "text"
            )
            usage = data.get("usage", {})
            return LLMResponse(
                text=text,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                ok=True,
            )
        except requests.RequestException as e:
            return LLMResponse("", 0, 0, ok=False, error=f"request failed: {e}")
