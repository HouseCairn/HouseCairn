---
orphan: true
nosearch: true
---

- **One way to write a date.** An English screen could show `Nov. 8, 2026` beside
  `02/08/2027`, which reads as 2 August or as 8 February. Every date now has its month in
  letters, in one format per language: `Nov 8, 2026` in English, `8 nov. 2026` in French
  ([how dates are shown](../../../guides/dates.md)).
- **A comma in a number tells what to type.** In English `12,5` is still refused, but the
  message now says "Enter a number with a point as the decimal mark, for example 12.5." instead
  of "Enter a number." The quantities of stock and of materials, the quantity used when a task
  is marked done, the threshold of a stock item and the last price paid to a supplier follow
  the rule of the amounts, which was only that of money fields: in French they accept the
  comma (`12,5`) ([entering an amount](../../../guides/amounts.md)).
- **The tests no longer read your `.env`.** Following the quick start, `cp .env.example .env`
  sets `DEBUG=true`, which made `test_debug_is_off_by_default` fail. The tests that import the
  settings do it from a copy of the sources, without any `.env`, and the contributor guide
  lists the `data` folder the quick start needed.
