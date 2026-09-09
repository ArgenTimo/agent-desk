"""A repository somebody pointed at, brought onto this machine and queued
(01M1X8DA7AMSKJWW0JR4081F59).

"…заканчивая полноценным проектом (с его отслеживанием и прочим). То есть результат — не текст, а
новый репозиторий, инстанс, набор задач и место на доске проектов. Всё, что консоль уже умеет
наблюдать, но заведённое ею самой."

From the clone onwards nothing about it is special: a session runs in a directory, the board shows
it, the blockers watch it, the budget bounds it. What had to be built is the clone, the place it
goes, and the discipline around both.
"""

from __future__ import annotations

import pathlib
import subprocess
from collections.abc import AsyncIterator
from typing import ClassVar

import pytest
from agent_desk import starting
from agent_desk.config import Settings
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit

HERE = pathlib.Path(__file__).resolve().parents[2]
BLOCKS_HTML = HERE / "agent_desk" / "web" / "templates" / "_blocks.html"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    yield store
    await store.close()


def _a_repository(at: pathlib.Path) -> str:
    """A real repository, locally, so the clone is a real clone and not a mock of one."""
    at.mkdir(parents=True)
    subprocess.run(  # noqa: S603 - a fixed argv and a temporary directory
        ["git", "init", "--bare", "-q", str(at)],  # noqa: S607 - git is on PATH or the suite cannot run
        check=True,
    )
    return f"file://{at}"


# --- where it goes -----------------------------------------------------------------------------
def test_a_clone_lands_in_the_one_tree_this_program_writes_to() -> None:
    """`config.py` says `data_dir` is that tree and CLAUDE.md's second rule says never into an
    observed repository. A checkout this console made is not one it reads over somebody's
    shoulder."""
    where = starting.where(pathlib.Path("/data"), "https://github.com/acme/proto.git")

    assert where == pathlib.Path("/data/projects/proto")


def test_it_is_named_after_the_repository() -> None:
    """Somebody is going to open a terminal in it eventually, and a path with a counter in it is
    one they cannot read."""
    assert starting.where(pathlib.Path("/data"), "https://github.com/acme/proto").name == "proto"


def test_the_key_is_the_shape_every_other_project_has() -> None:
    """So a project this console started sorts and groups with the rest instead of forming a
    second kind of thing."""
    assert starting.key_and_name("https://github.com/acme/proto.git") == (
        "origin:acme/proto",
        "proto",
    )


def test_something_that_is_not_a_repository_address_is_refused() -> None:
    assert starting.key_and_name("nonsense") == ("", "")
    assert not starting.clone("nonsense", pathlib.Path("/tmp/nope")).ok


def test_an_address_needing_a_key_nobody_typed_is_refused(tmp_path: pathlib.Path) -> None:
    """ssh and git:// would hang on a prompt this console cannot answer."""
    made = starting.clone("ssh://git@github.com/acme/proto.git", tmp_path / "x")

    assert not made.ok
    assert "https" in made.detail


# --- the clone ------------------------------------------------------------------------------------
def test_it_brings_the_repository_onto_this_machine(tmp_path: pathlib.Path) -> None:
    url = _a_repository(tmp_path / "origin.git")

    made = starting.clone(url, tmp_path / "here" / "proto")

    assert made.ok, made.detail
    assert (tmp_path / "here" / "proto" / ".git").is_dir()
    assert made.cwd == str(tmp_path / "here" / "proto")


def test_a_directory_that_is_already_there_is_not_touched(tmp_path: pathlib.Path) -> None:
    """Clobbering a checkout somebody has work in is the one failure this cannot be allowed to
    have."""
    url = _a_repository(tmp_path / "origin.git")
    (tmp_path / "here").mkdir()
    (tmp_path / "here" / "mine.txt").write_text("work in progress\n")

    made = starting.clone(url, tmp_path / "here")

    assert not made.ok
    assert "already here" in made.detail
    assert (tmp_path / "here" / "mine.txt").read_text() == "work in progress\n"


def test_a_repository_that_is_not_there_says_what_git_said(tmp_path: pathlib.Path) -> None:
    made = starting.clone(f"file://{tmp_path / 'nothing.git'}", tmp_path / "here")

    assert not made.ok
    assert made.detail


def test_the_token_is_never_in_the_command() -> None:
    """`/proc/<pid>/cmdline` is world-readable. The helper's *shape* goes in argv and the secret
    goes in the environment, which is the same place every other secret this program handles goes."""
    source = (HERE / "agent_desk" / "starting.py").read_text(encoding="utf-8")

    assert "GIT_ACCESS_TOKEN" in source
    assert 'command += ["-c", f"credential.helper={_HELPER}"]' in source
    assert "token}@" not in source, "a credential in the URL is the same mistake in another shape"


def test_git_is_never_left_waiting_at_a_prompt() -> None:
    source = (HERE / "agent_desk" / "starting.py").read_text(encoding="utf-8")

    assert '"GIT_TERMINAL_PROMPT": "0"' in source


# --- what the first agent is told -------------------------------------------------------------------
def test_the_brief_is_what_the_person_said() -> None:
    said = starting.first_task("make me a prototype of the reader", "https://x/y")

    assert said.startswith("make me a prototype of the reader")
    assert "https://x/y" in said


def test_the_references_travel_with_it() -> None:
    said = starting.first_task("make it", "https://x/y", ("https://example.com/spec",))

    assert "https://example.com/spec" in said


def test_it_is_told_that_nothing_publishes_on_anybody_s_behalf() -> None:
    said = starting.first_task("make it", "https://x/y")

    assert "pushes, publishes or opens anything" in said


# --- and the discipline around it --------------------------------------------------------------------
async def test_pressing_it_clones_and_queues_and_starts_nothing(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two acts, and the second is a click. A route that cloned a repository *and* set something
    running would be the automatic queue docs/adr/0007 exists to refuse, twice."""
    url = _a_repository(tmp_path / "origin.git")
    monkeypatch.setattr(routes, "settings", Settings(data_dir=tmp_path / "own"))
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="make a prototype", thread_set_by="human"
    )
    await desk.set_block_repo(block.id, url)

    await routes.start_a_project(block.id, _a_request())

    (task,) = await desk.tasks()
    assert task.waiting, "it started something"
    assert task.cwd.startswith(str(tmp_path / "own"))
    assert "make a prototype" in task.instruction


async def test_a_message_with_no_repository_in_it_starts_nothing(desk: Store) -> None:
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="what is going on", thread_set_by="human"
    )

    answer = await routes.start_a_project(block.id, _a_request())

    assert answer.status_code == 404
    assert await desk.tasks() == []


async def test_a_clone_that_failed_queues_nothing(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Work queued in a directory that is not there is a task that fails when somebody presses it,
    which is a worse answer than the one the clone already had."""
    monkeypatch.setattr(routes, "settings", Settings(data_dir=tmp_path / "own"))
    thread = await desk.create_thread("a chat")
    block = await desk.create_block(
        thread_id=thread.id, kind="question", input="make it", thread_set_by="human"
    )
    await desk.set_block_repo(block.id, f"file://{tmp_path / 'nothing.git'}")

    await routes.start_a_project(block.id, _a_request())

    assert await desk.tasks() == []


async def test_the_address_is_kept_on_the_block_the_message_arrived_in(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(blocks.runs, "start", lambda *a, **k: None)

    block = await blocks.submit(desk, "make a prototype in https://github.com/acme/proto.git", [])

    again = await desk.block(block.id)
    assert again is not None
    assert again.from_repo == "https://github.com/acme/proto.git"


def test_the_console_offers_it_rather_than_doing_it() -> None:
    markup = BLOCKS_HTML.read_text(encoding="utf-8")

    assert "block.from_repo" in markup
    assert 'action="/blocks/{{ block.id }}/project"' in markup


def _a_request() -> object:
    class Empty:
        async def body(self) -> bytes:
            return b""

        headers: ClassVar[dict[str, str]] = {}

    return Empty()


# --- and the other end: a project that is only an address ---------------------------------------
def _a_form(**fields: str) -> object:
    body = "&".join(f"{name}={value}" for name, value in fields.items()).encode()

    class Filled:
        async def body(self) -> bytes:
            return body

        headers: ClassVar[dict[str, str]] = {"content-type": "application/x-www-form-urlencoded"}

    return Filled()


def test_a_second_instance_gets_the_path_rather_than_an_error(tmp_path: pathlib.Path) -> None:
    """`clone` refuses a directory that is already there, which is right for starting a project and
    wrong here: somebody making their second instance of a project is told "it is already here",
    and the answer to that is the path."""
    url = _a_repository(tmp_path / "origin.git")
    first = starting.checkout(tmp_path / "own", url)

    again = starting.checkout(tmp_path / "own", url)

    assert first.ok and again.ok, again.detail
    assert again.cwd == first.cwd
    assert "already" in again.detail


def test_a_directory_in_the_way_that_is_not_a_checkout_is_still_refused(
    tmp_path: pathlib.Path,
) -> None:
    """The one case where the two readings differ, and guessing would be starting an agent in
    somebody's stray folder."""
    url = _a_repository(tmp_path / "origin.git")
    starting.where(tmp_path / "own", url).mkdir(parents=True)

    made = starting.checkout(tmp_path / "own", url)

    assert not made.ok
    assert "not a checkout" in made.detail


async def test_making_an_instance_of_an_address_clones_it(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "При подключении проекта из гита необходим механизм клонирования при создании инстанса, а не
    просто фраза «that project has no checkout on this machine»." The address is there, the console
    knows what is missing, and the press is already the click adr/0006 asks for."""
    url = _a_repository(tmp_path / "origin.git")
    monkeypatch.setattr(routes, "settings", Settings(data_dir=tmp_path / "own"))
    started: list[str] = []
    monkeypatch.setattr(
        routes.dispatch,
        "start",
        lambda said, *, cwd, name: started.append(cwd) or routes.dispatch.Started(True, "a1"),
    )
    await desk.set_link(repo_key="origin:acme/origin", name="repository", url=url)

    await routes.new_instance(_a_form(key="origin%3Aacme%2Forigin", name="pat"))

    assert started, "nothing was started, and nothing was cloned"
    assert started[0].startswith(str(tmp_path / "own"))
    assert pathlib.Path(started[0], ".git").is_dir()


async def test_a_project_with_neither_a_checkout_nor_an_address_says_so(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal stays where it is the truth. What changed is that it now says which of the two
    things is missing, because "no checkout" on a project with an address was a dead end."""
    started: list[str] = []
    monkeypatch.setattr(
        routes.dispatch,
        "start",
        lambda said, *, cwd, name: started.append(cwd) or routes.dispatch.Started(True, "a1"),
    )

    answer = await routes.new_instance(_a_form(key="origin%3Aacme%2Fnothing", name="pat"))

    assert not started
    assert "no address to clone from" in answer.body.decode()
