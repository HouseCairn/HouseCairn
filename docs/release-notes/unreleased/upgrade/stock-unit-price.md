---
orphan: true
nosearch: true
---

- **Stock: a unit price, without a new export format.** Migration `stock.0005` adds the optional
  field `unit_price` to the stock items (reversible; it drops the field). Archives of the home
  gain the field `unit_price` in `stock_items` and stay in format 3; an archive written before
  restores with no unit price. The planned cost of the tasks that list stock items with a price
  goes up by the cost of those items, which may change the figures of the budget.
