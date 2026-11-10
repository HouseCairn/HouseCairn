---
orphan: true
nosearch: true
---

- **Task templates.** About twenty common tasks of a home come ready, in English and in
  French, each with an indicative interval and the public source it comes from: the
  battery of the smoke alarms, the service of the boiler, the sweeping of the chimney, the
  vents of the ventilation, the gutters, the hot water tank and more. **Tasks › Add from a
  template** adds them in two taps, and the equipment ticked when a home is created adds
  theirs. A rule of one country, such as the yearly service of a boiler in France, is
  shown as such ([Add from a template](../../../screens/task-templates.md)).
- **A guide of the API**, with `curl` commands that the tests run against an instance:
  token, reads, writes, pages of a list and errors ([Using the API](../../../api/guide.md)).

- **Design guide: a secret is shown once.** The rule that the screen of the API tokens
  follows is now written for every screen: in the answer to the `POST` that made it, with
  `Cache-Control: no-store` and a Copy button
  ([Design guide](../../../developer/design-guide.md)).
