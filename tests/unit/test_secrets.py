"""What a secret typed into the console does, and what it never does."""

from __future__ import annotations

import json
import pathlib
import stat

import pytest
from agent_desk import secrets as kept
from agent_desk.config import Settings


@pytest.fixture
def here(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    monkeypatch.setattr(kept, "settings", Settings(data_dir=tmp_path / "data"))
    monkeypatch.delenv("DESK_TEST_TOKEN", raising=False)
    return tmp_path / "data"


@pytest.mark.unit
def test_a_secret_is_kept_on_this_machine_and_only_readable_by_its_owner(
    here: pathlib.Path,
) -> None:
    """docs/07-security.md: it is typed here, used here, and never leaves this machine.

    Not the store: the shared application serves a view out of that file, and nothing that answers
    a network request opens this one.
    """
    kept.keep("DESK_TEST_TOKEN", "a-real-looking-secret")

    assert kept.has("DESK_TEST_TOKEN") is True
    assert kept.get("DESK_TEST_TOKEN") == "a-real-looking-secret"

    on_disk = kept.path()
    assert on_disk.parent == here
    # Only this user, and stated rather than assumed: on a shared machine that is the whole of it.
    assert stat.S_IMODE(on_disk.stat().st_mode) == 0o600
    assert stat.S_IMODE(on_disk.parent.stat().st_mode) == 0o700
    assert json.loads(on_disk.read_text()) == {"DESK_TEST_TOKEN": "a-real-looking-secret"}


@pytest.mark.unit
def test_the_shell_wins_over_what_was_typed_months_ago(
    here: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator with a secret manager must not be quietly shadowed by a browser."""
    kept.keep("DESK_TEST_TOKEN", "typed-into-the-console")
    monkeypatch.setenv("DESK_TEST_TOKEN", "exported-in-the-shell")

    assert kept.get("DESK_TEST_TOKEN") == "exported-in-the-shell"
    assert kept.has("DESK_TEST_TOKEN") is True


@pytest.mark.unit
def test_forgetting_one_leaves_the_others_alone(here: pathlib.Path) -> None:
    kept.keep("DESK_ONE", "first")
    kept.keep("DESK_TWO", "second")

    kept.forget("DESK_ONE")

    assert kept.has("DESK_ONE") is False
    assert kept.get("DESK_TWO") == "second"
    assert kept.get("DESK_ONE") == ""


@pytest.mark.unit
def test_a_missing_or_broken_file_is_no_secrets_rather_than_a_crash(here: pathlib.Path) -> None:
    assert kept.has("DESK_TEST_TOKEN") is False
    assert kept.get("DESK_TEST_TOKEN") == ""

    here.mkdir(parents=True, exist_ok=True)
    kept.path().write_text("{ this is not json")
    assert kept.get("DESK_TEST_TOKEN") == ""

    # And writing over it repairs it rather than failing.
    kept.keep("DESK_TEST_TOKEN", "a-secret")
    assert kept.get("DESK_TEST_TOKEN") == "a-secret"


@pytest.mark.unit
def test_the_file_is_never_readable_by_anybody_else_even_for_a_moment(
    here: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Writing the file and then chmodding it leaves every secret in it world-readable for as
    long as that takes, and on a shared machine that window is the whole vulnerability.

    This asserts the mode at the moment the bytes are written, not afterwards.
    """
    seen: list[int] = []
    real_open = __import__("os").open

    def watch(path: object, flags: int, mode: int = 0o777, **rest: object) -> int:
        if str(path).endswith(".writing"):
            seen.append(mode)
        return real_open(path, flags, mode, **rest)  # type: ignore[arg-type]

    monkeypatch.setattr(kept.os, "open", watch)

    kept.keep("DESK_TEST_TOKEN", "a-real-looking-secret")

    assert seen == [0o600], "the file was created at some other permission first"
    assert stat.S_IMODE(kept.path().stat().st_mode) == 0o600
    # And nothing is left beside it for somebody to read later.
    assert not kept.path().with_suffix(".writing").exists()
