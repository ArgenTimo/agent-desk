"""Pull requests waiting on somebody, read as blockers (agent_desk/tracker/github.py).

A pull request open for three days waiting on a review is a thing that has stopped, it is stopped
on a *person*, and it is invisible from a board that only watches sessions.
"""

from __future__ import annotations

import ast
import json
import pathlib
import urllib.error

import pytest
from agent_desk.tracker import github


@pytest.mark.unit
def test_both_shapes_of_a_github_link_name_the_same_repository() -> None:
    for said in (
        "https://github.com/ArgenTimo/agent-desk",
        "https://github.com/ArgenTimo/agent-desk/",
        "https://github.com/ArgenTimo/agent-desk.git",
        "git@github.com:ArgenTimo/agent-desk.git",
    ):
        assert github.repo_of(said) == "ArgenTimo/agent-desk", said

    for not_one in ("https://gitlab.com/a/b", "https://github.com/", "", "nonsense"):
        assert github.repo_of(not_one) == "", not_one


@pytest.mark.unit
def test_what_a_pull_request_is_waiting_on_is_what_it_says() -> None:
    """ "Waiting for review" is a fact when a reviewer was asked and has not answered. "Probably
    needs a look" would be a guess, and a column of guesses is one nobody reads."""
    assert "draft" in github.waiting_for({"draft": True})
    assert "review from biba" in github.waiting_for({"requested_reviewers": [{"login": "biba"}]})
    assert "conflict" in github.waiting_for({"mergeable_state": "dirty"})
    assert "merged" in github.waiting_for({})


@pytest.mark.unit
def test_a_response_it_does_not_recognise_yields_nothing_rather_than_raising() -> None:
    for raw in (b"", b"not json", b"{}", b'{"message": "Bad credentials"}', b"[null, 3]"):
        assert github.read_pulls(raw) == (), raw

    # A pull request with no number or no title is not half a pull request.
    assert github.read_pulls(json.dumps([{"title": "x"}]).encode()) == ()


@pytest.mark.unit
def test_two_hundred_open_pull_requests_are_a_different_problem() -> None:
    many = [{"number": n, "title": f"one {n}"} for n in range(200)]

    assert len(github.read_pulls(json.dumps(many).encode())) == github.MOST_PULLS


@pytest.mark.unit
def test_a_link_with_no_credential_is_a_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same rule the Jira reader follows: a credential nobody named is one nobody decided to
    use here."""
    monkeypatch.delenv("GH_TOKEN", raising=False)

    read = github.open_pulls("owner/name", "GH_TOKEN")

    assert not read.ok
    assert "GH_TOKEN is not set" in read.detail


@pytest.mark.unit
def test_the_request_carries_the_credential_and_asks_only_for_open_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, str] = {}

    def fake_get(url: str, authorization: str) -> tuple[int, bytes]:
        asked["url"] = url
        asked["authorization"] = authorization
        return 200, json.dumps(
            [
                {
                    "number": 12,
                    "title": "rewrite the parser",
                    "html_url": "https://github.com/owner/name/pull/12",
                    "requested_reviewers": [{"login": "biba"}],
                }
            ]
        ).encode()

    monkeypatch.setattr(github, "_get", fake_get)
    monkeypatch.setenv("GH_TOKEN", "a-token")

    read = github.open_pulls("owner/name", "GH_TOKEN")

    assert read.ok
    (pull,) = read.pulls
    assert pull.key == "#12"
    assert "review from biba" in pull.waiting_for
    assert "state=open" in asked["url"]
    assert asked["authorization"].startswith("Bearer ")


@pytest.mark.unit
def test_a_network_failure_never_quotes_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(url: str, authorization: str) -> tuple[int, bytes]:
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(github, "_get", refuse)
    monkeypatch.setenv("GH_TOKEN", "a-token")

    read = github.open_pulls("owner/name", "GH_TOKEN")

    assert not read.ok
    assert "a-token" not in read.detail
    assert "URLError" in read.detail


@pytest.mark.unit
def test_nothing_here_writes_to_a_repository() -> None:
    """No review, no comment, no merge, no label. The one door out of this program is
    docs/adr/0005's, and it goes to a tracker rather than here."""
    tree = ast.parse(pathlib.Path(github.__file__).read_text())
    methods = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "POST" not in methods and "PATCH" not in methods and "PUT" not in methods
    assert "GET" in methods


@pytest.mark.unit
def test_a_refusal_is_a_status_and_a_body_rather_than_an_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reached from a loop that has to carry on either way, like every other reader here."""
    import io
    import urllib.request

    def refuse(request: object, timeout: float = 0) -> object:
        raise urllib.error.HTTPError(
            "https://api.github.com/x", 401, "Unauthorized", {}, io.BytesIO(b'{"message":"bad"}')
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    status, raw = github._get("https://api.github.com/repos/o/n/pulls", "Bearer x")
    assert status == 401
    assert b"bad" in raw

    monkeypatch.setenv("GH_TOKEN", "a-token")
    read = github.open_pulls("owner/name", "GH_TOKEN")
    assert not read.ok
    assert "401" in read.detail


@pytest.mark.unit
def test_a_successful_read_returns_what_github_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request

    class Answer:
        status = 200

        def read(self) -> bytes:
            return b"[]"

        def __enter__(self) -> Answer:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(urllib.request, "urlopen", lambda request, timeout=0: Answer())

    assert github._get("https://api.github.com/x", "Bearer x") == (200, b"[]")

    # An empty list is a repository with nothing open, which is a fine answer.
    monkeypatch.setenv("GH_TOKEN", "a-token")
    read = github.open_pulls("owner/name", "GH_TOKEN")
    assert read.ok and read.pulls == ()


@pytest.mark.unit
def test_a_body_that_is_not_a_list_is_not_an_empty_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable answer must never look like a repository with nothing waiting."""
    monkeypatch.setattr(github, "_get", lambda url, auth: (200, b'{"message":"Not Found"}'))
    monkeypatch.setenv("GH_TOKEN", "a-token")

    read = github.open_pulls("owner/name", "GH_TOKEN")

    assert not read.ok
    assert "does not understand" in read.detail


@pytest.mark.unit
def test_a_link_that_is_not_a_repository_is_refused_before_anything_is_asked() -> None:
    read = github.open_pulls("", "GH_TOKEN")

    assert not read.ok
    assert "does not name a GitHub repository" in read.detail
