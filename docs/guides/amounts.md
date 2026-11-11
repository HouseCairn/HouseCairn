# Entering an amount

The same rule applies to every amount you type: the budget of a project, a budget line, a
quote, the envelope, and the labour budget, material budget and actual cost of a task.

- **Write it as you speak.** In English `1250.50`, in French `1 250,50`. In French the point
  works too (`1250.50`), and spaces that group thousands are accepted (`1 250,50`).
- **Two decimals at most**, and a decimal mark only once. A form that could be read two ways
  is refused rather than guessed: `1,250.50` and `1.250,50` are refused, so are letters and
  a negative sign.
- **In English the comma is refused, and the message says what to type**: typing `12,5`
  shows "Enter a number with a point as the decimal mark, for example 12.5." In French the
  comma is the decimal mark and is accepted.
- **The currency is the one of the home**, never typed.
- **The largest amount is 9999999999.99**, and the smallest 0. The API and the files
  always use a dot and no space: `"1250.50"`.

Screens show amounts with the habits of your language, such as `€1,250.50` or
`1 250,50 €`. The symbol is the one your language gives to the currency of the home, and the
ISO code (`SEK`) when it has none; what is shown is not always what you type.

## Quantities

The same rule applies to every other decimal number you type: the quantity of a stock
movement, of a stock item needed by a task, the quantity really used when a task is marked
done, the threshold of a stock item and the last price paid to a supplier. Up to two
decimals, the decimal mark of your language (`12.5` in English, `12,5` in French), and the
same message when the English form meets a comma.
