# Instance settings

The settings of the instance, at `/instance/settings/`, reached from **Instance
administration**. Administrators only; anyone else gets a 404.

Each setting is paired with an environment variable (see [Settings](../administration/settings.md)):

- **Editable**: no variable sets it. Change the value and press **Save** at the bottom of
  its section. The default is shown below the field; **Restore the default** appears when you
  have changed it.
- **Locked**: a variable sets it. The field is read-only and shows the value in force, the
  name of the variable and a link to the documentation.
- **Secret** (the SMTP password): write only. The screen says whether one is stored; leave
  the field empty to keep it.

Sections: **Public address**, **Name, language and time zone** (name of the instance,
default language, time zone), **Sign-up** (open sign-up, sign-up through single sign-on,
allowed and blocked domains, anti-robot work), **Invitations** (lifetime), **Outgoing
email** (server, port, STARTTLS or TLS, user name, password, timeout, sender), **Rate
limits** (see [Rate limits](../administration/rate-limits.md)) and **Files of a home**
(largest file, space and number of files of each home). **Test the connection** checks the
mail server with the settings in force and sends nothing.
**Server** lists the variables that stay in the environment, read-only.

**Notifications** turns reminders on or off for the whole instance (off by default) and sets
how often the background worker looks for them, from 1 to 60 minutes (see
[Notifications](../guides/notifications.md)). It shows no channel of anyone.

Saving asks you to have signed in within the last five minutes; if you have not, you
are sent to confirm your sign-in and then back here, and you make the change again.
Every change is in the [audit log](instance.md).
