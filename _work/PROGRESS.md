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
| 7 | A5 dev isolated by default | done | #24 | tests/unit/test_make_run.py (3, read from `make -n`); live: `make run` served 200 on :9055 with data in ./.desk-data, live DB mtime unchanged | also fixed: `make share` never passed its AGENT_DESK_SHARE_* vars (a VAR= prefix went to `unset`) |
| 8 | A2 prod instance | done | `a2-prod-instance`; tags desk-20260927-rc1 → desk-20260927 | installed at ~/opt/agent-desk-prod, unit agent-desk.service enabled; http 200; `kill <MainPID>` → back under a new pid in <7 s; `touch` in the dev checkout → same pid; test_prod_unit.py (no --reload, Restart=always); `prod-update` exercised rc1 → final tag | Restart=always instead of on-failure (D11) |
| 9 | A6 AGENT_DESK_HANDS | done | #25 | tests/unit/test_hands.py (8; mutations: no check in dispatch.start → fails, loops ungated → fails); suite runs with HANDS=on in conftest so the agent paths keep their tests | kicking buttons left drawn: kicking is deleted in S1 |
| 10 | S2 appraise switch | done | #26 | test_hands: default off; lifespan with appraise off runs only `later`, with on runs appraising too | |
| 11 | B1 jobs blocked/stopped | done | #28, prod on desk-20260927.2 (live board: 203 waiting · 202 questions) | fixtures blocked/stopped/running (+working re-recorded) from ~/.claude/jobs, structure only; test_jobs + test_autostart (stopped ≠ done; mutation fails 2); real ~/.claude/jobs: 203 waiting, 202 questions, 0 unknown states; isolated gate 2772 passed | `blocked` has `needs`, not `block.questions` — questions counted from `block.questions` when present, else 1 per `needs` |
| 12 | B2 fixtures on current CLI | done | #29 | registry_entry + transcript re-aligned to 2.1.283 key sets (25 live transcripts), RECORDED_CLI_VERSION=2.1.283; test_transcript_shape (5; drift disabled → 3 fail); banner: fixture as recorded → no notice, 9.9.999 → notice; live board: 3 rows, 0 notices | stream_json.jsonl needs a real `claude -p` → H5; registry `waitingFor` found → H6 |
| 13 | B7 `claude agents --json` | done | #30 | fixture claude_agents.json (2.1.283, 3 interactive + 1 background); test_agents (9: parse, listed, fallback notice, each failure named, answer cached — 5 redraws → 1 process); live board: 3 rows with the CLI's statuses, 0 notices | kept 10 s (`agents_poll_seconds`): one call is ~0.21 s and ~190 MB; a CLI row with no registry file is counted, not invented |
| 14 | B4 go to session | done | #31; prod on desk-20260927.3 (migration 080 ran, `agent-desk.db.bak-v79` made first — A4 backup proven live) | short id to `claude attach` (the documented form; id == sessionId prefix for all 203 jobs); DISPLAY etc. from `systemctl --user show-environment` when the service has none (only those five vars, test); migration 080 `reason` + `POST /terminals/{press}/why` (closed list of 4, else 400); /standing: "sent somebody to a terminal N times: …, K not said"; go buttons on the waiting-jobs list | a real click on the owner's screen was not made (it would open a window and attach to a live job) — first thing to try on the board day |
| 15 | B3 open PRs on board | done (token → human H7) | #32 | web/pulls.py: own read-only loop (5 min, independent of hands), `AGENT_DESK_PULL_REPOS` + token by name; fixture github_pulls.json (real response); test_pulls_on_board (7); full live response parsed → "5 open, oldest 17 days" = `gh pr list` 5 | the existing reader ran only inside autostart (off since A6) |
| 16 | B6 quadratic select | done | `b6-ideas-select` | one shared `<datalist>` instead of a `<select>` of every idea in every card; link route ignores an id that names no idea (was impossible with a select); test_idea_list_size: 100→200 ideas grows < 2.2× (old template fails it), 0.71 MB at 200 (research: 3.7 MB) | the backlog's "< 400 KB at 200" is NOT met: ~3.5 KB per card remain (5 forms, 9 options); getting there means lazy-loading the per-card forms — not done |
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
