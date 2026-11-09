# Projects

The projects of a home, at `/h/<home id>/projects/`. **Projects** in the navigation opens
it; `/projects/` first asks which home when you belong to several.

A project is a piece of work with an end, such as redoing the bathroom. Three tabs split the
projects by status: **In progress** (in progress and planned, the root of the section, at
`/h/<home id>/projects/`), **Ideas** (`?view=ideas`) and **Finished** (finished and
abandoned, `?view=finished`). Within a tab the list groups the projects by status. It is a plain list, not a board. A row shows the title, the planned
budget and, in words, where the budget stands: **... left**, **Over budget by ...** or
**On budget**. A row opens the [project](project.md).

- **The filters** at the head narrow the list by words of the title or the goal, status,
  room and priority: `/h/<home id>/projects/?status=in_progress&room=<room id>`. A filter
  that is not valid is ignored.
- **Compare the ticked projects** opens the [comparison](project-compare.md) of the projects
  whose box is ticked.
- **Add a project** opens the [project form](project-form.md).
- **The budget envelope** at the top is what the household wants to spend on work this year.
  It sets it against the planned budget of the projects that are neither finished nor
  abandoned, shows what is paid so far and what is left, and says **over the envelope**
  when the plans exceed it. **Set the envelope** (owners and members) asks for a year and
  an amount in the currency of the home, at `/h/<home id>/projects/envelope/`.

The [budget](budget.md) sets the envelope against the projects and the upkeep of the year
together.

Read-only members see the same list and none of the buttons that change it.
