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

Sections: **Public address**, **Sign-up** (open sign-up, sign-up through single sign-on,
allowed and blocked domains, anti-robot work), **Invitations** (lifetime) and **Outgoing
email** (server, port, STARTTLS or TLS, user name, password, timeout, sender). **Test the
connection** checks the mail server with the settings in force and sends nothing.
**Server** lists the variables that stay in the environment, read-only.

Saving asks you to have signed in within the last five minutes; if you have not, you
are sent to confirm your sign-in and then back here, and you make the change again.
Every change is in the [audit log](instance.md).
