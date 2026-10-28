"""Settings read once from .env. Nothing else in the package touches os.environ."""

from __future__ import annotations

import json
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
    leisure: bool = True  # free moments where she may do something or nothing (decision 24)
    leisure_max_per_day: int = 3
    home_at: str = ""  # "lat,lon" where she lives, when not the machine's own city (decision 15)


def owner_words(text: str) -> str:
    """The persona and prompts call the user 他; with FISH_OWNER=她 in .env they say 她.
    Only for our own text, never for the user's words. 其他 stays 其他."""
    if os.environ.get("FISH_OWNER", "他") != "她":
        return text
    return re.sub(r"(?<!其)他", "她", text)


def home_timezone(home_file: Path) -> str:
    """The timezone of where she lives, saved with her home (decision 15) once she has
    located it; "" before that or when the file is unreadable."""
    try:
        return str(json.loads(home_file.read_text(encoding="utf-8")).get("tz") or "")
    except (OSError, ValueError):
        return ""


def load_settings(env_file: Path | None = None) -> Settings:
    """Read .env (or the given file). Missing key is allowed so tests can run offline.

    Her clock: a TZ line in .env wins (the user lives elsewhere than the machine); without
    one, the timezone of where she lives, so "late at night" is her night even on a machine
    whose clock was set up in another country."""
    load_dotenv(env_file or REPO_ROOT / ".env")
    db = os.environ.get("FISH_DB_PATH", "data/fish.db")
    db_path = Path(db) if Path(db).is_absolute() else REPO_ROOT / db
    tz = os.environ.get("TZ") or home_timezone(db_path.parent / "home" / "home.json")
    if tz:
        os.environ["TZ"] = tz
        if hasattr(time, "tzset"):
            time.tzset()
    elif "TZ" in os.environ:
        del os.environ["TZ"]  # an empty TZ= line would mean UTC to the C library
    return Settings(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        db_path=db_path,
        window_size=int(os.environ.get("FISH_WINDOW_SIZE", "20")),
        prompt_chars=int(os.environ.get("FISH_PROMPT_CHARS", "6000")),
        reach_out=os.environ.get("FISH_REACH_OUT", "1") not in ("0", "false", "no", ""),
        reach_max_per_day=int(os.environ.get("FISH_REACH_MAX", "2")),
        leisure=os.environ.get("FISH_LEISURE", "1") not in ("0", "false", "no", ""),
        leisure_max_per_day=int(os.environ.get("FISH_LEISURE_MAX", "3")),
        home_at=os.environ.get("FISH_HOME", "").replace(" ", ""),
    )
