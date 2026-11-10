# Entering an amount

The same rule applies to every amount you type: the budget of a project, a budget line, a
quote, the envelope, and the labour budget, material budget and actual cost of a task.

- **Write it as you speak.** In English `1250.50`, in French `1 250,50`. In French the point
  works too (`1250.50`), and spaces that group thousands are accepted (`1 250,50`).
- **Two decimals at most**, and a decimal mark only once. A form that could be read two ways
  is refused rather than guessed: `1,250.50` and `1.250,50` are refused, so are letters and
  a negative sign.
- **The currency is the one of the home**, never typed.
- **The largest amount is 9999999999.99**, and the smallest 0. The API and the files
  always use a dot and no space: `"1250.50"`.

Screens show amounts with the habits of your language, such as `€1,250.50` or
`1 250,50 €`. The symbol is the one your language gives to the currency of the home, and the
ISO code (`SEK`) when it has none; what is shown is not always what you type.
