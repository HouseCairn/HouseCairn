# Stock and supplies

The spare parts and supplies of the house: the filter that goes in the ventilation
unit, the tin of paint of the living room, the batteries of the smoke detectors.
This guide shows how to keep track of them. Every field is optional except the name.

## Add a stock item

Open **Stock** in the navigation, then **Add a stock item**. Give it a name and, if
you have them at hand, the manufacturer reference, the dimensions, the unit and where
it is kept. A photo of the label saves typing the reference now and finding it again
later: HouseCairn keeps the picture and nothing else (the location and every other
piece of information hidden in the file are removed).

Choose the **compatible items** when the part is made for a given piece of
equipment, such as the boiler a filter fits. The link is shown on the page of the stock
item; the page of the equipment itself does not show it yet.

## Count what you have

The quantity is never typed in: it is the sum of the movements. On the page of an
item, enter a quantity and press **Add to stock** after a purchase, **Take from
stock** when you use some, or **Set the count** after counting the shelf, which
corrects the stock to what you counted. A movement is never edited; a mistake is
corrected by another one, so the history always explains the figure.

Set a **threshold** to see which items are running out: they carry a **Low** label,
and **Low stock only** in the list keeps them.

## Note where to buy

Add one or more suppliers to an item: name, their reference, the purchase link and the
last price paid, in the currency of the home. The link is only a link: HouseCairn
makes no request to it and shows no preview. The search of the list also finds an
item by the name of a supplier.

## Share

Everyone in the home sees the same stock; members and owners change it, read-only
members change nothing. The same data is available to scripts through the
[API](../api/index.md) (`articles`, `suppliers` and `movements`), with the `read` and
`write` scopes of an API token. The stock is part of the
[export of the home](../administration/data.md), label photos included, and is erased
with it.
