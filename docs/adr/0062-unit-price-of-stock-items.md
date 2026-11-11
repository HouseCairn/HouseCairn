# 0062. Unit price of a stock item, planned cost of a task from its materials

- Status: accepted
- Date: 2026-11-12
- Extends: [0046](0046-stock-linked-to-tasks-and-rooms.md) (materials of a task), [0051](0051-budget-views-and-annual-envelope.md) (budget views)
- Amends: [0051](0051-budget-views-and-annual-envelope.md) (the stock consumed by a task was out of scope)

## Context

A task lists the stock items it needs, but its estimate only knew the material budget typed by
hand, so the stock a task would use was never counted in its planned cost. The maintainer
decided on 2026-11-11 that the stock joins the plan at a price per unit, and that a stock item
made from the form of a task is linked to the equipment of that task.

## Decision

- **A unit price on the item.** `stock.Article.unit_price` is optional, never negative, with the
  bounds of the other stock amounts (ten digits, two decimals), in the currency of the home.
  The price paid at each supplier (`Supplier.last_price`) stays on the supplier.
- **Filled from a supplier, once.** When an item has no unit price and a supplier is created, or
  its last price is changed, with a price, the item takes it (`stock.services`). A price that is
  there is never replaced, so a correction by hand holds. There is no link: changing the
  supplier's price later does not move the unit price. The alternative, reading the price of
  the latest supplier each time, would make the plan of a task change with no edit of the task
  or of the item.
- **The plan of a task** is the typed material budget plus, for each material line, quantity
  times unit price, added and rounded once to the cent, half up (`budget.services.stock_plan`,
  the only place where it is worked out; the screens, the API and the totals read it). An item
  with no unit price counts for nothing and is counted apart (`unpriced`); a price of zero is a
  price. The typed budget is never changed: the part of the stock is a separate figure
  (`TaskRow.stock`), shown as "of which stock", so a person always sees what they typed.
- **It is a plan.** The real cost stays the cost typed when a task is done (and, for what was
  really paid, Sure). Nothing here writes or reads a payment. The share of a real cost between
  materials and labour uses the plan with the stock in it.
- **Tasks of a project** keep their money in the budget lines of the project: no stock plan is
  added to their figures.
- **Export format.** The field is added to the section `stock_items` with no change of the
  format version: a field added by a later version is in the archive without a new version
  (`docs/administration/data.md`). An archive written before reads the field as empty. The
  published schema of version 3 lists the new field.
- **A stock item made from a task form** is created compatible with the equipment of the task,
  after the equipment of the same submission has been created, so the order of creation is the
  one of the form: room, equipment, task, stock items.

## Consequences

- One query more to load the budget, whatever the number of tasks.
- An item added from a task form has no price until someone gives it one: the screen says how
  many items of a task are without a price.
