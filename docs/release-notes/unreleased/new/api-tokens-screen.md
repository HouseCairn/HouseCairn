---
orphan: true
nosearch: true
---

- **API tokens from the application.** You create, list and revoke your
  [API tokens](../../../screens/api-tokens.md) in **More**, **API tokens**, without a command
  on the server: a name, the rights (**Read** by default), the homes it opens and an expiry
  of 30 days, 90 days (the default) or 1 year. The value is shown once, with a **Copy**
  button, and never again. The same operations are in the
  [API](../../../api/index.md): `GET` and `POST /api/v1/me/tokens/`, `DELETE
  /api/v1/me/tokens/<id>/`, for a person signed in only (a token gets `403`). Creating and
  revoking a token go to the audit log of the instance.
