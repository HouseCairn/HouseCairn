# Task form

The form to add a task, at `/h/<home id>/tasks/new/`, and to edit it, at
`/h/<home id>/tasks/<task id>/edit/`. Only the **title** is required. From a room
or an item, **Add a task** fills the room and the item in.

The first block holds the title, the room, the item (listed with its room), the
due date and, below, four sections that open when you need them:

| Section | Content |
| --- | --- |
| Repeat | **Once**, **Fixed date** (every N days, weeks, months or years from the first date) or **After the last time** (N units after the day it was done). A season (first and last month; November to March is fine) outside of which nothing falls, and the number of days before the date from which the task shows. |
| Who | Priority, the person in charge (a member of the home) and the contractor: pick one of the home or type a new name and trade. |
| Time and budget | Estimated duration in minutes, labour and material budgets, in the currency of the home. |
| How to do it | The procedure in Markdown, notes and, when adding, photos and files. |

Editing the date moves the occurrence that is open. Deleting the task, at the
bottom of the edit form, asks for confirmation and removes the task, its history
and its files from the screens.

When you add files together with the task and one of them is refused, the task is
created anyway and a message names the file and the reason.
