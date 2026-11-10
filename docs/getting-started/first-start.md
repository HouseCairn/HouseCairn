# First start

The image creates no account and has no default password. At each start, while the
instance has no administrator, HouseCairn writes a one-time code in its log. The first
administrator comes from one of these, right after the first start.

## The first-account screen

Read the code in the log of the container:

```sh
docker compose logs housecairn | grep -A4 "no administrator yet"
```

It looks like this:

```text
HouseCairn has no administrator yet.
  Open https://home.example.com/setup/
  First-account code: 7QKF-3MZB-XJ2D-VR5L-HN6P-WT4C-ES8A-YG3U
  The code works once and expires in 60 minutes; a new one is written
  at each start, or by running: manage setup_code
```

Open the address, give the code, your name, your email address and a password. HouseCairn
creates the administrator account and signs you in. See
[First account](../screens/first-account.md).

- **In Home Assistant**, when HouseCairn runs as an add-on, the log is the **Log** tab of
  the add-on, which has no command line: this screen is the way to create the first
  account.
- **A new code** is written at each start. Without restarting, run
  `docker compose exec housecairn python -m housecairn.entrypoint manage setup_code`.
- **Switch the screen off** with `HOUSECAIRN_SETUP_SCREEN=false` if you create the
  administrator another way (below). It is never available once an administrator exists.

## Single sign-on (OpenID Connect)

Set `OIDC_SERVER_URL`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET`, and
preferably `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL`. The first person to sign in
through the provider becomes the instance administrator; if the address is
set, only an identity with that verified address can. See
[Single sign-on](../administration/oidc.md).

The first-account screen and single sign-on both create the first administrator: the
first to do it closes the other. If you rely on single sign-on, set
`HOUSECAIRN_SETUP_SCREEN=false`, so that nobody who can read the log can create an
administrator before you sign in.

## A local account from the command line

```sh
docker compose exec housecairn python -m housecairn.entrypoint manage createsuperuser
```

This also closes the first-account screen.

Local sign-up from the web page stays closed unless
`HOUSECAIRN_SIGNUP_OPEN=true`.

## Sign in

Open the address of your instance and sign in with the account you created.

After signing in, HouseCairn shows the list of your homes. A new instance has
none, and there is no screen to create one yet.
