"""One JSON question to the model from a prompt template. A failed call or bad JSON
returns None: callers treat that as "nothing this time", never as an error."""

from __future__ import annotations

from fish.brain.llm import LLM
from fish.brain.parse import extract_json
from fish.brain.prompt import load_template, render


def ask_json(llm: LLM, template: str, *, temperature: float = 0.5, max_tokens: int = 800,
             image: str | None = None, **fields: str) -> dict | None:
    """`image` is a data URL; it rides in the user message, the only place pictures may go."""
    text = render(load_template(template), **fields)
    content = text if image is None else [{"type": "text", "text": text},
                                          {"type": "image_url", "image_url": {"url": image}}]
    try:
        raw = llm.chat([{"role": "user", "content": content}], json_mode=True,
                       temperature=temperature, max_tokens=max_tokens)
    except Exception:  # noqa: BLE001 - the routine must go on without the model
        return None
    return extract_json(raw)
