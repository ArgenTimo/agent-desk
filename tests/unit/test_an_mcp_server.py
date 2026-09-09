"""An MCP server a project lends to the agents it starts (01M21KG9PAKV2BKZ57CQ0FJB5T).

«Возможность подключить MCP сервер… Когда накидываешь какую-то задачу для agent-deck, у тебя должна
быть возможность как у пользователя подключать и добавлять различные mcp.»
"""

from __future__ import annotations

import ast
import json
import pathlib
import urllib.parse
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import dispatch
from agent_desk.store.repo import McpServer, Store
from agent_desk.web import routes

pytestmark = pytest.mark.unit


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _a_form(fields: dict[str, str]) -> object:
    body = urllib.parse.urlencode(fields).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {
            "content-type": "application/x-www-form-urlencoded",
            "hx-request": "true",
        }

    return Filled()


def _a_server(**over: object) -> McpServer:
    fields: dict[str, object] = {
        "repo_key": "dir:/tmp/thing",
        "name": "the board",
        "kind": "stdio",
        "address": "npx -y @modelcontextprotocol/server-everything",
    }
    return McpServer(**{**fields, **over})  # type: ignore[arg-type]


# --- attaching one --------------------------------------------------------------------------------
async def test_a_server_is_attached_to_a_project(desk: Store) -> None:
    await desk.add_mcp_server("dir:/tmp/thing", "the board", "stdio", "npx -y a-server")

    (one,) = await desk.mcp_servers("dir:/tmp/thing")
    assert (one.name, one.kind, one.address) == ("the board", "stdio", "npx -y a-server")


async def test_one_project_s_servers_are_not_another_s(desk: Store) -> None:
    """A server that reads one company's board is noise in another checkout, which is why
    connectors are per project too."""
    await desk.add_mcp_server("dir:/tmp/thing", "the board", "stdio", "npx -y a-server")

    assert await desk.mcp_servers("dir:/tmp/other") == []


async def test_the_same_name_twice_is_one_server(desk: Store) -> None:
    """Which is what editing one is."""
    await desk.add_mcp_server("k", "the board", "stdio", "the first try")
    await desk.add_mcp_server("k", "the board", "http", "https://example.test/mcp")

    (one,) = await desk.mcp_servers("k")
    assert (one.kind, one.address) == ("http", "https://example.test/mcp")


async def test_a_kind_the_cli_does_not_take_is_refused(desk: Store) -> None:
    """A third kind would be a control that fails when pressed."""
    with pytest.raises(ValueError, match="stdio or http"):
        await desk.add_mcp_server("k", "the board", "carrier pigeon", "somewhere")


async def test_a_secret_where_a_variable_name_belongs_is_refused(desk: Store) -> None:
    """The same guard a project link is under, and it is there because `ghp_R7Sz…` is letters,
    digits and underscores too (docs/07-security.md)."""
    with pytest.raises(ValueError, match="name of an environment variable"):
        await desk.add_mcp_server("k", "b", "stdio", "run it", "ghp_" + "a" * 36)

    assert await desk.mcp_servers("k") == []


async def test_one_can_be_taken_off(desk: Store) -> None:
    await desk.add_mcp_server("k", "the board", "stdio", "run it")

    assert await desk.remove_mcp_server("k", "the board")
    assert await desk.mcp_servers("k") == []


# --- the shape the CLI reads ------------------------------------------------------------------------
def test_a_stdio_server_is_a_command_and_its_arguments() -> None:
    shape = dispatch.as_mcp_config([_a_server(address="npx -y a-server --port 3")])

    assert shape["mcpServers"]["the board"] == {
        "command": "npx",
        "args": ["-y", "a-server", "--port", "3"],
    }


def test_an_http_server_is_a_url() -> None:
    shape = dispatch.as_mcp_config([_a_server(kind="http", address="https://example.test/mcp")])

    assert shape["mcpServers"]["the board"] == {
        "type": "http",
        "url": "https://example.test/mcp",
    }


def test_the_variable_travels_by_name_and_never_by_value() -> None:
    """The name travels; the value is whatever the process this starts already has, and this
    program never holds it (docs/07-security.md)."""
    shape = dispatch.as_mcp_config([_a_server(token_env="A_TOKEN")])

    assert shape["mcpServers"]["the board"]["env"] == {"A_TOKEN": "${A_TOKEN}"}


def test_a_command_that_is_nothing_at_all_is_left_out() -> None:
    assert dispatch.as_mcp_config([_a_server(address="   ")])["mcpServers"] == {}


# --- and what the agent is started with -------------------------------------------------------------
def test_the_config_is_written_under_the_one_tree_this_program_writes_to(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`.mcp.json` in somebody's checkout is precisely what CLAUDE.md's second rule refuses, and a
    person who looks at their tree afterwards finds it as they left it."""
    from agent_desk.config import Settings

    monkeypatch.setattr(dispatch, "settings", Settings(data_dir=tmp_path / "desk"))

    where = dispatch.write_mcp_config([_a_server()])

    assert where is not None
    assert where.parent == tmp_path / "desk"
    assert json.loads(where.read_text())["mcpServers"]["the board"]["command"] == "npx"


def test_a_project_that_lends_nothing_changes_no_command(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An agent started for a project with no servers is started with exactly the command it was
    before."""
    from agent_desk.config import Settings

    monkeypatch.setattr(dispatch, "settings", Settings(data_dir=tmp_path / "desk"))

    assert dispatch.write_mcp_config([]) is None
    assert "--mcp-config" not in dispatch.argv("do it", worktree="w")


def test_the_command_hands_the_file_over() -> None:
    said = dispatch.argv("do it", worktree="w", mcp_config=pathlib.Path("/tmp/desk/mcp.json"))

    assert said[said.index("--mcp-config") + 1] == "/tmp/desk/mcp.json"
    # And the instruction is still last, which is where the CLI takes it.
    assert said[-1] == "do it"


def test_nothing_here_writes_into_the_repository() -> None:
    """The rule, held where it can be checked as the surface grows: the only path this builds is
    under `data_dir`, and `.mcp.json` is not a string anywhere in this program.

    Literals only, docstrings excluded — the same line every structural rule here draws. Naming a
    path in order to explain why this program never writes it is the documentation the rule wants;
    a path in *code* is an open() waiting to happen.
    """
    here = pathlib.Path(__file__).resolve().parents[2] / "agent_desk"
    guilty = []
    for one in sorted(here.rglob("*.py")):
        tree = ast.parse(one.read_text(encoding="utf-8"))
        # The docstring nodes themselves, by identity: `ast.get_docstring` dedents what it returns,
        # so comparing the text would fail to match the constant it came from and every explanation
        # would read as a breach of the rule it explains.
        docs = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        if any(
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and ".mcp.json" in node.value
            and id(node) not in docs
            for node in ast.walk(tree)
        ):
            guilty.append(one.name)

    assert guilty == []


# --- and the panel -----------------------------------------------------------------------------------
async def test_the_project_panel_attaches_and_removes_one(desk: Store) -> None:
    await routes.add_mcp_server(
        _a_form(
            {
                "key": "dir:/tmp/thing",
                "name": "the board",
                "kind": "stdio",
                "address": "npx -y a-server",
            }
        )
    )

    (one,) = await desk.mcp_servers("dir:/tmp/thing")
    assert one.name == "the board"

    await routes.remove_mcp_server(_a_form({"key": "dir:/tmp/thing", "name": "the board"}))
    assert await desk.mcp_servers("dir:/tmp/thing") == []


async def test_the_panel_says_why_it_refused(desk: Store) -> None:
    back = await routes.add_mcp_server(
        _a_form(
            {"key": "k", "name": "b", "kind": "stdio", "address": "run", "token_env": "not a name"}
        )
    )

    assert "environment variable" in back.body.decode()
    assert await desk.mcp_servers("k") == []


async def test_the_panel_lists_them_and_has_no_field_for_a_secret(desk: Store) -> None:
    """The token field names a variable and never holds a value, which is the decision a project
    link was built under and the reason this form has nowhere to type one."""
    await desk.add_mcp_server("k", "the board", "stdio", "npx -y a-server", "A_TOKEN")

    said = await routes.render_project("k")
    form = said[said.index('class="new-server"') :]
    form = form[: form.index("</form>")]

    assert "the board" in said and "A_TOKEN" in said
    assert 'name="token"' not in form
    assert 'name="token_env"' in form
