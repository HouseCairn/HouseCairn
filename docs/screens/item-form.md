# Add or edit an item

The form to add an item to a room, at
`/h/<home id>/rooms/<room id>/items/new/`, and to edit one, at
`/h/<home id>/items/<item id>/edit/`.

| Field | Content |
| --- | --- |
| Room | The room the item is in. Choose another one to move the item; its photos go with it. |
| Name | Required, 120 characters at most. |
| Type | Equipment or surface. |
| Brand | Free text, 120 characters at most. The brands already entered for the items of the home are suggested as you type; any other text is kept. |
| Model, serial number | Free text, 120 characters at most each. |
| Installed on, warranty ends on | Dates. |
| Maintenance contract: provider | Who services it, 200 characters at most. |
| Maintenance contract: number | The number to quote when you call them, 120 characters at most. |
| Contract link | An `http` or `https` address. |
| Links | One address per line, then an optional label; ten at most, `http` or `https` only. |
| Notes | Free text, 4,000 characters at most. |

Only the name is required.

The link at the top and the form once sent lead back to the screen the form was
opened from: an item added from its room goes back to the room, with the message
**Item added · Open**. Saved changes go back to where the form was opened.
