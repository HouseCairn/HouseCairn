# Add or edit a supplier

The form to add a supplier to a [stock item](stock-item.md), at
`/h/<home id>/stock/<item id>/suppliers/new/`, and to edit one, at
`/h/<home id>/stock/suppliers/<supplier id>/edit/`.

| Field | Content |
| --- | --- |
| Name | Required, 120 characters at most. |
| Supplier reference | The reference in their catalogue. |
| Purchase link | An `http` or `https` address; any other kind (such as `javascript:`) is refused. HouseCairn never opens it. |
| Last price paid | In the currency of the home. |

An item can have several suppliers. **Delete the supplier**, at the bottom of the edit form, asks for confirmation and removes it.
