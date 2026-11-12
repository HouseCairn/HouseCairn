---
orphan: true
nosearch: true
---

- **Adding a link and testing a channel no longer hold the screen.** Reading the page of an
  inspiration link and sending the test message of a notification channel are now done by the
  background worker: the screen answers at once, shows "Reading the page…" or "The test message
  is being sent.", then the result (reload the page if it does not change by itself). A task
  that does not end within 30 seconds is shown as failed
  ([ADR 0069](../../../adr/0069-slow-network-calls-in-the-background.md)).
