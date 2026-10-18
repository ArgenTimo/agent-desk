# 01 · План уборки: ветки, PR, worktree

> Все данные сняты только чтением 2026-09-27: `gh pr list --state all`, `git for-each-ref`,
> `git cherry`, `git merge-tree --write-tree` (git 2.43), `git worktree list --porcelain`,
> `git -C <wt> status --porcelain`, `du -sh`. Ни один ref не сдвинут. Единственный побочный эффект:
> симуляция последовательного слияния создала через `commit-tree` объекты, на которые никто не
> ссылается. Их уберёт `git gc`.
> Живая сессия в этом репозитории одна, в основной копии. Перед удалением worktree это нужно
> перепроверить.

## 0. Главное

1. **В `origin/main` нет `tests/conftest.py`.**
   - Проверка: `git ls-tree origin/main tests/conftest.py` пусто; в снимке файла нет `[ФАКТ]`.
   - Пять веток добавляют свой вариант: #14, #17, #21, #6 и `message-carries-bench` без PR. Эти
     варианты конфликтуют между собой (add/add).
   - Пока ни один не слит, **каждый `make gate` в любой копии репозитория может запустить настоящего
     агента и мигрировать живую БД**. Гейт запускает в том числе Stop-хук `stop-verify.sh`
     `[ФАКТ: запуск, см. 04_dogfooding_gaps.md §G1]`.
   - **#14 сливается первым, до любой другой работы**, включая ребейзы: они тоже гоняют гейт.
2. **Дубликаты.**
   - #15 и #16 указывают на один и тот же HEAD `23d8caa`.
   - #8 патч-идентичен верхнему коммиту #7: `git patch-id --stable` даёт `833bcb8d` для обоих `[ФАКТ]`.
3. **Скрытый конфликт миграций.**
   - #15/#16 добавляют `078-when-a-card-last-changed.sql`, а в `main` уже есть
     `078-a-thing-drawn-from-the-project.sql`.
   - Раннер берёт номер из первых трёх символов имени (`agent_desk/store/repo.py:1052`), поэтому БД,
     уже стоящая на 78, пропустит один из файлов.
   - Git этого не покажет: имена файлов разные.
   - Ветка `worktree-mozhesh-…` так же сталкивается на номере `039`.
4. **Конкурирующие реализации одного и того же:**
   - «верстак доходит до агента»: #19, #21 и незакоммиченная работа в `typed-do-carries-bench`;
   - «project = имя копии»: #18 и #21;
   - «карточка изменилась, пока тебя не было»: #16 (с миграцией) и #17 (только на странице);
   - «htmx.process после swap»: #20, #21 и более полная незакоммиченная версия в `../agent-desk-shift`.
5. **Живая БД уже несёт следы этих веток.**
   - Её версия 78 — это `changed_at` из ветки `card-changed-at`, версия 79 — `sketch_card` из
     worktree `draw-what-the-project-is` `[ФАКТ: БД schema_version]`.
   - Уборку нужно делать вместе с починкой таблицы версий, см. `04_dogfooding_gaps.md` §R2.

## 1. Открытые PR (18) и решение по каждому

| PR | ветка | суть | черновик | конфликт с `origin/main` | решение |
|---|---|---|---|---|---|
| #14 | suite-starts-no-agent | `conftest`: `AGENT_DESK_CLAUDE_BIN` → несуществующее имя | да | нет | **Слить первым** и добавить перенаправление `data_dir`/`claude_home` (§R-изоляция). Опционально взять тест `tests/unit/test_no_test_starts_an_agent.py` из `9e3de5d`. |
| #20 | board-swap-htmx | `htmx.process` после swap тела карточки и списка идей | да | нет | **Слить** squash-ем (внутри коммит `wip`). Сначала сравнить с патчем из `agent-desk-shift`, он полнее. |
| #18 | task-names-its-project | задача сообщает агенту свой проект (`where_it_works`) | да | нет | **Слить** (лучше, чем часть #21). |
| #19 | carries-the-bench | сообщение запускает агента вместе с верстаком | да | нет | **Слить** или отложить: это функция запуска агентов, которую предлагается заморозить (02). Если слить, то ради корректности, а не ради развития. |
| #12 | land-main-checkout | `land` ищет worktree в основной копии | да | нет | Слить (исправление к замораживаемой функции, дёшево). |
| #11 | worktree-beri-v-rabotu-4 | Land выбирает worktree с номером от CLI | да | нет | Слить вместе с #7 или отложить с ним. |
| #9 → #10 | session-dispatch-context → dispatch-names-the-session | брифинг агента, запущенного из отказа | да | нет | Слить по порядку или отложить: это слой запуска агентов. |
| #13 | go-ahead-names-nothing | голое «давай» спрашивает «что», а не запускает агента | да | нет (с #19 конфликт в `web/blocks.py`) | **Слить после #19** с ребейзом. Это исправление безопасности: убирает запуск наугад. |
| #7 | dispatch-own-worktree | одинаковые слова дважды не дают двух агентов в одном worktree | **нет** | **есть**: `dispatch.py`, `test_dispatch.py` | Ребейз от `origin/dispatch-own-worktree` (локальная ветка отстала). Отложить, если запуск агентов заморожен. |
| #16 | undo-before-078 | отметка «изменилась», миграция и исправление undo | да | текстово нет; **номер 078 занят** | Выбрать между #16 и #17. Если #16: переименовать файл в `079-…`, затем ребейз (с #20 конфликт в `console.js`). |
| #17 | card-last-changed | та же отметка, только на странице, плюс слабый `conftest` | да | нет (с #14 конфликт в `conftest`) | Закрыть в пользу #16 или выбросить коммит `32717b5` с `conftest`. |
| #5 | answer-pipe-break | обрыв pipe после ответа сохраняет ответ | да | **есть**: `answer/session.py` | Проверить, не покрыл ли это уже `f7f9999`. Если нет — ребейз и слить. |
| #6 | worktree-beri-v-rabotu (base #5) | сильный `conftest` (перенаправляет `claude_home`/`data_dir`), второй движок | да | **есть**: `session.py`, `telling.py`, `test_spending.py` | **Не сливать целиком.** Вручную перенести его `conftest` в #14, остальное отложить. |
| #15 | card-changed-at | = #16 | да | — | **Закрыть** как дубликат. |
| #8 | dispatch-main-checkout | = верхний коммит #7 | да | есть | **Закрыть** как дубликат. |
| #21 | suite-starts-no-agent-check | 4 темы в одном PR | да | нет, но конфликтует с #18, #20 | **Закрыть**: разложен по #14, #18, #19, #20. |
| #3 | worktree-make-one-thing-… | объединение панелей spread и compare (+360/−323) | да | **есть**: `routes.py`, `console.js`, `board.html` | **Закрыть**: отстал на 79 коммитов, это верстак (замораживается). |

Кластеры конфликтов (попарно, `merge-tree`):
- `tests/conftest.py`: #14, #17, #21, #6.
- `console.js`: #16, #20, #21, #3.
- `web/blocks.py`: #13 и #19.
- `dispatch.py`: #7 и #14 (тесты).

`web/routes.py` трогают 10 PR. Текстово чистое слияние не значит зелёное, поэтому **гейт после
каждого слияния**.

## 2. Ветки

**Слиты в `origin/main`, можно удалять (15):**
- `three-columns`, `do-carries-bench`, `typed-do-carries-bench` (сначала спасти diff),
  `draw-what-the-project-is` (diff не нужен, см. ниже), `drawing-no-checkout-says-so`,
  `experiment/insurance-site`, `ideas-from-the-pool`, `shift-idea-pool` (сначала спасти diff);
- `worktree-beri-v-rabotu-7`, `worktree-looking-for-something-…`,
  `worktree-make-one-thing-…-say-wha`, `worktree-probe`, `worktree-provedi-brifing-…`,
  `worktree-vizualiziruy-…`;
- `main` сдвигается fast-forward.

**Локальные копии чужих HEAD, удалять после решения по PR:**
- `board-swap-htmx-finish` (= #20);
- `dispatch-carries-bench` (= #17);
- `worktree-beri-v-rabotu-2/5/6` (= #7);
- `worktree-beri-v-rabotu-3` (= #8).

**Без PR:**

| ветка | что внутри | решение |
|---|---|---|
| `message-carries-bench` | один полезный коммит `9e3de5d` (тест «ни один тест не запускает агента») | спасти тест, затем удалить |
| `drawing-reads-the-project` (локальная) | «wip, superseded by bcc98b1» | архивировать тегом или удалить |
| `worktree-eta-ideya-…` (origin) | 1 коммит, отстаёт на 153 | архивировать тегом `archive/…`, удалить на origin |
| `worktree-mozhesh-…` (origin) | 1 коммит, отстаёт на 154, конфликт номера `039` | то же |

**Прочее:**
- **stash** `stash@{0}` на `card-changed-at`: сохранить патч, просмотреть, удалить.
- **Отставшие от upstream локальные ветки:** `dispatch-own-worktree` и `card-changed-at`. С них
  нельзя пушить с перезаписью, иначе потеряются удалённые коммиты `7e8008e`/`23d8caa`. Ребейзить
  нужно от `origin/<ветка>`.

## 3. Worktree (32, 863 МБ в `.claude/worktrees/`)

**С незакоммиченной работой (4):**

| worktree | что там | решение |
|---|---|---|
| `../agent-desk-shift` | более полная версия #20: общий тест на все `innerHTML`, лишний `htmx.process`, story 14 | **сохранить патч**, влить в #20 |
| `.claude/worktrees/typed-do-carries-bench` | третья реализация «верстак → агент» (+84/−14) | сохранить патч, решить против #19 |
| `.claude/worktrees/draw-what-the-project-is` | **переименование применённой миграции 078→079 в main** | **выбросить**: переименовывать применённую миграцию нельзя (докстринг `_migrations`) |
| `.claude/worktrees/beri-v-rabotu` | только неотслеживаемый `uv.lock`; **внутри вложенный worktree** `do-carries-bench` | сначала удалить вложенный, затем этот (`--force`) |

**Отсоединённые HEAD:**
- `~/.claude/jobs/a4ef218c/tmp/pr20` и `…/b107350a/tmp/pr18` — рабочие копии фоновых заданий Claude;
- `carries-bench-verify`, `task-names-its-project-verify`.

Все четыре удалить.

**Остальные 24 чистые.** Удалять их по мере закрытия или слияния соответствующих PR. Ветки,
которые есть на origin, при удалении worktree не теряются.

**Отдельно про 203 зависших фоновых задания** (`claude agents --json`: 203 записи
`kind=background, state=blocked`) `[ФАКТ: запуск]`. Это задания, которые CLI держит как «ждут
человека». Многие, вероятно, остались от тестов и `explore` `[ВЫВОД]`. Разбирать их через
`claude agents` / `claude rm <id>`, но только **после** просмотра, что каждое ждёт. Чем закончится
удаление, [ПРОБЕЛ]: не проверено, удаляет ли `rm` и связанный worktree в чужих репозиториях.

## 4. Порядок действий (выполняет владелец)

**Шаг 0. Спасти незакоммиченное** (до всего остального):
```bash
cd /home/skotwind/PycharmProjects/agent-desk && mkdir -p ~/agent-desk-salvage
git -C ../agent-desk-shift diff > ~/agent-desk-salvage/shift-htmx-broader.patch
cp ../agent-desk-shift/docs/stories/14-*.md ~/agent-desk-salvage/
git -C .claude/worktrees/typed-do-carries-bench diff > ~/agent-desk-salvage/typed-do-carries-bench.patch
git stash show -p 'stash@{0}' > ~/agent-desk-salvage/stash-card-changed-at.patch
git show 9e3de5d:tests/unit/test_no_test_starts_an_agent.py > ~/agent-desk-salvage/test_no_test_starts_an_agent.py
cp ~/.local/share/agent-desk/agent-desk.db ~/agent-desk-salvage/agent-desk.db.before-cleanup   # бэкап БД
```

**Шаг 1.** `git merge --ff-only origin/main` в основной копии. `_diagnostics/` и `_research/`
остаются неотслеживаемыми, конфликта нет.

**Шаг 2. Закрыть без риска для кода:** #15, #8, #21, #3 (`gh pr close N --comment "…"`). Решить
#16 против #17. Рекомендация — #16: сохранённый `changed_at` — это факт, а не вывод по памяти
страницы.

**Шаг 3. Слить по порядку.** Последовательность проверена симуляцией и проходит без конфликтов.
После каждого PR — `make gate`.
1. **#14**, плюс в той же ветке перенос `data_dir`-изоляции из #6 (см. 06_backlog A1).
2. #20 (squash; сначала влить патч из shift).
3. #18.
4. #19 (или отложить вместе со слоем запуска агентов).
5. #12 → #11 → #9 → #10 (то же условие).

Механика: `gh pr ready N && gh pr merge N --squash --delete-branch`. Для #10 после слияния #9
нужно `gh pr edit 10 --base main`.

**Шаг 4. С ребейзом, в новом worktree от `origin/<ветка>`:**
- #13 (после #19);
- #16 с переименованием миграции в `079`;
- #7;
- #5, затем остаток #6.

Обновление ветки PR после ребейза делает владелец вручную, перезаписью с проверкой lease. Хук
`pre-push-guard` запрещает это агентам намеренно.

**Шаг 5. Удалить worktree.** Сначала вложенный, затем чистые. `git worktree remove` без `--force`
откажется удалять грязный worktree, и это страховка. `--force` только для трёх спасённых на шаге 0.
В конце `git worktree prune -v`.

**Шаг 6. Удалить ветки:**
- `git branch -d …` для слитых;
- `git branch -D …` только для проверенных копий чужих HEAD;
- удалить на origin слитые `experiment/insurance-site`, `ideas-from-the-pool`, `worktree-looking-…`;
- архивные теги для двух веток без PR.

**Проверка после уборки:**
- `gh pr list` показывает ≤ 6 PR, каждый с решением;
- `git worktree list` показывает ≤ 5 записей;
- `ls agent_desk/store/[0-9][0-9][0-9]-*.sql | xargs -n1 basename | cut -c1-3 | sort | uniq -d` пусто (нет дубликатов номеров);
- `make gate` зелёный с пустым PATH-фейком `claude`, то есть ни одного вызова.

## 5. Риски

| Риск | Смягчение |
|---|---|
| Гейт во время ребейза запускает агента или мигрирует живую БД | #14 + изоляция `data_dir` до любых ребейзов |
| Дубликат номера миграции проходит мимо git | проверка `uniq -d` после каждого слияния; в перспективе таблица версий по имени (06_backlog A4) |
| Живая БД уже на «чужих» 78/79 | не чинить руками. Сначала A4 (проверка имени), затем одноразовая сверка: `changed_at` из #16 совпадёт, если #16 сольётся как `079` с тем же SQL; иначе нужна явная миграция-выравнивание |
| Удаление worktree, где работает сессия | перед шагом 5 проверить `claude agents --json`: cwd ни одной живой сессии не должен совпадать |
| 10 PR трогают `routes.py` | гейт после каждого слияния; не сливать пачкой |

Оценка: **6–8 часов** на всё, из них 2–3 часа на ребейзы #7, #13, #16, #5/#6 `[ДОПУЩЕНИЕ]`.
