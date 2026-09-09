-- What "put these two together" means on this workbench.
--
-- "В алхимии вода + огонь = пар. В работе две карточки + вопрос = новый документ. Правило — это то,
-- что превращает пару в третье, и оно должно быть видимым и сменяемым: одна и та же пара в разных
-- правилах даёт разное."
--
-- The gesture (060) had the rule written into the page as a constant, which made every combine on
-- every bench ask the same thing. That is fine for the first one somebody tries and wrong for the
-- second: two cards put together to draft a document and the same two put together to find what
-- they disagree about are one gesture and two questions.
--
-- ## Per bench, not per pair
--
-- "Промпт-шаблон, привязанный к верстаку, а не к паре — иначе на каждое соединение придётся
-- объяснять заново." A rule asked for once and then used twenty times is a rule; a rule asked for
-- at each combine is a text field with extra steps, and the gesture stops being a gesture.
--
-- ## Why this is not a column on `thread`
--
-- The same reason `began` (050) is not one: a chat is a subject somebody is talking about, and
-- this is a fact about the arrangement in front of them. They are one-to-one today because a bench
-- belongs to a chat, and writing it here keeps the two ideas separable on the day they are not.
--
-- An absent row is the default rule, not an empty one. The default lives in
-- `agent_desk/combining.py`, in one place, so a bench that has never been told anything and a
-- bench somebody reset both ask exactly what the console documents.

CREATE TABLE combining (
    thread_id TEXT PRIMARY KEY,
    said      TEXT NOT NULL,
    at        INTEGER NOT NULL
);
