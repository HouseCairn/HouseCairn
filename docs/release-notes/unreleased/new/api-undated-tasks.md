---
orphan: true
nosearch: true
---

- **Tasks without a date in the API.** `GET /api/v1/homes/<id>/tasks/?due=none` returns only
  the active tasks that have no due date, so an integration no longer has to read the whole
  list to find them. It combines with the other filters and with the cursor; any other value
  of `due` is a 400. See the [API guide](../../../api/index.md).
