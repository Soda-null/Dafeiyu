"""The skeleton holds together and the dependency rule in AGENTS.md is obeyed."""

import importlib
from pathlib import Path

import fish

MODULES = [
    "fish.config", "fish.storage", "fish.persona", "fish.memory", "fish.mood",
    "fish.brain", "fish.routines", "fish.channels",
]
NO_CHANNELS = ["brain", "memory", "mood", "persona", "storage", "routines"]
SRC = Path(fish.__file__).parent


def test_all_modules_import():
    for name in MODULES:
        importlib.import_module(name)


def test_brain_memory_mood_do_not_import_channels():
    for pkg in NO_CHANNELS:
        for py in (SRC / pkg).rglob("*.py"):
            src = py.read_text(encoding="utf-8")
            assert "from fish.channels" not in src and "import fish.channels" not in src, (
                f"{py} imports channels"
            )


def test_persona_loads_without_header_card():
    from fish.persona import load_persona

    text = load_persona()
    assert "大肥鱼" in text
    assert "**地位：**" not in text
