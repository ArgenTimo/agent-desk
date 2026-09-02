"""The two structural rules of design/01-module-layout.md, enforced rather than remembered.

Both are written before the code they constrain. That order is deliberate: a boundary added after
the first violation is a boundary that has already failed once, and these two are the mechanisms
behind docs/adr/0002 and docs/adr/0004 — the reasons this tool is safe to point at a working
session at all.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PKG = Path(__file__).resolve().parents[2] / "agent_desk"


def _modules() -> list[Path]:
    return sorted(p for p in PKG.rglob("*.py"))


def _imported_names(path: Path) -> set[str]:
    """Every module named by an import in `path`, as a dotted string."""
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
    return names


def _string_literals(path: Path) -> list[str]:
    """Every string constant in `path` except docstrings.

    A path named in a docstring is an explanation; a path named in code is an open() waiting to
    happen. Only the second is what these rules are about.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


@pytest.mark.unit
def test_only_web_imports_the_write_path() -> None:
    """docs/adr/0002: the one path that messages a running session is reached by a human click.

    `peer` is that path. If `observe`, `store`, `answer` or `ideas` can import it, then a
    background loop can message a session, and the property the whole tool rests on — that reading
    is invisible to the agent being read — stops being structural and becomes a habit.
    """
    offenders = []
    for path in _modules():
        rel = path.relative_to(PKG)
        if rel.parts[0] in {"web"} or rel.name == "peer.py":
            continue
        if any(n == "agent_desk.peer" or n.endswith(".peer") for n in _imported_names(path)):
            offenders.append(str(rel))

    assert not offenders, (
        "only agent_desk/web/ may import the peer-messaging path (docs/adr/0002); "
        f"found in: {offenders}"
    )


@pytest.mark.unit
def test_only_observe_parses_the_on_disk_formats() -> None:
    """docs/adr/0004: the formats under ~/.claude/ live behind one parser.

    The failure this prevents is not "the format changed" — that is expected. It is the format
    changing quietly, `.get()` returning None at five call sites, and the board rendering a
    plausible, wrong picture. One parser turns that into one loud failure.
    """
    offenders = []
    for path in _modules():
        rel = path.relative_to(PKG)
        if rel.parts[0] == "observe":
            continue
        source = path.read_text()
        # `json.load` is a prefix of `json.loads`, so one check covers both.
        uses_json = "json.load" in source
        touches_claude = ".claude/sessions" in source or ".claude/projects" in source
        # config.py names the paths for everyone; naming is not parsing.
        if touches_claude and rel.name != "config.py":
            offenders.append(f"{rel} (references ~/.claude paths)")
        elif uses_json:
            offenders.append(f"{rel} (parses JSON)")

    assert not offenders, (
        "only agent_desk/observe/ may read or parse what Claude Code writes to disk "
        f"(docs/adr/0004); found in: {offenders}"
    )


@pytest.mark.unit
def test_no_code_names_a_credential_path() -> None:
    """docs/07-security.md: the key files sit beside the registry entries with the same stem.

    `~/.claude/sessions/` holds `<pid>.json`, which is the board's backbone, and `<pid>.<hash>.key`,
    which authenticates that session's messaging socket. A glob of `sessions/*` where
    `sessions/*.json` was meant reads an authentication key into a process whose whole job is to
    render things, and nothing else in the system would notice.

    Docstrings and comments are excluded on purpose: naming a path in order to explain why it is
    never opened is the documentation this rule wants, not a violation of it.
    """
    forbidden = (".credentials.json", ".key", "cc-socks")
    offenders = [
        f"{path.relative_to(PKG)}: {literal!r}"
        for path in _modules()
        for literal in _string_literals(path)
        for token in forbidden
        if token in literal
    ]
    assert not offenders, f"no string literal may name a credential path: {offenders}"


@pytest.mark.unit
def test_the_registry_glob_is_never_widened() -> None:
    """`sessions/*.json`, never `sessions/*` — the single character that separates the two.

    This is the concrete form of the rule above, and it is the one that would be broken by an
    innocent-looking simplification rather than by a deliberate choice.
    """
    offenders = [
        f"{path.relative_to(PKG)}: {literal!r}"
        for path in _modules()
        for literal in _string_literals(path)
        if "sessions" in literal and literal.rstrip("/").endswith("*")
    ]
    assert not offenders, f"the registry glob must end in *.json: {offenders}"
