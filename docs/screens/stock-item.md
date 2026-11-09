# Stock item

One item of the [stock](stock.md), at `/h/<home id>/stock/<item id>/`.

- **The quantity** at the top is the sum of the movements below; it is stored
  nowhere else. A **Low stock** label shows when it is at or below the threshold.
- **Record a movement** takes a quantity, a date (today by default) and a note, then
  one button: **Add to stock** (an entry), **Take from stock** (an exit) or **Set the
  count** (an inventory: you state what you counted on the shelf and the stock is
  corrected to it). Taking more than what is in stock is refused. A movement is
  never changed or deleted: a mistake is corrected by a new movement.
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

- **QR label** opens the [label](qr-label.md) of this stock item; **Make a QR label** makes
  it when there is none, for members who may write. Read-only members see the label and
  print it.

Read-only members see everything and none of the buttons that change it.
