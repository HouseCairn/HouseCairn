# Add or edit an item

The form to add an item to a room, at
`/h/<home id>/rooms/<room id>/items/new/`, and to edit one, at
`/h/<home id>/items/<item id>/edit/`.

| Field | Content |
| --- | --- |
| Room | The room the item is in. Choose another one to move the item; its photos go with it. |
| Name | Required, 120 characters at most. |
| Type | Equipment or surface. |
| Brand, model, serial number | Free text, 120 characters at most each. |
| Installed on, warranty ends on | Dates. |
| Maintenance contract | Who services it, and the contract number if any. |
| Contract link | An `http` or `https` address. |
| Links | One address per line, then an optional label; ten at most, `http` or `https` only. |
| Notes | Free text, 4,000 characters at most. |

Only the name is required.
