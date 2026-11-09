# Task form

The form to add a task, at `/h/<home id>/tasks/new/`, and to edit it, at
`/h/<home id>/tasks/<task id>/edit/`. Only the **title** is required. From a room
or an item, **Add a task** fills the room and the item in.

The first block holds the title, the room, the item (listed with its room), the
due date and, below, five sections that open when you need them:

| Section | Content |
| --- | --- |
| Repeat | **Once**, **Fixed date** (every N days, weeks, months or years from the first date) or **After the last time** (N units after the day it was done). A **season** outside of which nothing falls (see below), and the number of days before the date from which the task shows. |
| Who | Priority, the person in charge (a member of the home, shown by name) and the contractor, in one field: pick one of the home from the suggestions or type a new name, which is added to the contractors of the home when you save. Empty the field to remove the contractor. |
| Time and budget | Estimated duration (a number and a unit: minutes, hours or days), labour and material budgets, in the currency of the home. |
| Materials | The stock items the task needs, one line each: the stock item and the quantity. Two empty lines are offered for more; set a line's stock item to the dash to remove it. Marking the task done takes these quantities from the stock. |
| How to do it | The procedure in Markdown, notes and, when adding, photos and files. |

## Season

A task can be limited to a season: **Spring**, **Summer**, **Autumn**, **Winter**,
**Heating season** or **Custom months** (a first and a last month; November to March is
fine). The predefined seasons follow the **hemisphere** of the home, which you set on the
[home](home.md) page: in the northern hemisphere spring is March to May, summer June to
August, autumn September to November, winter December to February and the heating season
October to April; in the southern one they are shifted by six months. Changing the
hemisphere of the home moves the tasks on a predefined season; a custom season keeps its
months.

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
