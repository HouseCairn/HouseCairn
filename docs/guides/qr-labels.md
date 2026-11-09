# QR labels

Stickers that open the page of a boiler, a room or a shelf of the cellar when scanned.

## Print stickers

Open **QR labels** on the home page, tick the rooms, items and stock items to label,
choose a layout and press **Print the labels**. You get a PDF: an A4 sheet of 3 by 8
labels (63.5 by 33.9 mm, the format of common adhesive sheets) or a 62 mm roll with one
label per page for a label printer of the Brother QL kind. Print at 100 %: no scaling,
no "fit to page". Each label has the QR code, the name of the object and where it is (the
room of an item, the storage location of a stock item).

The code holds the address of the instance and a random identifier of 22 characters, and
nothing else: no name, no room, no number that could be guessed. **Set the public
address** of the instance (the `HOUSECAIRN_SITE_URL` setting) **before printing**: without
it the code holds the address the page was opened from, which may not be the one other
people use. If the instance later moves to another address, the stickers already stuck
stop working and must be printed again.

## What a sticker does

Scanning opens `/l/<code>/`. If you are not signed in, you sign in and come back. A member
of the home goes to the page of the object, read-only members included. Anyone else sees
"Page not found", the same page as for a sticker that was revoked, deleted or never
issued, so a code tells nothing to someone who is not in the home.

A sticker that is lost, photographed or shared is replaced: open the label and press
**Make a new label** (the old sticker stops opening anything) or **Revoke the label**.

The address is built to work as a universal link of a future iOS application, which would
claim `/l/*` through an `apple-app-site-association` file. That file is not served yet.

## Scripts

Labels are in the [API](../api/index.md) (`labels`), with the same rules as the screens.
They are in the [export of the home](../administration/data.md)
and are erased with it.
