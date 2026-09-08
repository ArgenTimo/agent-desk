"""One message read into its parts, and the credential taken out of it
(01M1X8DA7FJ16SH96MMS5VY0VV).

"Я просто условно кидаю в ввод ссылку на пустой реп и токен + разные ссылки/файлы/референсы —
прошу сделать прототип на основе. Секрет — отдельная история: его нельзя ни записать в базу, ни
отдать в промпт. Значит, из сообщения он должен уходить в переменную окружения или в хранилище
ключей, а в истории сообщения оставаться след «здесь был токен»."

A block's input goes into the SQLite file, onto the page, into the thread history that travels with
the next question, and into the prompt. A credential in it is in all four places, and deleting the
message afterwards does not take it out of the two that already left.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator

import pytest
from agent_desk import pasted
from agent_desk import secrets as kept
from agent_desk.store.repo import Store
from agent_desk.web import blocks, routes

pytestmark = pytest.mark.unit

TOKEN = "ghp_R7SzQ1aBcDeFgHiJkLmNoPqRsTuVwXyZ0123"


@pytest.fixture
async def desk(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    monkeypatch.setattr(routes, "store", store)
    monkeypatch.setenv("HOME", str(tmp_path))
    yield store
    await store.close()


# --- the parts ------------------------------------------------------------------------------------
def test_a_repository_a_link_and_a_file_are_told_apart() -> None:
    found = pasted.read(
        "make a prototype in https://github.com/acme/proto.git "
        "using https://example.com/spec and /home/dev/notes.md"
    )

    assert found.repos == ("https://github.com/acme/proto.git",)
    assert found.links == ("https://example.com/spec",)
    assert found.files == ("/home/dev/notes.md",)


def test_only_a_repository_host_is_a_repository() -> None:
    """A documentation page has `owner/name` in its path too, and calling it a repository would
    start a clone of somebody's blog."""
    found = pasted.read("read https://docs.example.com/getting/started")

    assert found.repos == ()
    assert found.links == ("https://docs.example.com/getting/started",)


def test_a_message_with_nothing_in_it_reads_as_itself() -> None:
    found = pasted.read("what is going on")

    assert found.said == "what is going on"
    assert (found.repos, found.links, found.files, found.token) == ((), (), (), "")


# --- the credential -------------------------------------------------------------------------------
def test_a_token_is_taken_out_of_the_words() -> None:
    found = pasted.read(f"here is the token {TOKEN} for it")

    assert TOKEN not in found.said
    assert found.token == TOKEN


def test_what_is_left_says_a_token_was_here() -> None:
    """A message that silently lost a word is a message somebody re-pastes the token into, and the
    second paste is the one that gets stored."""
    found = pasted.read(f"token {TOKEN}")

    assert "a token was here" in found.said
    assert found.kept_as in found.said


def test_it_is_named_after_the_repository_it_arrived_with() -> None:
    """Which is what it is for and what somebody will look for it under — the rule the project
    links already follow."""
    found = pasted.read(f"https://github.com/acme/proto.git {TOKEN}")

    assert found.kept_as == "TOKEN_ACME_PROTO"


def test_a_token_with_no_repository_still_gets_a_name() -> None:
    assert pasted.read(f"the token is {TOKEN}").kept_as == "PASTED_TOKEN"


def test_what_a_secret_looks_like_is_asked_of_the_one_list() -> None:
    """A second list would be a second answer to "is this a secret", and the shapes it did not have
    would be the ones that got through."""
    source = (pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "pasted.py").read_text(
        encoding="utf-8"
    )

    assert "from agent_desk.store.redact import patterns" in source
    assert "ghp_" not in source, "a shape written out here is a shape that will drift"


def test_the_token_is_removed_before_the_links_are_found() -> None:
    """A link matcher run over the raw text returns a URL with the token in its query string, and
    that URL is then in the parts as well."""
    found = pasted.read(f"https://example.com/x?token={TOKEN}")

    assert all(TOKEN not in one for one in found.links)


def test_it_needs_no_model_call() -> None:
    """A message holding a credential must not wait on a model to have it removed — least of all
    one that would be given the credential in order to decide."""
    source = (pathlib.Path(__file__).resolve().parents[2] / "agent_desk" / "pasted.py").read_text(
        encoding="utf-8"
    )

    assert "stream_answer" not in source
    assert "async def" not in source


# --- and what the console does with it ---------------------------------------------------------------
async def test_the_block_never_holds_the_token(
    desk: Store, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(blocks.runs, "start", lambda *a, **k: None)
    monkeypatch.setattr(kept, "keep", lambda name, value: None)

    block = await blocks.submit(
        desk,
        f"make a prototype in https://github.com/acme/proto.git with {TOKEN}",
        [],
    )

    again = await desk.block(block.id)
    assert again is not None
    assert TOKEN not in again.input
    assert "a token was here" in again.input


async def test_the_token_goes_to_the_store_built_for_it(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One file, this machine, mode 0600, never read back to a screen — and not the database the
    shared view is served out of."""
    monkeypatch.setattr(blocks.runs, "start", lambda *a, **k: None)
    given: dict[str, str] = {}
    monkeypatch.setattr(kept, "keep", lambda name, value: given.__setitem__(name, value))

    await blocks.submit(desk, f"https://github.com/acme/proto.git {TOKEN}", [])

    assert given == {"TOKEN_ACME_PROTO": TOKEN}


async def test_the_block_says_what_the_message_held(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Somebody who pasted four things and got an answer about two needs to see which two, and a
    secret that was moved has to say where it went."""
    monkeypatch.setattr(blocks.runs, "start", lambda *a, **k: None)
    monkeypatch.setattr(kept, "keep", lambda name, value: None)

    block = await blocks.submit(
        desk,
        f"https://github.com/acme/proto.git {TOKEN} see https://example.com/spec "
        "and /home/dev/notes.md",
        [],
    )

    again = await desk.block(block.id)
    assert again is not None
    said = again.context or ""
    assert "repository · https://github.com/acme/proto.git" in said
    assert "link · https://example.com/spec" in said
    assert "file · /home/dev/notes.md" in said
    assert "kept as TOKEN_ACME_PROTO" in said
    assert TOKEN not in said


async def test_an_ordinary_message_is_untouched(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(blocks.runs, "start", lambda *a, **k: None)

    block = await blocks.submit(desk, "what is going on", [])

    again = await desk.block(block.id)
    assert again is not None and again.input == "what is going on"
