"""What a review column is waiting on, and the two claims that have to stay apart (docs/adr/0011).

Half of this file is about the quotations — that a sentence is attached to the ticket somebody
wrote it on, and only to that one. The other half is about failure: an unreadable board and an
unavailable model both have to leave what an earlier pass knew exactly where it is, because a
column nobody could read must never look like a column with nothing in it.
"""

from __future__ import annotations

import ast
import json
import pathlib
from collections.abc import AsyncIterator, Iterator

import pytest
from agent_desk import secrets as kept
from agent_desk.config import Settings
from agent_desk.store.repo import Store
from agent_desk.tracker import jira, review
from agent_desk.web import blockers, routes

KEY = "origin:acme/api"
SITE = "https://acme.atlassian.net"
BOARD = f"{SITE}/browse/DUCK"


@pytest.fixture
async def desk(tmp_path: pathlib.Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "agent-desk.db")
    await store.open()
    yield store
    await store.close()


@pytest.fixture
def nowhere(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine with no secret of its own, so a test never reads the developer's."""
    monkeypatch.setattr(kept, "settings", Settings(data_dir=tmp_path / "data"))


def _issue(key: str, status: str, comments: list[str], summary: str = "the export") -> dict:
    """One issue in the shape the v3 search returns it, comments as Atlassian documents."""
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status},
            "comment": {
                "comments": [
                    {
                        "body": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": said}],
                                }
                            ],
                        }
                    }
                    for said in comments
                ]
            },
        },
    }


def _body(*issues: dict) -> bytes:
    return json.dumps({"issues": list(issues)}).encode()


# --- what the column says (agent_desk/tracker/jira.py) ------------------------------------------


@pytest.mark.unit
def test_the_query_asks_for_a_category_rather_than_a_status_name() -> None:
    """A status name is a thing a team renames, and a JQL naming one the board does not have
    fails the whole request. The three categories are fixed in every Jira (docs/adr/0011)."""
    where = jira.Destination(site=SITE, project_key="DUCK", token_env="DUCK_TOKEN")

    jql = jira.review_jql(where)

    assert 'project = "DUCK"' in jql
    assert 'statusCategory = "In Progress"' in jql
    assert "In Review" not in jql, "the column is matched by name in Python, not in the query"


@pytest.mark.unit
def test_only_the_review_column_is_read_and_only_the_sentences_that_say_something_is_stuck() -> (
    None
):
    raw = _body(
        _issue("DUCK-1", "In Review", ["Blocked on the staging credential.", "Nice work."]),
        _issue("DUCK-2", "In Progress", ["blocked on the same credential"]),
    )

    found = jira.read_mentions(raw)

    assert [(one.key, one.said) for one in found] == [
        ("DUCK-1", "Blocked on the staging credential.")
    ]


@pytest.mark.unit
def test_a_comment_that_says_it_twice_is_two_things_to_wait_for() -> None:
    """A ticket says it once; a comment thread says it eleven times in eleven places, and each is
    something somebody separately has to do."""
    raw = _body(
        _issue(
            "DUCK-3",
            "Code Review",
            ["Blocked on the vendor SDK. Also waiting on a decision about the schema."],
        )
    )

    found = jira.read_mentions(raw)

    assert [one.said for one in found] == [
        "Blocked on the vendor SDK.",
        "Also waiting on a decision about the schema.",
    ]
    assert {one.key for one in found} == {"DUCK-3"}


@pytest.mark.unit
def test_the_column_is_recognised_in_the_words_a_team_actually_uses() -> None:
    for named in ("In Review", "in review", "Review", "на ревью"):
        raw = _body(_issue("DUCK-9", named, ["blocked on infra"]))
        assert jira.read_mentions(raw), f"{named} is a review column"


@pytest.mark.unit
def test_a_shape_it_does_not_recognise_yields_nothing_rather_than_raising() -> None:
    """This is on the path of a loop (docs/adr/0004, one layer down)."""
    for unusable in (b"", b"null", b'{"issues": "not a list"}', b'{"nothing": 1}'):
        assert jira.read_mentions(unusable) == ()

    # And the parts of an issue that can each be missing on their own.
    assert jira.read_mentions(_body({"key": "DUCK-1"})) == ()
    assert jira.read_mentions(_body({"fields": {"status": {"name": "In Review"}}})) == ()
    assert (
        jira.read_mentions(
            _body({"key": "DUCK-1", "fields": {"status": {"name": "In Review"}, "comment": None}})
        )
        == ()
    )


@pytest.mark.unit
def test_reading_a_review_column_never_writes_to_it() -> None:
    """0010's refusal, unchanged: no transition, no comment, no assignment."""
    tree = ast.parse(pathlib.Path(jira.__file__).read_text())
    reader = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "read_review"
    )
    called = {
        node.func.id
        for node in ast.walk(reader)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "_get" in called
    assert "_post" not in called
    assert "file_issue" not in called


@pytest.mark.unit
def test_the_read_asks_for_the_three_fields_it_uses_and_carries_the_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: dict[str, str] = {}

    def fake_get(url: str, authorization: str) -> tuple[int, bytes]:
        asked["url"] = url
        asked["authorization"] = authorization
        return 200, _body(_issue("DUCK-1", "In Review", ["blocked on the staging credential"]))

    monkeypatch.setattr(jira, "_get", fake_get)
    monkeypatch.setenv("DUCK_TOKEN", "someone@example.com:a-token")
    where = jira.destination_of(BOARD, "DUCK_TOKEN")
    assert where is not None

    read = jira.read_review(where)

    assert read.ok
    assert [one.key for one in read.mentions] == ["DUCK-1"]
    assert "rest/api/3/search" in asked["url"]
    assert "comment" in asked["url"] and "status" in asked["url"]
    assert asked["authorization"].startswith("Basic ")


@pytest.mark.unit
def test_an_unset_variable_is_a_refusal_that_names_both_places_a_token_can_come_from(
    nowhere: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DUCK_TOKEN", raising=False)
    where = jira.destination_of(BOARD, "DUCK_TOKEN")
    assert where is not None

    read = jira.read_review(where)

    assert not read.ok
    assert "DUCK_TOKEN is not set" in read.detail
    assert "type the token on the" in read.detail
    assert read.mentions == ()


@pytest.mark.unit
def test_a_board_that_refuses_or_answers_nonsense_is_unread_rather_than_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DUCK_TOKEN", "a-token")
    where = jira.destination_of(BOARD, "DUCK_TOKEN")
    assert where is not None

    monkeypatch.setattr(
        jira, "_get", lambda url, auth: (403, json.dumps({"errorMessages": ["no"]}).encode())
    )
    refused = jira.read_review(where)
    assert not refused.ok and "403" in refused.detail

    monkeypatch.setattr(jira, "_get", lambda url, auth: (200, b'{"total": 0}'))
    strange = jira.read_review(where)
    assert not strange.ok and "does not understand" in strange.detail

    def unreachable(url: str, auth: str) -> tuple[int, bytes]:
        raise TimeoutError("slow")

    monkeypatch.setattr(jira, "_get", unreachable)
    away = jira.read_review(where)
    assert not away.ok and "could not reach" in away.detail
    assert SITE in away.detail and "a-token" not in away.detail


# --- what a model is allowed to say about it (agent_desk/tracker/review.py) ---------------------

MENTIONS = (
    jira.Mention(key="DUCK-1", summary="the export", said="Blocked on the staging credential."),
    jira.Mention(key="DUCK-4", summary="the import", said="waiting on the same credential"),
    jira.Mention(key="DUCK-7", summary="the report", said="blocked until somebody picks a format"),
)

REPLY = """## Rotate the staging credential
tickets: DUCK-1, DUCK-4
1. Open the vault entry for staging and issue a new token.
2. Put it in the deploy secret and restart the two workers.

## Decide the report format
tickets: DUCK-7
1. Take the decision in Thursday's sync: CSV or XLSX.
"""


@pytest.mark.unit
def test_a_group_carries_the_sentences_it_was_made_from_with_their_keys() -> None:
    """The quotes are rebuilt from the mentions rather than read out of the reply, so what a card
    quotes is always what a person actually wrote (CLAUDE.md, rule five)."""
    first, second = review.read_groups(REPLY, MENTIONS)

    assert first.title == "Rotate the staging credential"
    assert first.keys == ("DUCK-1", "DUCK-4")
    assert first.said.splitlines() == [
        "DUCK-1 · Blocked on the staging credential.",
        "DUCK-4 · waiting on the same credential",
    ]
    assert first.tutorial.splitlines() == [
        "Open the vault entry for staging and issue a new token.",
        "Put it in the deploy secret and restart the two workers.",
    ]
    assert second.keys == ("DUCK-7",)
    assert first.id == "rotate-the-staging-credential"


@pytest.mark.unit
def test_a_key_the_model_was_not_shown_is_dropped_and_a_group_with_no_real_key_goes_whole() -> None:
    """The one thing this must never do is attach a sentence to a ticket that did not say it."""
    invented = """## Rotate the staging credential
tickets: DUCK-1, DUCK-999
1. Issue a new token.

## Ask the vendor about the SDK
tickets: OTHER-3
1. Email them.
"""

    (only,) = review.read_groups(invented, MENTIONS)

    assert only.keys == ("DUCK-1",)
    assert "DUCK-999" not in only.said


@pytest.mark.unit
def test_a_group_without_a_title_a_ticket_or_a_step_is_not_a_card_anybody_can_act_on() -> None:
    assert review.read_groups("no headings here at all", MENTIONS) == ()
    assert review.read_groups("## Rotate it\n1. do the thing", MENTIONS) == ()
    assert review.read_groups("## Rotate it\ntickets: DUCK-1", MENTIONS) == ()
    assert review.read_groups("## ...\ntickets: DUCK-1\n1. do it", MENTIONS) == ()


@pytest.mark.unit
def test_two_groups_the_model_named_the_same_way_are_one_card() -> None:
    """They would otherwise collide on the primary key they share (039-review-blockers.sql)."""
    twice = "## Rotate it\ntickets: DUCK-1\n1. first\n\n## Rotate it\ntickets: DUCK-4\n1. second"

    (only,) = review.read_groups(twice, MENTIONS)

    assert only.tutorial == "first"


@pytest.mark.unit
async def test_a_model_that_cannot_be_asked_says_nothing_rather_than_something_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`None` and `()` are different answers: the first means this pass knows nothing and must
    not overwrite what an earlier one knew."""

    async def broken(prompt: str) -> AsyncIterator[str]:
        raise review.AnswerFailed("no model here")
        yield ""  # pragma: no cover

    monkeypatch.setattr(review, "stream_answer", broken)
    assert await review.group(MENTIONS) is None

    async def rambling(prompt: str) -> AsyncIterator[str]:
        yield "I had a look and I think the credential is the problem."

    monkeypatch.setattr(review, "stream_answer", rambling)
    assert await review.group(MENTIONS) is None


@pytest.mark.unit
async def test_the_prompt_shows_the_sentences_with_their_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []

    async def fake(prompt: str) -> AsyncIterator[str]:
        asked.append(prompt)
        yield REPLY

    monkeypatch.setattr(review, "stream_answer", fake)

    made = await review.group(MENTIONS)

    assert made is not None and len(made) == 2
    assert "DUCK-1 (the export): Blocked on the staging credential." in asked[0]
    assert "Do not invent one" in asked[0]


# --- the pass, end to end -----------------------------------------------------------------------


@pytest.fixture
def a_board(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[jira.Reviewed]]:
    """One answer from the board, swappable per test. The transport is never reached."""
    answers = [jira.Reviewed(True, mentions=MENTIONS)]
    monkeypatch.setattr(jira, "read_review", lambda where: answers[0])
    yield answers


async def _linked(desk: Store) -> None:
    await desk.set_link(repo_key=KEY, name="jira", url=BOARD, token_env="DUCK_TOKEN")


def _answers(monkeypatch: pytest.MonkeyPatch, reply: str) -> None:
    async def fake(prompt: str) -> AsyncIterator[str]:
        yield reply

    monkeypatch.setattr(review, "stream_answer", fake)


@pytest.mark.unit
async def test_a_pass_writes_one_card_per_problem_and_the_column_shows_it(
    desk: Store, a_board: list[jira.Reviewed], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _linked(desk)
    _answers(monkeypatch, REPLY)

    assert await review.sweep(desk) == 2

    found = [one for one in await blockers.blockers(desk) if one.kind == "review"]
    assert [one.what for one in found] == [
        "Rotate the staging credential",
        "Decide the report format",
    ] or [one.what for one in found] == [
        "Decide the report format",
        "Rotate the staging credential",
    ]
    card = next(one for one in found if one.what == "Rotate the staging credential")
    # The quotations, with the key of the ticket each was written on.
    assert "DUCK-1 · Blocked on the staging credential." in card.why
    assert "grouped by a model" in card.why
    # The steps, kept apart from them.
    assert card.tutorial.startswith("Open the vault entry")
    # And the tickets it was read from, which are genuinely waiting on it: they are in review and
    # their own comments say so.
    assert [held.id for held in card.holding_up] == ["DUCK-1", "DUCK-4"]
    assert card.repo_key == KEY


@pytest.mark.unit
async def test_the_column_renders_the_steps_apart_from_the_sentences_they_were_read_from(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole of what makes this card allowed on the board: a person can see which half is a
    quotation and which is a reading (CLAUDE.md, rule five)."""
    monkeypatch.setattr(routes, "store", desk)
    await desk.replace_review_blockers(
        KEY,
        [
            (
                "rotate-the-staging-credential",
                "Rotate the staging credential",
                "Open the vault entry for staging.",
                "DUCK-1 · Blocked on the staging credential.",
            )
        ],
    )

    column = await routes.render_blockers()

    assert "Rotate the staging credential" in column
    assert "DUCK-1 · Blocked on the staging credential." in column
    assert "Open the vault entry for staging." in column
    # Labelled as a reading rather than left to pass for one of the quotations above it.
    assert "not observed" in column
    # And it counts against the project, once, however many comments named it.
    assert (await routes.board_work())[KEY]["stuck"] == 1


@pytest.mark.unit
async def test_a_project_with_no_board_is_never_asked_about(
    desk: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A link with no token variable is a link, not a destination — the rule everywhere here."""
    await desk.set_link(repo_key=KEY, name="jira", url=BOARD, token_env=None)

    def never(where: object) -> None:  # pragma: no cover — reaching it is the failure
        raise AssertionError("a board was read for a project that named no credential")

    monkeypatch.setattr(jira, "read_review", never)

    assert await review.sweep(desk) == 0


@pytest.mark.unit
async def test_a_board_nobody_could_read_leaves_what_the_last_pass_knew(
    desk: Store, a_board: list[jira.Reviewed], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable column must never look like an empty one (docs/adr/0010, and 0011)."""
    await _linked(desk)
    _answers(monkeypatch, REPLY)
    await review.sweep(desk)

    a_board[0] = jira.Reviewed(False, detail="DUCK_TOKEN is not set")
    assert await review.sweep(desk) == 0

    assert len(await desk.review_blockers()) == 2


@pytest.mark.unit
async def test_a_model_that_could_not_be_reached_leaves_them_too(
    desk: Store, a_board: list[jira.Reviewed], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _linked(desk)
    _answers(monkeypatch, REPLY)
    await review.sweep(desk)

    async def broken(prompt: str) -> AsyncIterator[str]:
        raise review.AnswerFailed("no model here")
        yield ""  # pragma: no cover

    monkeypatch.setattr(review, "stream_answer", broken)
    assert await review.sweep(desk) == 0

    assert len(await desk.review_blockers()) == 2


@pytest.mark.unit
async def test_a_column_that_was_read_and_says_nothing_is_the_one_thing_that_clears_them(
    desk: Store, a_board: list[jira.Reviewed], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A comment somebody answered stops being a blocker without anybody telling this console."""
    await _linked(desk)
    _answers(monkeypatch, REPLY)
    await review.sweep(desk)

    a_board[0] = jira.Reviewed(True, mentions=())
    assert await review.sweep(desk) == 0

    assert await desk.review_blockers() == []
    assert [one for one in await blockers.blockers(desk) if one.kind == "review"] == []


@pytest.mark.unit
async def test_a_second_pass_replaces_this_project_and_leaves_another_alone(desk: Store) -> None:
    other = "origin:acme/other"
    await desk.replace_review_blockers(KEY, [("a", "Rotate it", "1. do it", "DUCK-1 · blocked")])
    await desk.replace_review_blockers(other, [("a", "Ask them", "1. ask", "OTHER-1 · blocked")])

    await desk.replace_review_blockers(KEY, [("b", "Pick a format", "1. pick", "DUCK-7 · stuck")])

    assert {(one.repo_key, one.id) for one in await desk.review_blockers()} == {
        (KEY, "b"),
        (other, "a"),
    }


@pytest.mark.unit
async def test_a_grouped_blocker_narrows_to_its_project_like_every_other(desk: Store) -> None:
    await desk.replace_review_blockers(KEY, [("a", "Rotate it", "1. do it", "DUCK-1 · blocked")])

    assert [one.kind for one in await blockers.blockers(desk, only=KEY)] == ["review"]
    assert await blockers.blockers(desk, only="origin:acme/other") == []
