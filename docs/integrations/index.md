# Integrations

HouseCairn works fully without any integration. Each one is optional and off by
default. Wherever possible, the other tool pushes to HouseCairn (webhooks)
rather than HouseCairn holding its token.

- **Home Assistant**: the
  [Home Assistant app](https://github.com/HouseCairn/home-assistant-addons)
  runs HouseCairn inside Home Assistant and opens it in the sidebar (ingress).
  The [integration](https://github.com/HouseCairn/home-assistant-housecairn),
  installed with HACS, shows the tasks of a home as sensors and a to-do list and
  marks a task done. It uses a HouseCairn API token; HouseCairn never holds a
  Home Assistant token.
- **Notifications**: reminders go to the services people already read, through
  [Apprise](https://github.com/caronc/apprise): more than a hundred services, each one
  reviewed, from Telegram, Signal and Matrix to ntfy, SMS gateways and email (see
  [Notifications](../guides/notifications.md)). Home Assistant is not one of them: it would
  need a Home Assistant token.
- **Paperless-ngx** (documents) and **Sure** (actual spending): planned.
