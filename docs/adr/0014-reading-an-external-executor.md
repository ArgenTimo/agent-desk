# ADR 0014 — reading an external executor the way `~/.claude/` is read

**Status:** proposed · 2026-09-27

## Context

agent-desk watches the Claude Code sessions on this laptop by reading what the CLI writes to disk
and what `claude agents --json` prints ([0004](0004-the-transcript-format-is-not-a-contract.md),
`agent_desk/observe/`). A second kind of worker is coming: ai-worker, which runs its own agents in
containers against Jira tickets, has its own console of runs, and its own approval surface in
Jira and Slack. Its sessions never appear in `~/.claude/` — they run as another OS user, in
another home, often on another machine.

The owner wants one board that says what is waiting on a person, across both. The pull is to give
that board buttons for the second worker too — proceed, hold, retry — because the button is
right there. That would make agent-desk a third control surface for ai-worker, beside ai-worker's
own console and its Jira comments, and ai-worker's own specification forbids a second approval
surface (`docs/15-web-console.md` there). It would also repeat what
[0013](0013-back-to-observing.md) just undid here: a console that grew hands.

Nothing in this ADR is built. It fixes the shape before the first line of code, so that the code
does not choose it.

## Decision

**An external executor is read like `~/.claude/` is read: from its published interface, never
written to, and never controlled from here.**

1. **Read its API, not its database.** The only source is the executor's own read API (for
   ai-worker, the `aiw-read/0` subset of `/api/v1` described in the integration notes). No shared
   database, no reading its log files, no scraping its console. One reader module in
   `agent_desk/observe/` (`observe/aiworker.py` when it exists), with recorded fixtures and a
   version check exactly like the CLI parsers: when the contract moves, one module fails loudly.
2. **Statuses as the executor wrote them, plus when they were read.** A run's `status` is shown
   verbatim (`waiting_for_input`, `running`, …) — this program does not map it onto its own words,
   because a mapping is a second opinion about someone else's state. Every value carries `seen_at`,
   and the board says "read N s ago". An executor that cannot be reached is shown as unreachable
   since `seen_at`, never as idle and never as empty (CLAUDE.md, rule five).
3. **No control buttons.** The board links to the executor's own console and to the ticket; it
   does not proceed, hold, retry, cancel, approve or comment. "Waiting for an answer in Jira" is
   shown as a fact with a link to the comment, and answering stays in Jira. `AGENT_DESK_HANDS`
   (A6 in the backlog, [0013](0013-back-to-observing.md)) does not change this: hands are for this machine's own sessions.
4. **The token is named, never held.** A project link names an environment variable
   (`token_env`, e.g. `AGENT_DESK_AIW_TOKEN`) whose value is a read-only token issued by the
   executor; the value lives in the environment or `secrets.json` (`agent_desk/secrets.py`) and
   never in the database, a log, a fixture or a notice.
5. **The executor's own workspaces stay off this board.** Sessions whose working directory is
   under an executor's workspace roots (`aiworker_workspace_roots`) are not shown as local
   sessions and their transcripts are not opened: they are the executor's, and they are reported
   through its API or not at all.
6. **One loop, observed.** Reading happens in one polling task in the console's lifespan, inside
   the TaskGroup, with every tick's exception caught and logged — a failing executor must not take
   the console down with it.

## Consequences

- The board can say "ai-worker: 2 runs waiting for input, oldest 40 min — read 12 s ago" and link
  to both places where the answer is given. It cannot answer, and that is the design.
- The executor can change its internals freely; only its read contract is a dependency, and that
  dependency is recorded and version-checked.
- ai-worker must never be given write access to the files that render its own status here
  (`observe/aiworker.py`, its tests and fixtures): a worker editing the code that reports on it is
  the recursion the integration notes warn about. CODEOWNERS covers them when they exist.
- Anything that looks like a control ("retry this run") is a change to this ADR first, argued on
  its own, not a template edit.

## Not decided here

The polling interval and the event feed (`/api/v1/events`) versus plain polling; whether the lane
is its own column or rows inside projects; how a run maps to a project on this board when the
repository is the same. Those are the first implementation's questions, answered with data.
