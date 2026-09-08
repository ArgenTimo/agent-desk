"""Making something out of the files on the bench, and the permission that costs
(01M1X8DA75NXRY6WCSD5Q7V56K).

"Здесь нужно решить границу: карточка-папка сегодня НЕ открывает файлы, и это осознанное правило
безопасности. «Собери из них» означает, что файлы будут прочитаны — значит, это отдельное
разрешение, которое человек даёт явно, а не побочный эффект просьбы."

So the folder reader still never opens anything — a test walks its syntax tree — and opening one
file is a different module, reached only through a click somebody made on a card naming the file.
"""

from __future__ import annotations

import ast
import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk.observe import folder, reading
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
FOLDER_CARD = HERE / "agent_desk" / "web" / "templates" / "_card_folder.html"
FILE_CARD = HERE / "agent_desk" / "web" / "templates" / "_card_file.html"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


# --- the rule that did not move ---------------------------------------------------------------------
def test_the_folder_reader_still_never_opens_anything() -> None:
    """It is a separate module so that both rules can be stated without qualification. Weakening
    this test to let one function through is how a security invariant becomes a habit."""
    tree = ast.parse(pathlib.Path(folder.__file__).read_text(encoding="utf-8"))
    called = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

    for opening in ("read_text", "read_bytes", "open"):
        assert opening not in called, opening


def test_a_folder_card_still_says_nothing_was_opened(tmp_path: pathlib.Path) -> None:
    (tmp_path / "secrets.env").write_text("TOKEN=hunter2\n")

    assert "hunter2" not in folder.about(folder.read(str(tmp_path)))


# --- what a click cannot unlock -----------------------------------------------------------------------
@pytest.mark.parametrize(
    "name", [".env", ".env.local", "prod.env", "server.key", "cert.pem", "store.p12"]
)
def test_a_credential_is_refused_however_it_is_reached(tmp_path: pathlib.Path, name: str) -> None:
    (tmp_path / name).write_text("TOKEN=hunter2\n")

    said = reading.read_file(str(tmp_path / name))

    assert not said.ok
    assert "does not open credentials" in said.detail
    assert "hunter2" not in said.text


def test_nothing_under_the_claude_directory_is_opened() -> None:
    """Where the account token and the peer keys live. The pattern is the directory rather than the
    filenames, because a text file beside them is not worth getting the pattern slightly wrong."""
    assert reading.is_a_credential(pathlib.Path.home() / ".claude" / "notes.md")
    assert reading.is_a_credential(pathlib.Path.home() / ".claude" / "sessions" / "a.key")
    assert not reading.is_a_credential(pathlib.Path.home() / "notes.md")


async def test_the_permission_for_one_is_never_even_written(desk: Store) -> None:
    """Two checks for one rule. This one keeps the row out of the table, so "which files may this
    console open" never has a wrong answer in it; the reader's holds even if a row appeared by
    another route."""
    from urllib.parse import urlencode

    from tests.unit.test_kept_bench import _post

    status, _ = await _post(
        "/cards/file/read",
        urlencode({"path": "/home/dev/api/.env"}).encode(),
        b"application/x-www-form-urlencoded",
    )

    assert status == 400
    assert await desk.readable() == []


# --- and what it does unlock -------------------------------------------------------------------------
def test_a_file_reads_as_text(tmp_path: pathlib.Path) -> None:
    (tmp_path / "notes.md").write_text("the release goes out on Friday\n")

    said = reading.read_file(str(tmp_path / "notes.md"))

    assert said.ok
    assert "Friday" in said.text
    assert said.left_out == 0


def test_something_that_is_not_text_is_refused(tmp_path: pathlib.Path) -> None:
    """A picture in a prompt is bytes nobody can read and a bill nobody agreed to."""
    (tmp_path / "a.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0d")

    said = reading.read_file(str(tmp_path / "a.png"))

    assert not said.ok
    assert "not a text file" in said.detail


def test_a_long_file_is_cut_and_says_how_much(tmp_path: pathlib.Path) -> None:
    """Quietly answering about the first half of a file is worse than saying so."""
    (tmp_path / "big.txt").write_text("x" * (reading.MOST_CHARS + 500))

    said = reading.read_file(str(tmp_path / "big.txt"))

    assert len(said.text) == reading.MOST_CHARS
    assert said.left_out == 500


def test_a_file_that_is_not_there_says_so(tmp_path: pathlib.Path) -> None:
    said = reading.read_file(str(tmp_path / "gone.txt"))

    assert not said.ok
    assert "not a file on this machine" in said.detail


def test_a_relative_path_is_refused() -> None:
    assert not reading.read_file("notes.md").ok


# --- the boundary in the question path ----------------------------------------------------------------
async def test_a_file_nobody_allowed_says_nothing(desk: Store, tmp_path: pathlib.Path) -> None:
    """The default is silence, and the permission is a row somebody made. Not a check that can be
    forgotten into an accident."""
    (tmp_path / "notes.md").write_text("the release goes out on Friday\n")

    assert await blocks.notes(desk, [f"file:{tmp_path / 'notes.md'}"]) == []


async def test_a_file_somebody_allowed_goes_with_the_question(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    (tmp_path / "notes.md").write_text("the release goes out on Friday\n")
    await desk.let_it_be_read(str(tmp_path / "notes.md"))

    (line,) = await blocks.notes(desk, [f"file:{tmp_path / 'notes.md'}"])

    assert "Friday" in line


async def test_what_it_says_is_scrubbed_on_the_way_out(desk: Store, tmp_path: pathlib.Path) -> None:
    """They asked for the file to be read, not for the token on line 40 of it to be sent."""
    (tmp_path / "notes.md").write_text("deploy key ghp_R7SzQ1aBcDeFgHiJkLmNoPqRsTuVwXyZ0123\n")
    await desk.let_it_be_read(str(tmp_path / "notes.md"))

    (line,) = await blocks.notes(desk, [f"file:{tmp_path / 'notes.md'}"])

    assert "ghp_R7SzQ1aBcDeFgHiJkLmNoPqRsTuVwXyZ0123" not in line


# --- the card ------------------------------------------------------------------------------------------
async def test_the_card_of_a_file_nobody_allowed_offers_the_choice(
    desk: Store, tmp_path: pathlib.Path
) -> None:
    (tmp_path / "notes.md").write_text("the release goes out on Friday\n")

    body = bytes((await routes.card("file", str(tmp_path / "notes.md"))).body).decode()

    assert "Nothing in this file has been read" in body
    assert "Let it be" in body
    assert "Friday" not in body


async def test_the_control_says_what_pressing_it_does(desk: Store, tmp_path: pathlib.Path) -> None:
    """A permission somebody clicked without reading is not a permission."""
    (tmp_path / "notes.md").write_text("x\n")

    body = bytes((await routes.card("file", str(tmp_path / "notes.md"))).body).decode()

    assert "lets this console open" in body
    assert "a credential is refused whatever you press" in body


async def test_an_allowed_card_shows_what_it_will_send(desk: Store, tmp_path: pathlib.Path) -> None:
    (tmp_path / "notes.md").write_text("the release goes out on Friday\n")
    await desk.let_it_be_read(str(tmp_path / "notes.md"))

    body = bytes((await routes.card("file", str(tmp_path / "notes.md"))).body).decode()

    assert "Friday" in body
    assert "may be read" in body


def test_a_file_can_be_dragged_out_of_the_folder_it_is_in() -> None:
    """Otherwise there is no way to get one onto the bench, and the permission has nothing to be
    granted on."""
    markup = FOLDER_CARD.read_text(encoding="utf-8")

    assert "data-kind=\"{{ 'folder' if one.is_folder else 'file' }}\"" in markup
    assert 'data-id="{{ folder.path }}/{{ one.name }}"' in markup


def test_the_permission_is_a_button_and_not_a_side_effect() -> None:
    """ "Отдельное разрешение, которое человек даёт явно, а не побочный эффект просьбы." The
    request that uses the contents does not grant this and cannot."""
    markup = FILE_CARD.read_text(encoding="utf-8")

    assert 'action="/cards/file/read"' in markup
    assert "<button" in markup
