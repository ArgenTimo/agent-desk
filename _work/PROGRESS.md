# Progress — autonomous plan of 2026-09-27

Source of task IDs: `_research/06_backlog.md`, `_research/01_repo_cleanup_plan.md`,
`../_integration/07_dogfooding_safety.md`. On a fresh session: read this file and continue with the
first row that is not done / blocked / human.

Isolated test run until A1 was merged (and still used for every gate here):
`scratchpad/iso-gate.sh <dir> gate` — fake `claude` first on PATH logging each call,
`AGENT_DESK_DATA_DIR`/`AGENT_DESK_CLAUDE_HOME` on a temp dir, and a before/after snapshot of
`~/.local/share/agent-desk/*` (mtime, size) and the number of `~/.claude/jobs` entries.

| # | Task | Status | Branch / PR | How verified | Notes |
|---|---|---|---|---|---|
| 0 | Backup | done | local branch `backup/2026-09-27-before-autonomy` (ce3f286) | `git log -1` on it; bundles in `~/agent-desk-salvage/` | not pushed: repo is public, see DECISIONS D1 |
| 1 | U0 salvage | done | — | `~/agent-desk-salvage/README.md` lists 4 dirty worktrees, stash, 9e3de5d test; DB copied via sqlite backup API from a `mode=ro` connection, `integrity_check` ok, schema_version max 79 | |
| 2 | A1 hermetic suite | done | #14 (73e2d4c) | isolated `make gate`: 2708 passed, 0 fake-claude calls, live DB mtime/size and jobs count unchanged; mutation (drop DATA_DIR redirect) fails the new test | |
| 3 | Job cleanup (07 §7) | human | `_work/proposed/rm-test-jobs.sh` | snapshot `~/agent-desk-salvage/agents-2026-09-27.json` + `jobs-2026-09-27/`; 203 blocked = 199 test ("бери в работу") + 1 explore + 3 other | `claude rm` fails: background service not running (supervisor dead since 09-16) → HUMAN_TODO H2 |
| 4 | U1 PR/branch/worktree cleanup | done (branch deletion → human H3) | merged #20 (with the fuller ../agent-desk-shift patch), #18, #13, #16 (migration renumbered 079); closed #15 #8 #21 #3 #17 #12 #11 #5 | open PRs 18→5 (#19 #10 #9 #7 #6, all frozen agent-launch/engine work); worktrees 32→3; `uniq -d` over migration numbers empty; each merge after an isolated green gate | local branch/stash deletion refused by auto-mode classifier → H3 |
| 5 | A4 safe migrations | done | #22 (ed9b93f) | 9 tests in test_migrate.py (mutations: name check off → 2 fail; checks outside txn → 1 fails); isolated gate 2741 passed; live DB backed up (`~/agent-desk-salvage/agent-desk.db.before-a4`), restore verified, reconciled (D8); a copy opens with main, nothing pending | |
| 6 | A3 flock + recover=False | done | #23 | tests/unit/test_one_process.py 5 tests (mutations: MCP recover=True → fails; lifespan without lock → fails); live smoke: two `python -m agent_desk` on one temp data_dir — second exits with `AlreadyRunning … pid N …`, first still serves 200 | uvicorn exits 0 on a refused startup |
| 7 | A5 dev isolated by default | done | `a5-dev-isolated` | tests/unit/test_make_run.py (3, read from `make -n`); live: `make run` served 200 on :9055 with data in ./.desk-data, live DB mtime unchanged | also fixed: `make share` never passed its AGENT_DESK_SHARE_* vars (a VAR= prefix went to `unset`) |
| 8 | A2 prod instance | todo | | | |
| 9 | A6 AGENT_DESK_HANDS | todo | | | |
| 10 | S2 appraise switch | todo | | | |
| 11 | B1 jobs blocked/stopped | todo | | | |
| 12 | B2 fixtures on current CLI | todo | | | |
| 13 | B7 `claude agents --json` | todo | | | |
| 14 | B4 go to session | todo | | | |
| 15 | B3 open PRs on board | todo | | | |
| 16 | B6 quadratic select | todo | | | |
| 17 | B5 MCP | todo | | | |
| 18 | S1 remove explore/land, kicking, close | todo | | | |
| 19 | filing tracker='git' | todo | | | |
| 20 | README | todo | | | |
| 21 | D6 aiworker_workspace_roots | todo | | | |
| 22 | web/board.py | todo | | | |
| 23 | project profile | todo | | | |
| 24 | ADR draft external executors | todo | | | |
| 25 | human: CI, CODEOWNERS, protection | todo | | | |

## Baseline numbers (before)

- open PRs: 18; worktrees (PycharmProjects repo): 32; blocked jobs: 203 (research), to re-count in task 3
- tests: 2704 passed on origin/main 974a306 (research); lines of code: see final report
