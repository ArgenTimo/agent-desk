"""Waiting for a thing to become true, rather than for a length of time.

"Полный прогон падал восемью тестами, пока рядом работала живая консоль, и проходил начисто, когда
её останавливали."

Both halves of that sentence are the problem. A test that fails because something else was running
is a test people learn to ignore, and a red run they have learned to ignore is a gate that has
stopped working — which is worse than not having one, because it still costs the time.

Every test in this suite that waits is waiting for a *fact*: a block has settled, a loop has come
round, a task has been noticed. None of them is waiting for a duration. Written as
`await asyncio.sleep(0.3)` the duration is a guess about how fast the machine is, and this project
is normally worked on with several agents and a live console on the same laptop — so the guess is
wrong exactly when the suite matters most.

Written as a condition it is right on both: instant on an idle machine, patient on a busy one, and
when it genuinely does not happen it says what it was waiting for instead of failing three lines
later on an assertion about something else.

The ceiling is generous on purpose. It is not a performance budget — nothing here asserts that the
console is fast — it is the point at which "it has not happened" stops being "not yet".
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

# How long a thing gets to become true before not-yet becomes never. Deliberately far longer than
# any of these take on an idle machine: the number is the difference between "slow" and "broken",
# and a suite that draws that line at half a second draws it in the wrong place.
GIVE_UP_AFTER = 20.0

# How often to look. Short enough that a test on an idle machine is not measurably slower for
# waiting this way, long enough not to spin.
LOOK_EVERY = 0.01


async def until(
    what: Callable[[], Awaitable[bool]] | Callable[[], bool],
    why: str,
    *,
    seconds: float = GIVE_UP_AFTER,
) -> None:
    """Wait until `what` is true, then return. Raise naming `why` if it never becomes true.

    `why` is the sentence in the failure, so write it as the thing that was supposed to happen —
    "both questions are running", not "timeout".

    **Pass an async predicate, not a lambda that compares its coroutine.**
    `lambda: some_async(x) != y` compares a coroutine object to a value, which is `True` every
    time — so the wait returns immediately and the test fails later, on an assertion about
    something that had not happened yet. That is a real `bool`, so nothing here can catch it;
    write `lambda: _is_true(x)` with an `async def _is_true` instead. Cost an hour once already.
    """
    for _ in range(int(seconds / LOOK_EVERY)):
        said = what()
        if isinstance(said, Awaitable):
            said = await said
        # A predicate that returns anything but a boolean is a predicate that was not called
        # properly, and the commonest way to write one is `lambda: some_async(x) != y` — which
        # compares a coroutine to a value and is therefore always true. That does not fail here; it
        # fails three lines later, in the test, as an assertion about something that had not
        # happened yet. So it is caught where it was written.
        if not isinstance(said, bool):
            raise TypeError(
                f"waiting for {why!r} was given {type(said).__name__} rather than a bool — an "
                "async predicate has to be awaited, so pass the function itself rather than a "
                "lambda that compares its coroutine"
            )
        if said:
            return
        await asyncio.sleep(LOOK_EVERY)
    raise AssertionError(f"waited {seconds:.0f}s and never saw: {why}")
