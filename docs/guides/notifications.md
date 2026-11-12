# Notifications

HouseCairn reminds you of your tasks through the service you already read, among more than a
hundred that [Apprise](https://github.com/caronc/apprise) can reach: messaging (Telegram,
Signal, Matrix, Microsoft Teams, Rocket.Chat, Zulip...), push notifications (ntfy, Gotify,
Pushover, Pushbullet, Bark...), text messages (Free Mobile, SFR, Twilio...), email, and
services you host yourself.

## Before you start

Notifications are off on a new instance. An instance administrator turns them on in
**Instance administration, Settings, Notifications**, or with the variable
`HOUSECAIRN_NOTIFICATIONS_ENABLED=true` (see [Settings](../administration/settings.md)). The
background worker of the container then looks for reminders every five minutes.

Links to tasks in the messages need the public address of the instance
(`HOUSECAIRN_SITE_URL`). Without it, the message has no link.

## Add a channel

Open **More**, then [Notifications](../screens/notifications.md). Give the channel a name
and its Apprise address. Some examples, with `example.com` standing for your server:

| Service | Address |
| --- | --- |
| ntfy | `ntfys://ntfy.example.com/my-topic` |
| Gotify | `gotifys://gotify.example.com/app-token` |
| Telegram | `tgram://123456789:bot-token/111222333` |
| Signal (signal-cli REST API) | `signals://signal.example.com/+15555550100/+15555550101` |
| Matrix | `matrixs://user:password@matrix.example.com/#room:example.com` |
| Email | `mailtos://user:password@mail.example.com?to=me@example.com` |

For Telegram, put the token that BotFather gave the bot (digits, a colon, then letters)
and the number of the chat; for Signal, the number registered with signal-cli, then the
number to send to, both in international format.

The Apprise documentation lists the options of each service. Then open the channel and
**Send a test message**. If it does not arrive, check the address: the screen does not
repeat the service's error, since it may carry your secrets. HouseCairn waits at most eight
seconds per channel, for a test as for a reminder: a service slower than that counts as
not reached.

The address is encrypted, never shown again and never exported. Some addresses are refused:
services that would run something on the server, write to its logs or open a raw
connection, generic webhooks (`json://`, `xml://`, `form://`), options that make the server
read a file or add headers or fields to the request (`+name`, `-name`, `:name`), and
addresses of the server itself or of a cloud metadata service.

Addresses of a private network, such as a ntfy or a Gotify on your local network, are
refused too, unless an instance administrator turns on **Channels on the local network**
(**Instance administration, Settings, Notifications**; see
[Hardening](../administration/hardening.md)). An address that gives the IP address of such
a server is refused when you add the channel; a name that leads to one is refused when a
message is sent, and **Send a test message** then says so.

## Services

The [Notifications](../screens/notifications.md) screen lists every service accepted, by
family, with an example address and a link to its page in the Apprise documentation:

- **Messaging**: DingTalk, Discord, Feishu, Flock, Fluxer, Google Chat, GroupMe, Guilded,
  KOOK, Lark, LINE, Matrix, Mattermost, Microsoft Teams (through a Power Automate
  workflow), Notifico (IRC), QQ, Revolt, Rocket.Chat, Ryver, Slack, Stackfield, Telegram,
  Threema Gateway, Twist, Viber, Webex, WeChat Work, WeCom bot, WhatsApp Business, Zalo,
  Zoho Cliq, Zoom Team Chat, Zulip.
- **Push notifications**: Bark, Chanify, Dot., IFTTT, Join, Kumulos, Lauther, LFG Alarm,
  Notifiarr, ntfy, OneSignal, Pingram, Prowl, Pushbullet, PushDeer, Pushed, PushMe,
  Pushover, PushPlus, Pushsafer, PushWard, Pushy, ServerChan, Signalgrid, Simplepush, Spug
  Push, Streamlabs, Techulus Push, Trigv, WPush, WxPusher, YouLMK.
- **Text messages (SMS)**: 46elks, 800.com, Africa's Talking, Amazon SNS, BulkSMS, BulkVS,
  Burst SMS, Clickatell, ClickSend, D7 Networks, DAPNET, Exotel, Free Mobile, httpSMS,
  Kavenegar, MessageBird, Mobile Message, MSG91, Notifyre, Octopush, Plivo, RingCentral,
  SerwerSMS, seven, SFR, Sinch, SMS Manager, SMSC, Telnyx, Twilio, VoIP.ms, Vonage.
- **Email**: your own mail server (SMTP), Amazon SES, Brevo, MailerSend, Mailgun,
  Microsoft 365, Postmark, Resend, SendGrid, SendPulse, SMTP2GO, SparkPost.
- **Self-hosted**: Apprise API, Emby, Enigma2, Evolution API, Gorush, Gotify, HumHub,
  Jellyfin, Kodi, LaMetric Time, Nextcloud, Nextcloud Talk, OneBot, Parse Platform,
  Pushjet, Signal (signal-cli REST API), SMSEagle, Synology Chat.
- **On-call and alerting**: Better Stack, GoAlert, ilert, incident.io, PagerDuty,
  PagerTree, SIGNL4, Spike.sh, Splunk On-Call, Squadcast.

**Where your reminders go.** A self-hosted service, or one whose address names its server
(ntfy, Matrix, Mattermost...), sends to that server. Amazon SNS and SES, Mailgun, SparkPost
and PagerDuty send to the region that the address chooses. Stackfield, Pushsafer, Free
Mobile, SFR, Octopush, seven, 46elks, SerwerSMS, SMS Manager, DAPNET, Brevo and ilert are
providers in the European Union. Every other service sends your reminders to its provider,
outside the European Union or without saying where. The screen says the same for each
service.

Some services are not offered, each for a reason given in the
[decision record](../adr/0064-every-apprise-service-with-a-fixed-format.md): Home Assistant
(it would need a Home Assistant token), generic webhooks, social networks that publish a
public post (Mastodon, Bluesky, X...), and services that need a file on the server or that
do not speak HTTP or SMTP.

## Choose when

A reminder says the title of the task, the home, the due date and a link: nothing else of
the task leaves HouseCairn. It goes to the person in charge of the task. When nobody is,
or when that person cannot receive it (they only read the home now, have no channel on,
or their account is deactivated), it goes to every member of the home who may change it
and has a channel on. A reader of the home receives nothing.

- The first reminder comes one day before the due date by default, from 08:00 in your
  time zone. Change both in **Reminders**.
- Then a follow-up comes every day for a high priority, every three days for a normal one,
  every week for a low one, until the task is done or skipped. Postponing it stops them
  until the new date.
- **Quiet hours**: nothing is sent between the two times; what was due goes out at their
  end.
- **Daily summary**: one message a day with every task to remind, instead of one each.
  Turned on before the time of reminders, the first one comes at that time.

Each reminder is sent once, even if the worker runs twice at the same time. When a service
fails, the reminder is not sent again; the next follow-up is.
