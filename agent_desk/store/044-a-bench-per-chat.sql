-- A workbench for each chat, rather than one workbench for all of them.
--
-- "Исследование, харнесс, прототип и пайплайн не помещаются на одну поверхность — а в сценариях
-- они существуют одновременно. Нужны именованные верстаки и переключение между ними, ровно как
-- между чатами сейчас. Тогда же решается и то, что сегодня разговор и схема лежат вперемешку:
-- разговор — это один верстак, схема — другой."
--
-- ## The assumption, stated
--
-- The idea asks for named workbenches switched between the way chats are switched between now.
-- Chats are already named — automatically, from what they turned out to be about — already
-- switched between, already closed and reopened, and the page already says out loud that "the
-- workbench belongs to the chat". So the smallest thing that gives the investigation, the harness,
-- the prototype and the pipeline a surface each is to make that sentence true, rather than to
-- build a second row of tabs above the first with its own naming, its own closing and its own
-- ordering.
--
-- What that gives up is a bench that outlives one conversation, or two benches inside one. Nobody
-- has asked for either, and neither is blocked by this: a bench that wants to be its own thing
-- gets a row of its own on the day somebody wants one.
--
-- ## It also fixes something that was broken between 040 and here
--
-- 040 gave the console one stored bench while the page had always cleared the surface on a chat
-- switch. Those two together meant switching chats *destroyed* the stored bench: the page cleared
-- itself, wrote the empty surface down, and the other chat's cards were gone for good. Scoping the
-- rows is what makes the clear a switch instead of a deletion.
--
-- ## Why the column is not null and defaults to the empty string
--
-- The bench of a page open before anybody has said anything belongs to no chat yet — there is no
-- thread id until the first message creates one. That is a real state and it gets a real key,
-- rather than NULL, so that every query is one shape and "which bench" is never a three-way
-- question.

ALTER TABLE bench_card ADD COLUMN thread_id TEXT NOT NULL DEFAULT '';
ALTER TABLE bench_was  ADD COLUMN thread_id TEXT NOT NULL DEFAULT '';

CREATE INDEX bench_card_thread ON bench_card (thread_id);
CREATE INDEX bench_was_thread ON bench_was (thread_id, at);

-- The one bench that existed before this has to become one of the many, or it becomes none of
-- them: left under the empty key it belongs to no chat, is shown on no surface, and somebody
-- upgrading loses the cards they had laid out — silently, which is the worst version of it.
--
-- Nothing records which chat it was for, because until now there was only one. So this is a
-- placement, not a recovered fact, and it is stated as one: the newest chat still open is where
-- the person was last, and it is the only answer that puts their cards back in front of them.
-- Being wrong costs a bench on the wrong tab, which is visible and fixable by dragging; being
-- silent costs the bench.
--
-- The undo history is not moved with it. A step is a whole surface as it stood, and replaying one
-- onto a bench it was not taken from would restore cards to a chat that never had them. The cards
-- move; the way back to before they were arranged does not, and that is the honest trade.
UPDATE bench_card
   SET thread_id = (SELECT id FROM thread WHERE closed_at IS NULL ORDER BY created_at DESC LIMIT 1)
 WHERE thread_id = ''
   AND EXISTS (SELECT 1 FROM thread WHERE closed_at IS NULL);

DELETE FROM bench_was WHERE thread_id = '';
