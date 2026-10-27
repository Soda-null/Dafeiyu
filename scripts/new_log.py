#!/usr/bin/env python3
"""Create today's docs/log/YYYY-MM-DD.md from TEMPLATE.md; never overwrites.

Run: python3 scripts/new_log.py [--date 2026-10-26]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "docs" / "log"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat, default=date.today())
    day = ap.parse_args().date.isoformat()
    target = LOG_DIR / f"{day}.md"
    if target.exists():
        print(f"exists, not touched: {target.relative_to(ROOT)}")
        return 0
    template = (LOG_DIR / "TEMPLATE.md").read_text(encoding="utf-8")
    target.write_text(template.replace("{{date}}", day), encoding="utf-8")
    print(f"created: {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
