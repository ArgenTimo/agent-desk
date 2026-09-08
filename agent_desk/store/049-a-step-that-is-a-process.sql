-- A step whose work is another drawing.
--
-- "Схема из тридцати шагов нечитаема. Нужен шаг, внутри которого лежит другая схема, и который
-- снаружи выглядит одной карточкой — иначе конструктор упирается в потолок примерно на десяти
-- шагах, а все интересные процессы длиннее."
--
-- ## No sixth role
--
-- adr/0011 closed the list of roles at five and gave the reason: a role is what a card *is* in a
-- process, and five names with a meaning each is a language while six is a list. A step that runs
-- another drawing is still an Action — something to do — and what makes it different is not what
-- it is but what it does the work with. So it is a field on an Action (`runs`, the name of a saved
-- process) rather than a role of its own, and every part of the console that reasons about roles
-- carries on unchanged.
--
-- ## Two columns, and why the run is where they go
--
-- A nested run is an ordinary run: same steps, same states, same engine, same undo. What it needs
-- on top is to know where to report back to, which is a run and a step — `inside_run` and
-- `inside_step`. The parent's step then settles from its child exactly the way an ordinary step
-- settles from its task, which is why this needed no new state anywhere: `going` already means
-- "started, waiting for the thing it started".
--
-- Nullable, and null is the ordinary case: almost every run is somebody pressing run on a bench.

ALTER TABLE run ADD COLUMN inside_run  TEXT;
ALTER TABLE run ADD COLUMN inside_step TEXT;

CREATE INDEX run_inside ON run (inside_run, inside_step);
