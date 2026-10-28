"""The model call. One small interface so tests can swap in a fake."""

from __future__ import annotations

from typing import Callable, Protocol

from fish.config import Settings


class LLM(Protocol):
    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False,
             temperature: float = 1.0, max_tokens: int = 800) -> str: ...


class DeepSeekLLM:
    """DeepSeek's API is OpenAI-compatible; the client is created lazily so importing
    this module never needs a key. json_mode asks for a JSON object (the prompt must
    contain the word "json", which our templates do)."""

    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is empty; copy .env.example to .env and fill it in")
        from openai import OpenAI  # imported here so tests run without the package configured

        self._client = OpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=60)
        self._model = settings.model
        self.last_finish: str | None = None  # why the last reply stopped ("stop", "length")

    def chat(self, messages, *, json_mode=False, temperature=1.0, max_tokens=800) -> str:
        kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
        resp = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=temperature,
            max_tokens=max_tokens, **kwargs,
        )
        self.last_finish = resp.choices[0].finish_reason
        return (resp.choices[0].message.content or "").strip()


class CountingLLM:
    """Wraps any LLM and counts calls and characters in and out (the checkup's cost line)."""

    def __init__(self, inner: LLM) -> None:
        self.inner = inner
        self.calls = 0
        self.chars_in = 0
        self.chars_out = 0

    def chat(self, messages, *, json_mode=False, temperature=1.0, max_tokens=800) -> str:
        self.calls += 1
        self.chars_in += sum(len(_text_of(m["content"])) for m in messages)
        out = self.inner.chat(messages, json_mode=json_mode, temperature=temperature,
                              max_tokens=max_tokens)
        self.chars_out += len(out)
        return out

    @property
    def last_finish(self) -> str | None:
        return getattr(self.inner, "last_finish", None)


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


Responder = Callable[[list[dict[str, str]], bool], str]


class FakeLLM:
    """For tests: answers from a list (in order) or from a function of (messages, json_mode).
    Every call is kept in `calls` so a test can look at the prompt that was built."""

    def __init__(self, responses: list[str] | Responder) -> None:
        self._responses = responses
        self.calls: list[tuple[list[dict[str, str]], bool]] = []

    def chat(self, messages, *, json_mode=False, temperature=1.0, max_tokens=800) -> str:
        self.calls.append((messages, json_mode))
        if callable(self._responses):
            return self._responses(messages, json_mode)
        if not self._responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        return self._responses.pop(0)
