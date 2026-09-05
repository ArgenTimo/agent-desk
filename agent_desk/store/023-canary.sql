-- The name an instance was told to sign its replies with, so the console can notice when it stops.
--
-- Asked for as "агент отслеживает канареек в сессии: канарейка — показатель того что контекст
-- целостный, выражен тем что агент пишет своё имя в начале каждого ответа; если имени нет, а
-- должно быть — завершаем задачу и открываем новую сессию".
--
-- The reason it works is that the instruction to sign is in the *first* message of the
-- conversation. A session whose window has rolled far enough to lose that message is a session
-- that has lost the rest of its brief too — the signature is the cheapest visible symptom of a
-- thing that is otherwise invisible until the work comes back wrong.
--
-- Only sessions this console started have one: nobody else's session was told to sign anything,
-- and an absent signature there means nothing at all.

CREATE TABLE IF NOT EXISTS canary (
    short_id   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    started_at INTEGER NOT NULL
);
