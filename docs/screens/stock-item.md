# Stock item

One item of the [stock](stock.md), at `/h/<home id>/stock/<item id>/`.

- **The quantity** at the top is the sum of the movements below; it is stored
  nowhere else. A **Low stock** label shows when it is at or below the threshold.
- **Record a movement** takes a quantity, a date (today by default) and a note, then
  one button: **Add to stock** (an entry), **Take from stock** (an exit) or **Set the
  count** (an inventory: you state what you counted on the shelf and the stock is
  corrected to it). Taking more than what is in stock is refused (a task marked done is the exception: the stock stops at zero). A movement is
  never changed or deleted: a mistake is corrected by a new movement.
- **Rooms** lists the rooms where the item is used, and **Needed by tasks** the tasks that
  list it in their materials. A movement written by a task names that task.
- **Compatible items** lists the equipment or surfaces of the home this fits; each
  one opens its [item page](item.md).
- **Suppliers** lists where to buy it: name, supplier reference, purchase link and
  the last price paid, in the currency of the home. **Add a supplier** and **Edit
  the supplier** open the [supplier form](supplier-form.md). The purchase link is a
  plain link: HouseCairn never opens it and shows no preview.
- **The history** lists the movements, the most recent first.
- **The photo of the label** is shown when there is one. Its address,
  `/h/<home id>/stock/<item id>/label/`, opens for the members of the home only.
- **Edit the stock item** opens the [form](stock-item-form.md), where **Delete the stock item** asks
  for confirmation and removes the item, its suppliers and its movements from the
  screens and the API.

Read-only members see everything and none of the buttons that change it.
