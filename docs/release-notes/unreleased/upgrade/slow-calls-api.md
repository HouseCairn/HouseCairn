---
orphan: true
nosearch: true
---

- **API: testing a channel and adding a link answer before the work is done.**
  `POST /api/v1/me/notification-channels/<id>/test/` answers `202` with `{"state": "running",
  "detail": ...}` instead of `{"ok": ..., "detail": ...}`; read `test_state` of the channel
  later (`sent`, `failed` or `private`). A link created with the preview on is returned with
  `preview_state: "running"`, and its `title` and `image_url` are filled when it is `done`.
  The queue is the one of the background worker, which must be running (it is, in the
  container)
  ([API](../../../api/index.md)).
