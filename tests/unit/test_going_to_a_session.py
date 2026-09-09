""" "Go to it", and it goes (01M1VAZ5PT5YHPDZ6BR780HM0E).

«Кнопка "перейти" должна открывать сессию на экране устройства… Страница не может открыть терминал
сама, и кнопка, которая делает вид что может, была бы хуже — но настоящее "перейти" возможно.»

The page cannot, and never could. The console is a process on the same machine, started by the same
person, and it can.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from agent_desk import opening
from agent_desk.web import routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]


def test_the_command_is_a_list_and_a_shell_never_sees_it() -> None:
    """A session id reaching a shell is a session id in a command line somebody else wrote."""
    said = opening.argv("0f8cf805-a691-4599-9565-4211709833c0")

    assert said is not None
    assert said[-3:] == ["claude", "attach", "0f8cf805-a691-4599-9565-4211709833c0"]
    assert all(isinstance(one, str) for one in said)


def test_the_distributions_own_terminal_comes_first() -> None:
    """`x-terminal-emulator` is the machine's own answer to "the terminal", and going round it
    would open a window somebody did not choose."""
    assert opening.TERMINALS[0][0] == "x-terminal-emulator"


def test_a_machine_with_no_terminal_gets_no_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opening.shutil, "which", lambda name: None)

    assert opening.a_terminal() is None
    assert opening.argv("abc") is None


def test_a_session_with_no_id_is_not_opened() -> None:
    assert opening.argv("   ") is None


def test_it_says_what_it_could_not_do_rather_than_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The button falls back to what it always did — copying the exact line — and the sentence is
    what tells somebody why."""
    monkeypatch.setattr(opening.shutil, "which", lambda name: None)

    done = opening.open_it("abc")

    assert not done.ok
    assert "copied instead" in done.detail


def test_a_terminal_that_will_not_start_is_an_answer_and_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This is reached from a route that has to render something either way."""
    monkeypatch.setattr(opening.shutil, "which", lambda name: "/usr/bin/" + name)

    def refuses(*args: object, **kwargs: object) -> object:
        raise OSError("no")

    monkeypatch.setattr(opening.subprocess, "Popen", refuses)

    done = opening.open_it("abc")

    assert not done.ok
    assert "would not open" in done.detail


def test_it_starts_the_session_in_the_terminal_it_found(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[list[str]] = []

    monkeypatch.setattr(opening.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        opening.subprocess, "Popen", lambda command, **rest: started.append(command)
    )

    done = opening.open_it("abc")

    assert done.ok
    assert started[0][0] == "x-terminal-emulator"
    assert started[0][-1] == "abc"


def test_the_child_is_not_left_holding_this_console_s_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal that inherited them would keep them open for as long as somebody left the window
    up, and it is a session of its own rather than a child of this one."""
    kept: dict[str, object] = {}

    monkeypatch.setattr(opening.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(opening.subprocess, "Popen", lambda command, **rest: kept.update(rest))

    opening.open_it("abc")

    assert kept["start_new_session"] is True
    assert kept["stdin"] == opening.subprocess.DEVNULL


async def test_the_route_answers_either_way(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(opening.shutil, "which", lambda name: None)

    back = json.loads((await routes.open_a_session("abc")).body)

    assert back["opened"] is False
    assert back["why"]


def test_the_button_asks_the_console_and_keeps_the_line_to_paste() -> None:
    """On a machine with no terminal this console knows how to open, copying the exact line is what
    it falls back to — and that is the half that was always real."""
    board = (HERE / "agent_desk" / "web" / "templates" / "_board.html").read_text(encoding="utf-8")
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))

    assert "data-open=" in board
    assert "data-copy=" in board
    assert "/open`, { method: 'POST' }" in code
    assert "copyTheLine" in code


def test_the_copy_handler_does_not_fire_as_well() -> None:
    """Both attributes are on one button, and two handlers would copy the line every time somebody
    opened a terminal successfully."""
    script = (HERE / "agent_desk" / "web" / "static" / "console.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("//"))

    assert "button.hasAttribute('data-open')" in code
