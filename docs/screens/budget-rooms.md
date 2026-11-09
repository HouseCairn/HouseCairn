# Budget by room

`/h/<home id>/budget/rooms/`, with `?year=` for the year and `?export=csv` for a file.

One row per room that has a figure, and **No room** for what belongs to none. A room adds up
the projects counted in the year that name it and the upkeep of its tasks in that year. A
project in several rooms is shared evenly between them, in whole cents, the odd cents going
to the first rooms, so the rooms always add up to the project. A row shows **Planned**,
**Committed**, **Paid**, the gauge of **Used** against planned and, in words, where it
stands. The total is at the foot of the table. Read-only members see the same page.
