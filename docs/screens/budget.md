# Budget

The budget of a home, at `/h/<home id>/budget/`. **Budget** in the navigation opens it,
with its tabs **Summary**, **Rooms**, **Projects** and **Upkeep**. `/budget/` goes straight to the budget of the
[current home](my-home.md#the-current-home), without asking which home.

The page is figures only: nothing on it changes your data, so everyone who can open the home
reads it, read-only members included. How the figures are worked out is in the
[budget guide](../guides/budget.md).

- **Year** picks the year of the figures; **Download as CSV** gives the same figures as a
  file.
- **The envelope of the year** is three figures and a gauge: what is set aside (the
  **envelope**, or **Planned** when no envelope is set), what is **Spent** (the more of
  committed and paid) and what is **Left**. Next to the gauge, a sentence says the share
  spent in percent; past the limit it says **Over by ...** and *over budget*, so colour is
  never the only signal. **Details of the year** (closed by default) holds the rest: planned
  against the envelope, what is left to plan, what is paid, projects and upkeep apart, and
  **Budget in Sure**, which says *Not connected*: that place is kept for a later version and
  nothing is fetched. **Set the envelope** (owners and members) leads to the projects screen.
- **By nature** splits the year into materials, labour, rental and other. The cost typed on
  a task that is done is shared between *Materials* and *Labour* as the estimate of the task
  is, so it stands against its own plan; with no estimate, it counts under *Other*.
- **By year** lists every year that has a figure, with its envelope.
- **Last 12 months** is the upkeep done since the same day last year. Payments on projects
  carry no date, so they are not in it.

Every row says where the budget stands in words (**... left**, **On budget** or **Over budget
by ...**) and shows a gauge with its percentage: colour is never the only signal.
See [by room](budget-rooms.md), [by project](budget-projects.md) and
[by task](budget-tasks.md).
