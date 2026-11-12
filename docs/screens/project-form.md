# Project form

Adds a project (`/h/<home id>/projects/new/`) or changes one
(`/h/<home id>/projects/<project id>/edit/`). Only the **title** is required.

- **Goal** says what the work is for.
- **Status** is idea, planned, in progress, finished or abandoned. **Priority** is low,
  normal or high.
- **Budget** (when adding) is the amount you plan to spend, in the currency of the home. It
  becomes the first [budget line](budget-line-form.md), which you can split into materials
  and labour later. Leave it empty to add lines yourself.
- **Rooms, duration and season** is under a heading. The **rooms concerned** are rooms of
  the home, chosen in a search field: type to narrow the list, pick a room, and it becomes a chip
  that its **Remove** button takes away (without JavaScript, a list where you choose several). The **estimated duration** is a number and a unit (minutes, hours, days, weeks, months or
  years), from a minute to a year. The **preferred season** is one of the seasons of tasks; it follows
  the hemisphere of the home, and **Custom months** takes a first and a last month.

**Delete the project** asks for confirmation. It removes the project, its budget lines, its
quotes and its photos from the screens and the API; its tasks stay, taken out of the
project.
