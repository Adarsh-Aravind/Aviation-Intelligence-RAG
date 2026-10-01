"""Groq chat-completion wrapper with model fallback.

Groq's free tier limits tokens per minute *per model* (e.g. 8K TPM for gpt-oss-120b, which is only
2–3 RAG answers a minute). Instead of letting the SDK sleep and retry on a 429, we immediately try
the next model in the list, which has its own quota — so a burst of visitors degrades to a slightly
smaller model rather than to 15-second waits.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """User-facing LLM failure (rate limit, outage, misconfiguration)."""


@dataclass(slots=True)
class LLMResult:
    text: str
    model: str  # the model that actually produced the answer


class LLMClient(Protocol):
    model: str

    def complete(self, system: str, user: str) -> LLMResult: ...


class GroqLLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
        timeout: float = 60.0,
        reasoning_effort: str = "",
        fallback_models: Sequence[str] = (),
    ):
        from groq import Groq

        self.model = model
        self.models = [model, *(m for m in fallback_models if m and m != model)]
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort
        # No SDK-level retries: on 429 / transient errors we move to the next model right away.
        self._client = Groq(api_key=api_key, timeout=timeout, max_retries=0)

    def _create(self, model: str, system: str, user: str):
        extra = {}
        if self.reasoning_effort and "gpt-oss" in model:  # only reasoning models accept this
            extra["reasoning_effort"] = self.reasoning_effort
        return self._client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            **extra,
        )

    def complete(self, system: str, user: str) -> LLMResult:
        import groq

        rate_limited = False
        for model in self.models:
            try:
                resp = self._create(model, system, user)
            except groq.RateLimitError:
                logger.warning("Groq rate limit on %s — trying next model", model)
                rate_limited = True
                continue
            except groq.AuthenticationError as exc:
                logger.error("Groq authentication failed — check GROQ_API_KEY")
                raise LLMError("The language model is not configured correctly.") from exc
            except groq.NotFoundError:
                logger.error("Groq model %s not found (retired?) — update GROQ_MODEL", model)
                continue
            except (groq.APIConnectionError, groq.InternalServerError) as exc:
                logger.warning(
                    "Groq unavailable for %s (%s) — trying next model", model, exc.__class__.__name__
                )
                continue
            except groq.APIError as exc:
                logger.warning("Groq API error on %s: %s", model, exc.__class__.__name__)
                raise LLMError("The language model is temporarily unavailable.") from exc
            return LLMResult(text=(resp.choices[0].message.content or "").strip(), model=model)

        if rate_limited:
            raise LLMError("The AI is busy right now (free-tier rate limit). Please try again in a minute.")
        raise LLMError("The language model is temporarily unavailable.")
