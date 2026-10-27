"""Settings read once from .env. Nothing else in the package touches os.environ."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
PERSONA_PATH = REPO_ROOT / "docs" / "persona_zh.md"


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    model: str
    db_path: Path
    window_size: int = 20
    prompt_chars: int = 6000  # docs/memory_design_zh.md §2
    reach_out: bool = True  # may she message first (decision 10)
    reach_max_per_day: int = 2
    home_at: str = ""  # "lat,lon" where she lives, when not the machine's own city (decision 15)


def owner_words(text: str) -> str:
    """The persona and prompts call the user 他; with FISH_OWNER=她 in .env they say 她.
    Only for our own text, never for the user's words. 其他 stays 其他."""
    if os.environ.get("FISH_OWNER", "他") != "她":
        return text
    return re.sub(r"(?<!其)他", "她", text)


def load_settings(env_file: Path | None = None) -> Settings:
    """Read .env (or the given file). Missing key is allowed so tests can run offline.

    A TZ line in .env sets her clock (so "late at night" is the user's night even when she
    runs on a machine in another timezone)."""
    load_dotenv(env_file or REPO_ROOT / ".env")
    if os.environ.get("TZ") and hasattr(time, "tzset"):
        time.tzset()
    db = os.environ.get("FISH_DB_PATH", "data/fish.db")
    db_path = Path(db) if Path(db).is_absolute() else REPO_ROOT / db
    return Settings(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        db_path=db_path,
        window_size=int(os.environ.get("FISH_WINDOW_SIZE", "20")),
        prompt_chars=int(os.environ.get("FISH_PROMPT_CHARS", "6000")),
        reach_out=os.environ.get("FISH_REACH_OUT", "1") not in ("0", "false", "no", ""),
        reach_max_per_day=int(os.environ.get("FISH_REACH_MAX", "2")),
        home_at=os.environ.get("FISH_HOME", "").replace(" ", ""),
    )
