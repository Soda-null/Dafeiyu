"""The skeleton holds together and the dependency rules in AGENTS.md and
docs/nodes_design_zh.md §2 are obeyed."""

import importlib
import re
from pathlib import Path

import fish

MODULES = [
    "fish.config", "fish.storage", "fish.persona", "fish.memory", "fish.mood",
    "fish.brain", "fish.routines", "fish.channels", "fish.cottage", "fish.msgs", "fish.bus", "fish.clock",
]
NO_CHANNELS = ["brain", "memory", "mood", "persona", "storage", "routines", "cottage"]
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


# --- rule 3 (docs/nodes_design_zh.md §2): a node reaches another node only through what that
# node's __init__.py exports, and only the node that owns a table writes SQL on it. The old
# debts are listed here and let through; anything new fails. Fix one, strike its line: the
# test says so when a listed debt is gone, so the list only ever gets shorter.

DEEP_IMPORT = re.compile(r"^\s*(?:from|import)\s+fish\.([a-z_]+)\.([a-z_][a-z_.]*)", re.M)
SQL = re.compile(r"\.execute(?:many|script)?\(")
SQL_OWNERS = ("storage/", "memory/", "mood/", "routines/runs.py")  # mood and runs own their tables
LAUNCH = ("__main__.py",)  # the launch file wires nodes together; it may reach in

KNOWN_DEEP_IMPORTS = {
    "brain/leisure/book.py -> world.http", "brain/leisure/book.py -> world.wikisource",
    "brain/reach.py -> memory.longterm", "brain/reach.py -> memory.prospective",
    "routines/outside.py -> world.days", "routines/outside.py -> world.http", "routines/outside.py -> world.place",
    # imported inside functions (found by the test, not by eye)
    "brain/consolidate.py -> memory.retrieval",
    "mood/state.py -> memory.longterm", "routines/browse.py -> brain.respond", "routines/browse.py -> brain.world",
    "routines/nightly.py -> brain.consolidate", "routines/nightly.py -> brain.leisure",
    "routines/nightly.py -> brain.respond", "routines/outside.py -> brain.ask", "routines/outside.py -> brain.respond",
    "routines/stickers.py -> brain.ask", "routines/stickers.py -> brain.respond",
}
KNOWN_SQL = {"brain/reach.py", "brain/leisure/free.py", "routines/nightly.py"}


def _node_files():
    for py in sorted(SRC.rglob("*.py")):
        rel = py.relative_to(SRC).as_posix()
        if "/" in rel and not rel.startswith(LAUNCH):
            yield rel, py.read_text(encoding="utf-8")


def test_nodes_reach_each_other_only_through_their_exports():
    found = set()
    for rel, src in _node_files():
        node = rel.split("/")[0]
        for other, inner in DEEP_IMPORT.findall(src):
            if other != node and (SRC / other).is_dir():
                found.add(f"{rel} -> {other}.{inner.split('.')[0]}")
    new, paid = found - KNOWN_DEEP_IMPORTS, KNOWN_DEEP_IMPORTS - found
    assert not new, f"new import past another node's __init__.py (export it there instead): {sorted(new)}"
    assert not paid, f"fixed, strike from KNOWN_DEEP_IMPORTS: {sorted(paid)}"


def test_only_a_table_s_owner_writes_sql_on_it():
    found = {rel for rel, src in _node_files() if SQL.search(src) and not rel.startswith(SQL_OWNERS)}
    new, paid = found - KNOWN_SQL, KNOWN_SQL - found
    assert not new, f"new SQL outside the node that owns the table (add a method there): {sorted(new)}"
    assert not paid, f"fixed, strike from KNOWN_SQL: {sorted(paid)}"


def test_the_contract_and_the_bus_depend_on_nothing():
    for name in ("msgs.py", "bus.py"):
        src = (SRC / name).read_text(encoding="utf-8")
        assert not re.search(r"^\s*(?:from|import)\s+fish\b", src, re.M), f"{name} must stay dependency-free"
