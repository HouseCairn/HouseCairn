# Room

One room, at `/h/<home id>/rooms/<room id>/`. The address stays the same when
the room is renamed or reordered, so it can be printed on a label.

The page has five parts:

- the **type** and the **notes** of the room, with **Edit the room**;
- the **room memory**: paint (colour, brand, reference, batch, what is left in
  stock), floor and wall coverings and free notes, with **Edit the memory**.
  It is empty until you note something, and nothing in it is required;
- **Open walls**: photos taken before a wall or a duct was closed, to find
  where the cables and pipes run;
- **Photos** of the room, with **Add a photo**, see [Add a photo](photo-form.md);
- the **items** in the room, with **Add an item**.

**Delete the room** (in the edit form) asks for confirmation. Deleting a room
also deletes its items and their photos; they disappear from every screen and
from the API.

Members and owners change the room; read-only members see it all and change
nothing. An address that does not exist, or that belongs to a home you are not
a member of, answers the same "Page not found".
