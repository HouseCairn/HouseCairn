"""Nothing of a home is registered in the administration site.

The administrator of the instance runs accounts, invitations and settings but
reads no home: neither the homes, nor their members, invitations or events
(docs/adr/0022). Every model that belongs to a home, now or later, stays out of
this site; `tests/test_instance_admin.py` fails when one is registered.
"""
