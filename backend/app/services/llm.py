"""Groq chat-completion wrapper."""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """User-facing LLM failure (rate limit, outage, misconfiguration)."""


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> str: ...


class GroqLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        timeout: float = 60.0,
        reasoning_effort: str = "",
    ):
        from groq import Groq

        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        self._client = Groq(api_key=api_key, timeout=timeout, max_retries=2)

    def complete(self, system: str, user: str) -> str:
        import groq

        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                **({"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}),
            )
        except groq.RateLimitError as exc:
            raise LLMError("The language model is rate-limited right now. Please retry shortly.") from exc
        except groq.AuthenticationError as exc:
            logger.error("Groq authentication failed — check GROQ_API_KEY")
            raise LLMError("The language model is not configured correctly.") from exc
        except groq.APIError as exc:
            logger.warning("Groq API error: %s", exc.__class__.__name__)
            raise LLMError("The language model is temporarily unavailable.") from exc
        return (resp.choices[0].message.content or "").strip()
