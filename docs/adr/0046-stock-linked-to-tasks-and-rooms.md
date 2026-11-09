# 0046. Stock linked to tasks and rooms, the stock follows Done

- Status: accepted
- Date: 2026-11-09

## Context

The stock (ADR 0038) was a ledger next to the tasks: a task did not say what it needs, so
nothing took the stock down when the task was done, which the specification asks for.
The paint left over in the memory of a room was a free text that no one could keep up to
date, a room did not show the articles that concern it, and the unit of an article was a
free text (ADR 0045 asks for a list with Other wherever there is a free value).

## Decision

**Materials of a task.** `tasks.TaskMaterial` lists an article of the same home with a
quantity planned, once per task (a unique constraint on live rows). It is edited from the
task form (a formset of lines; emptying the stock item of a line removes it) and from the
task page, and in the API at `task-materials/`, which the task also lists, read-only, in
`materials`. A line whose article was deleted is hidden, not removed, so that restoring the
article restores the line. The tasks depend on the stock; the stock never imports the tasks
(the link back is a string foreign key).

**Done takes the stock.** Marking an occurrence done writes, inside the transaction that
closes it, one exit per material for the planned quantity, and records the draw in
`tasks.MaterialDraw` (`wanted`, `drawn`, one live row per occurrence and article). The
exits point to the occurrence (`stock.Movement.occurrence`), so the history of an article
says which task used it. Skipping takes nothing.

**Undo gives it back by entries.** The ledger stays append-only (ADR 0038): undoing writes
an entry of what was drawn and ends the draw; the exit is not touched. Marking the task done
again takes again. Undoing is refused, as before, once the next occurrence was worked on,
and nothing has then been put back.

**The real quantity is entered afterwards.** Done stays one gesture. Completing the
occurrence (`tasks:occurrence-edit`, and `PATCH` of the occurrence with `used`) sets the
quantity really used of each article taken: less puts the difference back by an entry, more
takes it by an exit. An article the closing did not take is refused (400).

**Not enough stock never blocks Done: an exception to ADR 0038.** ADR 0038 refuses an exit
that would take the stock below zero, which is right for a person typing a movement: they
can see the shelf. It is wrong here: a task was done in the real world, and a refusal would
leave the application saying the opposite. So the draw takes `min(planned, stock)` (the
stock stops at zero, never negative; no line is written when there is nothing), keeps the
planned quantity in `wanted`, and tells the shortage: the screen shows a warning with the
quantities, the API answers `short` in the closing. The article is then probably out of
stock, and the threshold already flags it. Completing again, or the next closing, takes
what is available. Alternatives rejected: refusing Done (the task would have to be done
twice, once for the stock); letting the stock go negative (breaks the rule that the ledger
never shows less than nothing and every report that sums it).

**Concurrency.** The closing locks the occurrence row (`SELECT ... FOR UPDATE`) and checks it
is still open, then each article row, in the order of the identifiers so that two tasks
needing the same articles cannot wait for one another. The second of two Done at once finds
the occurrence closed (400) and takes nothing; the unique constraint on the draws is the
safety net if a lock were ever missed.

**Rooms.** An article lists rooms (`Article.rooms`, besides the rooms of the equipment it
fits). The page of a room shows the articles that concern it: listed on it, compatible with
an item of the room, or the paint left over; the API offers `articles/?room=`. The **paint
left over** of the memory of a room is a link to an article of the home (`Room.paint_article`):
its quantity and its place are read from the stock, so they cannot be out of date. The old
free text is not lost: the migration appends it to the memory notes as a line
`Paint left in stock: <text>` and undoing the migration takes the last such line back.

**Units.** The unit of an article is a list (piece, litre, metre, kilogram, roll, box) plus
Other with its own text (`unit_other`), as the trade of a contractor (ADR 0045). The
migration maps the usual spellings, in English and French, to the list and keeps anything
else under Other; undoing writes the plural of the list again, or the text of Other.
Quantities are written with the unit in the right number (`1 litre`, `2 litres`).

**Remarks of the review of ADR 0038.** `record_movement` and the draws share one function
that locks the article and reads its stock, and a test requests the lock (and, on
PostgreSQL, runs two connections). The label file is replaced after the article is saved and
removed if the save fails, as photos are. A count too far from the stock to fit the column is
an error of the quantity, not of `delta`. **A backdated count** (an inventory with a date in
the past) states the quantity on the shelf now: its difference is worked out against the
whole stock at the moment it is recorded, wherever its date puts it in the history; the date
only places the line.

**Isolation.** Articles, rooms and tasks are checked against the home on the screens and in
the API (a line of another home is a 400 or 404). Read-only members read the lines and the
draws and change nothing, closing a task included. The export holds the lines
(`task_materials`), the draws (`stock_draws`), the rooms of an article and the
`occurrence` of a movement; erasing the home erases them with it (cascade on the home).

## Consequences

Closing a task writes to the stock, so a task done by a script moves the stock too. An
article used by a task cannot be told apart from one used by hand except by the occurrence
on its movements. The `paint_stock` field disappears from the API of a room (replaced by
`paint_article`) and `unit` of an article only accepts the list.
