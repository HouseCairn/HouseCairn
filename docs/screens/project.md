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
  **Over budget by ...**, **On budget**), never by colour alone. The last row is the total, whose gap is the sum of the gaps of the
  lines.
  **Add a budget line** and **Edit** open the [budget line form](budget-line-form.md).
- **Quotes** lists the quotes with the contractor, the amount, the status (requested,
  received, accepted, rejected), the line an accepted quote is committed on, the dates, the
  files and the Paperless-ngx document if one is noted. **Accept the quote** commits its
  amount on the line chosen next to the button; **Mark as received** and **Reject the quote**
  change its status; rejecting an accepted quote releases the line. **Add a quote** and
  **Edit the quote** open the [quote form](quote-form.md).
- **Inspiration** lists the links added to the project, each with the title and the picture
  of the page when the instance reads previews (the picture is a copy kept by HouseCairn,
  never the remote one). **Add the link** takes an address and an optional title and
  reads the page once; if it cannot be read, the link keeps its address. **Delete** removes
  the link and its picture.
- **Photos** are pictures of the project, as the photos of a room: HouseCairn keeps the
  picture and nothing else, the location and every other piece of information hidden in the
  file are removed. Their address, `/h/<home id>/projects/files/<file id>/`, opens for the
  members of the home only. **Delete** asks for confirmation.

Deleting the project (in its [form](project-form.md)) removes it, its budget lines, its
quotes and its photos; its tasks stay. Read-only members see everything and none of the
buttons that change it.

The link at the top leads back to the screen the project was opened from (Budget, for
example, which then stays marked in the bar), and to the list of projects otherwise. The
buttons of the page (a task, a quote's status, a photo, a link) keep it: after them the
link at the top still leads to the same screen. A quote, a budget line or a change of the
project made from this page comes back to it. After deleting the project, you are back on
the screen it was opened from, or on the list of projects when that screen was the
project itself.
