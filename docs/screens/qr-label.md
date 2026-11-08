# QR label

One label, at `/h/<home id>/labels/<label id>/`, opened from the list of
[QR labels](qr-labels.md) or from the page of a room, an item or a stock item.

- The **QR code** is drawn on the page. Under it, the **address it holds**:
  `<public address of the instance>/l/<code>/` and nothing else. The code is 22
  characters of random, with no name and no identifier in it.
- **Open the page** goes to the room, item or stock item the label stands for.
- **Print this label** downloads a PDF of this label alone, in the layout you choose
  (A4 sheet or 62 mm roll).
- **Make a new label** and **Revoke the label**, for members who may write: a new label
  has a new code and the old sticker stops opening anything; revoking stops it without
  replacing it. Both are recorded in the [audit log](audit.md), with the name of the
  object and never the code. Use them when a sticker is lost, photographed or shared.

Read-only members see the code and print it; they do not see the buttons that change it.
