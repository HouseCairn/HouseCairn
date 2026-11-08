# Stock

The stock of a home, at `/h/<home id>/stock/`. **Stock** in the navigation opens it
directly when you belong to a single home; with several homes, it first asks which
one (`/stock/`). Each row shows the name of the item, its current quantity with
its unit and where it is stored; a **Low** label appears when the quantity has
fallen to the threshold or below. A row opens the [stock item](stock-item.md).

- **Add a stock item** opens the [stock item form](stock-item-form.md). Only the
  name is required.
- The search field looks for the text anywhere in the name, in the manufacturer
  reference or in the name or reference of a supplier, ignoring case:
  `/h/<home id>/stock/?q=<text>`.
- **Low stock only** keeps the items at or below their threshold:
  `/h/<home id>/stock/?low=1`. An item with no threshold is never low.

Read-only members see the same list and none of the buttons that change it.
