"""Groq model fallback: a rate-limited primary model must not stall answers."""

import groq
import httpx
import pytest

from app.services.llm import GroqLLM, LLMError


def _error(cls, status):
    req = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    return cls("error", response=httpx.Response(status, request=req), body=None)


class _Resp:
    def __init__(self, text):
        self.choices = [type("C", (), {"message": type("M", (), {"content": text})()})()]


def _llm(behaviour):
    llm = GroqLLM("key", "big-model", reasoning_effort="low", fallback_models=["small-model"])
    calls = []

    def create(model, system, user):
        calls.append(model)
        outcome = behaviour[model]
        if isinstance(outcome, Exception):
            raise outcome
        return _Resp(outcome)

    llm._create = create  # bypass the network
    return llm, calls


def test_primary_model_used_when_available():
    llm, calls = _llm({"big-model": "answer [1]", "small-model": "unused"})
    result = llm.complete("sys", "user")
    assert (result.text, result.model, calls) == ("answer [1]", "big-model", ["big-model"])


def test_rate_limited_primary_falls_back_immediately():
    llm, calls = _llm({"big-model": _error(groq.RateLimitError, 429), "small-model": "answer [1]"})
    result = llm.complete("sys", "user")
    assert result.model == "small-model" and calls == ["big-model", "small-model"]


def test_retired_model_falls_back():
    llm, _ = _llm({"big-model": _error(groq.NotFoundError, 404), "small-model": "ok"})
    assert llm.complete("sys", "user").model == "small-model"


def test_all_models_rate_limited_gives_friendly_error():
    llm, _ = _llm(
        {"big-model": _error(groq.RateLimitError, 429), "small-model": _error(groq.RateLimitError, 429)}
    )
    with pytest.raises(LLMError, match="busy"):
        llm.complete("sys", "user")


def test_bad_api_key_is_not_retried():
    llm, calls = _llm({"big-model": _error(groq.AuthenticationError, 401), "small-model": "ok"})
    with pytest.raises(LLMError, match="not configured"):
        llm.complete("sys", "user")
    assert calls == ["big-model"]


def test_reasoning_effort_only_for_reasoning_models(monkeypatch):
    llm = GroqLLM("key", "openai/gpt-oss-120b", reasoning_effort="low", fallback_models=["qwen/qwen3.8-27b"])
    seen = {}
    monkeypatch.setattr(
        llm._client.chat.completions, "create", lambda **kw: seen.setdefault(kw["model"], kw) and _Resp("x")
    )
    llm._create("openai/gpt-oss-120b", "s", "u")
    llm._create("qwen/qwen3.8-27b", "s", "u")
    assert seen["openai/gpt-oss-120b"]["reasoning_effort"] == "low"
    assert "reasoning_effort" not in seen["qwen/qwen3.8-27b"]
