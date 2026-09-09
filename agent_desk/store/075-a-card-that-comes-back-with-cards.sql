-- A button whose answer becomes cards on the workbench.
--
-- «Идея — карточка-исполнитель, которая сама пойдёт в интернет, разузнает всё что попросили и
-- вернётся с новыми карточками, основанными на полученных данных.»
--
-- A button already sends a request "как будто бы мы его вписали в поле ввода" (059). What it could
-- not do is bring anything back except one answer card, and an answer card is a paragraph: it is
-- read whole or not at all, and the second half of it stays unread. Cards are taken one at a time.
--
-- ## What this console claims and what it does not
--
-- It does not claim to browse. Whether the engine behind an answer can reach the internet is the
-- CLI's business and changes with its configuration, so the card says what it *does* — it asks, and
-- what comes back becomes cards — and never that it went anywhere. Naming Google Drive as a
-- connector kind does not make this program able to read a Drive (agent_desk/connectors.py), and
-- the same rule holds here.
--
-- ## Why the flag is on the button and copied onto the block
--
-- The button is where somebody sets it, and the block is what is running when the answer arrives.
-- A button edited or deleted between the press and the answer must not change what happens to work
-- that is already going — which is the same reason a run freezes the cards it was started with
-- (037-runs.sql).

ALTER TABLE button_card ADD COLUMN brings_back INTEGER NOT NULL DEFAULT 0;
ALTER TABLE block ADD COLUMN brings_back INTEGER NOT NULL DEFAULT 0;
