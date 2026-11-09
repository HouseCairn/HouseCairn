# Budget line form

Adds a budget line to a [project](project.md)
(`/h/<home id>/projects/<project id>/lines/new/`) or changes one
(`/h/<home id>/projects/lines/<line id>/edit/`).

- **Label** is what it pays for ("Paint", "Plumber").
- **Nature** is materials, labour, rental or other.
- **Planned** is what you plan to spend; **Paid** is what has been paid so far. Both are
  amounts in the currency of the home, from 0 to 9999999999.99, with at most two
  decimals ([how to type one](../guides/amounts.md)). The committed amount is not typed: it is the sum of the quotes accepted on the
  line.

**Delete the budget line** asks for confirmation. The quotes accepted on it go back to
*received*: they commit nothing any more.
