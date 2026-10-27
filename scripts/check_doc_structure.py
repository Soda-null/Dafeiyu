#!/usr/bin/env python3
"""Check the rules in docs/writing_guide_zh.md §5. Reports only; never edits.

1. Every .md directly under docs/ and every README.md in the tree has `**地位：**` or
   `**Standing:**` in its first 15 lines.
2. docs/README.md names every .md directly under docs/ and every folder under docs/.
3. Entry-file size budgets: STATUS.md 8 KB, AGENTS.md 8 KB.

Run: python3 scripts/check_doc_structure.py   (exit 0 = clean, 1 = findings)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD_KEYS = ("**地位：**", "**Standing:**")
CARD_LINES = 15
BUDGET_KB = {"STATUS.md": 8, "AGENTS.md": 8}
SKIP_DIRS = {".git", ".venv", "venv", "data", "__pycache__", ".pytest_cache"}


def has_card(path: Path) -> bool:
    head = path.read_text(encoding="utf-8").splitlines()[:CARD_LINES]
    return any(k in line for line in head for k in CARD_KEYS)


def main() -> int:
    findings: list[str] = []
    docs = ROOT / "docs"

    to_check = [p for p in docs.glob("*.md")]
    to_check += [p for p in ROOT.rglob("README.md") if not (set(p.parts) & SKIP_DIRS)]
    for p in to_check:
        if not has_card(p):
            findings.append(f"no header card in first {CARD_LINES} lines: {p.relative_to(ROOT)}")

    index = (docs / "README.md").read_text(encoding="utf-8")
    for p in sorted(docs.iterdir()):
        if p.name == "README.md" or p.name.startswith("."):
            continue
        name = p.name if p.is_file() else p.name + "/"
        if f"`{name}`" not in index:
            findings.append(f"docs/README.md does not list `{name}`")

    for name, kb in BUDGET_KB.items():
        size = (ROOT / name).stat().st_size
        if size > kb * 1024:
            findings.append(f"{name} is {size} bytes, budget {kb} KB")

    for f in findings:
        print(f"finding: {f}")
    print("doc structure: clean" if not findings else f"doc structure: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
