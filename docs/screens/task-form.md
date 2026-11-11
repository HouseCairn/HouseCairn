# Task form

The form to add a task, at `/h/<home id>/tasks/new/`, and to edit it, at
`/h/<home id>/tasks/<task id>/edit/`. Only the **title** is required. From a room
or an item, **Add a task** fills the room and the item in.

The first block holds the title, the room, the item (listed with its room), the
due date and, below, five sections that open when you need them:

| Section | Content |
| --- | --- |
| Repeat (open when the task is added from an item, or when it repeats) | One sentence: **Repeat this task**, **Repeat every** N days, weeks, months or years, **Count from** the due date or the day it is done (see below). A **season** outside of which nothing falls (see below), the number of days before the date from which the task shows, and the repetition said in plain words. |
| Who | Priority, the person in charge (a member of the home, shown by name) and the contractor, in one field: pick one of the home from the suggestions or type a new name, which is added to the contractors of the home when you save. Empty the field to remove the contractor. |
| Time and budget | Estimated duration (a number and a unit: minutes, hours or days), labour and material budgets, in the currency of the home. |
| Materials | The stock items the task needs, one line each: the stock item and the quantity. Two empty lines are offered for more; set a line's stock item to the dash to remove it. Marking the task done takes these quantities from the stock. |
| How to do it | The procedure in Markdown, notes and, when adding, photos and files. |

## Repeat

Leave **Repeat this task** unticked for a task done once. Ticked, the task comes back
**every** N days, weeks, months or years, counted from:

- **the due date**: the task keeps its day, whenever it is done. A date field, **Starting
  on**, opens with the calendar of the device; it is the due date of the first block, and
  typing in one fills in the other. A task due on 15 January 2027, every 3 months, stays on
  the 15th even when it is done on the 20th.
- **the day it is done**: the period is the number of days, weeks, months or years chosen,
  counted from the day the task is marked done. A filter changed on 3 March, every 3 months,
  is due on 3 June. The date field is hidden, as it is not used.

Under the fields, **In short** says the repetition in plain words and follows what you
type: "Next time: 3 months after the last time", "Day 15 of every quarter, from
01/15/2027", with the months of the season if there is one. A task set on the 31st falls on
the last day of shorter months, one set on 29 February on 28 February in other years: the
sentence says so.

Without script, every field stays visible and nothing is lost: the server ignores what the
choices do not use (the interval of a task done once, the date field when counting from the
day it is done). If both date fields were changed to two different dates, the form asks for
one.

## Season

A task can be limited to a season: **Spring**, **Summer**, **Autumn**, **Winter** or
**Custom months** (a first and a last month; November to March is fine). The two month
fields show only with **Custom months**; without script they stay visible and are ignored
for another season. The predefined seasons follow the **hemisphere** of the home, which you
set on the [home](home.md) page: in the northern hemisphere spring is March to May, summer
June to August, autumn September to November and winter December to February; in the
southern one they are shifted by six months. Changing the hemisphere of the home moves the
tasks on a predefined season; a custom season keeps its months.

The heating season is no longer offered: for the heating, take **Custom months**, October to
April in the north. A task or a project that had it was given those months when the
application was updated, and an archive, a CSV file or an API client of before that sends
it gets them too, so nothing changes for it.

## Estimated duration

A whole number and a unit, from 1 minute to 30 days; it is stored in minutes and shown as
people say it: **45 min**, **1 h 30**, **2 days**.

## Contractor

The field has no list to scroll through: start typing and the contractors of the home are
suggested (with their trade); without script, type the name. A name that is already in the
home, whatever its case, picks that contractor; a new name creates one, which you complete
on its [sheet](contractor.md).

Editing the date moves the occurrence that is open. Deleting the task, at the
bottom of the edit form, asks for confirmation and removes the task, its history
and its files from the screens.

When you add files together with the task and one of them is refused, the task is
created anyway and a message names the file and the reason.

## Going back

The link at the top and the form once sent lead back to the screen the form was
opened from: a task added from an item goes back to the item, with the message
**Task added · Open**, whose link opens the new task. Opened from the task list, the
form opens the new task instead. A form sent with an error stays open and still goes
back to the same screen. After **Delete the task**, the page of the deleted task no
longer exists: you land on the task list, or on the screen you came from if it was
another one.
