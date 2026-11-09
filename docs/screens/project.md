# Project

One [project](projects.md), at `/h/<home id>/projects/<project id>/`.

- **The top** shows the status, the priority and the state of the budget in words, then the
  goal, the rooms concerned, the estimated duration and the preferred season.
  **Edit the project** opens the [form](project-form.md).
- **Tasks** lists the tasks of the project with their date. **Add a task to the project**
  makes a new task, which is a task like any other (it also shows in **Tasks** and **Today**)
  and whose page names its project. **Put an existing task in the project** takes one that
  is in no project yet: a task is in one project at most. **Take out** removes a task from
  the project and keeps the task.
- **Budget** is a table of budget lines, in the currency of the home: **Planned** and
  **Paid** are typed; **Committed** is the sum of the quotes accepted on the line; **Gap** is
  the planned amount less the more of committed and paid, said in words (**... left**,
  **Over budget by ...**, **On budget**), never by colour alone. The last row is the total.
  **Add a budget line** and **Edit** open the [budget line form](budget-line-form.md).
- **Quotes** lists the quotes with the contractor, the amount, the status (requested,
  received, accepted, rejected), the line an accepted quote is committed on, the dates, the
  files and the Paperless-ngx document if one is noted. **Accept the quote** commits its
  amount on the line chosen next to the button; **Mark as received** and **Reject the quote**
  change its status; rejecting an accepted quote releases the line. **Add a quote** and
  **Edit the quote** open the [quote form](quote-form.md).
- **Photos** are pictures of the project, as the photos of a room: HouseCairn keeps the
  picture and nothing else, the location and every other piece of information hidden in the
  file are removed. Their address, `/h/<home id>/projects/files/<file id>/`, opens for the
  members of the home only. **Delete** asks for confirmation.

Deleting the project (in its [form](project-form.md)) removes it, its budget lines, its
quotes and its photos; its tasks stay. Read-only members see everything and none of the
buttons that change it.
