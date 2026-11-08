# Notifications

Where and when your reminders go, at `/me/notifications/` (**More**, then
**Notifications**). Everything on this screen is yours alone: nobody else sees your
channels, not even an administrator of the instance.

When the instance has notifications off, the screen says so and you cannot add or test a
channel; its administrator turns them on in the [settings](instance-settings.md).

## Channels

The list shows the name of each channel and the kind of service (`ntfy`, `tgram`,
`mailto`...). **Add a channel** takes a name and an Apprise address, such as
`ntfys://ntfy.sh/my-topic` or `tgram://bot-token/chat-id`: see the
[guide](../guides/notifications.md) for the address of each service. The address is
kept encrypted and never shown again, on this screen or anywhere else.

Opening a channel lets you:

- rename it, or turn it off without deleting it (**Enabled**);
- **Send a test message**: a real message to the service. The answer is either "sent" or
  "could not be sent", without the service's own message; five tests a minute;
- **Delete the channel**. To change an address, delete the channel and add another.

## Reminders

- **First reminder (days before)**: how many days before the due date the first reminder
  comes, from 0 (the day itself) to 30. One by default.
- **Time of reminders**: reminders and the daily summary go out from this time of day.
  08:00 by default.
- **Quiet hours from** and **until**: nothing is sent in between; what was due goes out at
  their end. They may run past midnight (22:00 to 07:00). Give both or neither.
- **Daily summary**: one message a day for every task to remind, instead of one per task.
- **Language** of the messages, and **Time zone** of the times above (empty: the time zone
  of the instance).

**Download my notification settings** gives your channels (name, kind of service, never
the address) and these preferences as a JSON file. The same is in the
[API](../api/index.md).
