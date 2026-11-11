# How dates are shown

Every date on a screen is written the same way, in letters for the month, so that nobody
has to guess which number is the day and which is the month:

| | English | French |
| --- | --- | --- |
| A date | Nov 8, 2026 | 8 nov. 2026 |
| A date and the time | Nov 8, 2026, 2:30 PM | 8 nov. 2026, 14:30 |
| A date without its year | Nov 8 | 8 nov. |
| A day with its weekday | Sun, Nov 8 | dim. 8 nov. |

The numeric form `02/08/2027` is never shown: it reads as 2 August or as 8 February depending
on where you live. The language of your account decides the format, and a time is shown in
the time zone of the instance.

Boxes where you pick a date (the date of a task, a quote, a stock movement) are those of your
browser, which shows them in the habits of your system. The files and the API always use
`2027-02-08` (ISO 8601), as the other guides say.
