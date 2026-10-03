# ppa-slot-watch

Watches the booking calendar of the Estonian Police and Border Guard Board (PPA) at broneering.politsei.ee and sends a notification to the phone when an appointment slot opens before the current appointment. Earlier slots appear when other people cancel, and they are taken again within minutes, so the notification has to be fast and has to lead straight to the next step.

The bot only reports. Moving the appointment is done by hand on the site, with one tap on the notification, one on the time and one on the confirm button.

By default it watches the residence permit service ("Applying for or extending a residence permit") at the Tammsaare office in Tallinn. It uses only the Python standard library and runs on Linux with Python 3.10 or later; it was set up on Linux Mint 22 with Python 3.12.

## How it works

- About every two minutes the bot asks the booking API for the free dates of the service at the office, and the free times of the earliest three days that qualify. Requests go one at a time with short random pauses; errors make it wait longer, up to 15 minutes.
- A day qualifies if it is before the current appointment and leaves the school time to send its documents. The school sends them the same day if it gets an e-mail with the new date before 12:00 on a working day, so only days after that sending day are reported. Examples: a slot found on Saturday counts from Tuesday on, one found on Friday at 11:00 from Monday on, one found on Friday at 11:45 from Tuesday on.
- Each new qualifying date or time is reported once, with priority 5. A slot that disappears and comes back, for example because someone else held it for 10 minutes, is reported again.
- Other messages: one at startup with the current state, one status message every morning at 09:00, one when checks keep failing and one when they work again.
- The site does not send its intermediate TLS certificate, which Python on Linux needs; the project ships it in `certs/`.

## When a notification arrives

```
Earlier slot, Tallinn Tammsaare, 06.10
Tallinn Tammsaare
Tue 06.10.2026  09:15, 10:15
Current appointment 27.10.2026. Tap to open it, then "I want to reschedule my appointment".
Book and email the school the new date before 12:00 on Mon 05.10.2026.
[Reschedule]  [Email school]
```

1. Tap the notification. Your own appointment page opens, in English: the same page as the link in the confirmation e-mail.
2. Tap "I want to reschedule my appointment". The calendar opens with the first free day selected, normally the day from the notification.
3. Tap the time from the notification, then "Reschedule appointment". There is no form: your name and contact details are already part of the appointment. Selecting a time holds it for 10 minutes.
4. Go back to the notification and tap "Email school" (on iPhone, press and hold the notification to see the buttons). The phone's default mail app opens with an e-mail to study@taltech.ee that names the new date and time. Make the app that holds your TalTech account the default: with Outlook, Settings, Apps, Default Apps, Email, Outlook (on older iOS: Settings, Outlook, Default Mail App). Check the time and send it before the moment in the last line of the notification.
5. Set `CURRENT_APPOINTMENT` in `settings.py` to the new date and restart the bot (`systemctl --user restart ppa-slot-watch`), or stop it. If the confirmation e-mail of the moved appointment has a different link, put it into `APPOINTMENT_LINK`.
6. Have the documents ready for the earlier day: passport, application form, family information form, proof of payment of the state fee, a 40x50 mm colour photo, proof of income (bank statements; ask the migration advisor about translation) and the student status certificate from your study consultant. The school sends its invitation document to the office itself.

This needs the appointment link in `settings.py` (next section).

To try it before a real slot appears, run `python3 slot_watch.py --test-notification`. Tapping the test message opens your real appointment page: look at it, you may also open "I want to reschedule my appointment", but do not select a time and do not cancel. Its "Email school" draft has a subject starting with `[TEST]`: close it without sending and delete the draft.

## The appointment link

The PPA confirmation e-mail ends with "You can modify or cancel the appointment at https://broneering.politsei.ee/qmaticwebbooking/#/...". Put that link into `settings.py` and restart the bot:

```python
APPOINTMENT_LINK = "https://broneering.politsei.ee/qmaticwebbooking/#/<long id from the e-mail>"
```

Anyone who has this link can change or cancel the appointment. It is therefore kept only in `settings.py`, which is not committed, and the bot never prints it. It does travel inside slot notifications through the ntfy server, so the ntfy topic has to stay secret; this was accepted for the faster flow.

Without `APPOINTMENT_LINK`, tapping a notification opens the booking calendar for a new appointment instead, with the office, the service and the first free day selected. Booking there needs the form (first name, last name, date of birth, e-mail, phone; the phone's AutoFill fills all but the date of birth), and because the site allows only one active appointment, it asks to cancel the current one first. If the 10-minute hold of the new time runs out meanwhile, both may be lost.

## Quick start

```bash
gh repo clone umutdinceryananer/ppa-slot-watch ~/ppa-slot-watch
cd ~/ppa-slot-watch
cp settings.example.py settings.py          # then set NTFY_TOPIC and APPOINTMENT_LINK in settings.py
python3 tools/check_host.py                 # checks Python, TLS, time zone, systemd
python3 -m unittest discover -s tests       # tests; no requests to the live site
python3 slot_watch.py --test-notification   # test message to the phone
python3 slot_watch.py --check-once          # one check, printed
```

Then install the systemd user service ([docs/03-running.md](docs/03-running.md)). The ntfy app has to be installed on the phone and subscribed to the topic ([docs/01-setup.md](docs/01-setup.md)).

## Commands

| Command | Effect |
|---|---|
| `python3 slot_watch.py` | Watches and sends notifications, normally run by the systemd service |
| `python3 slot_watch.py --check-once` | Checks once, prints the reported days, the earliest dates and slots that are too close; sends nothing |
| `python3 slot_watch.py --test-notification` | Sends a test message with the buttons of a slot message for a sample slot; the e-mail draft is marked `[TEST]` and is not meant to be sent |
| `python3 tools/check_host.py` | Checks the machine; `--desktop-test` and `--ntfy-topic TOPIC` add alert tests |
| `systemctl --user restart ppa-slot-watch` | Restarts the service, for example after changing `settings.py` |
| `journalctl --user -u ppa-slot-watch -f` | Follows the log |

`--settings PATH` makes `slot_watch.py` read another settings file.

## Settings

All settings are in `settings.py`, which is not committed because it holds the ntfy topic and the appointment link. Settings missing from it use the defaults of `settings.example.py`. The ones most likely to change:

| Setting | Default | Meaning |
|---|---|---|
| `CURRENT_APPOINTMENT` | `"2026-10-27"` | Only days before this date are reported |
| `NTFY_TOPIC` | placeholder | Your ntfy topic |
| `APPOINTMENT_LINK` | `None` | The "modify or cancel" link of the confirmation e-mail; with it, a notification opens your appointment page |
| `SCHOOL_EMAIL_DEADLINE` | `"12:00"` | The school must get the e-mail before this time on a working day |
| `SCHOOL_WORKDAYS` | `0` | Working days the school needs after the e-mail; raise to 1 if it is ever late |
| `BOOKING_MINUTES` | `30` | Time you need from a notification to the e-mail |
| `SCHOOL_EMAIL` | `"study@taltech.ee"` | Address of the "Email school" button |
| `BOOKING_LANGUAGE` | `"en_en"` | Language of the booking pages opened from a notification; `"et_ee"` for Estonian |

The full list is in [docs/01-setup.md](docs/01-setup.md).

## Limits

- The bot never books or moves anything, and it cannot do anything about slots that others take faster.
- Only weekends are treated as days off. No Estonian public holiday falls before 27.10.2026; for later dates, raise `SCHOOL_WORKDAYS` around holidays.
- On 3 October 2026 the appointment page and the reschedule page opened on a computer with the real link, without selecting anything. On the phone, opening the reschedule address directly failed once ("Something went wrong with your appointment"), so the notification opens the appointment page instead. Moving the appointment itself has not been tried yet.
- The machine has to stay on, online and plugged in; with the lid closed, the XFCE power settings must not suspend it ([docs/03-running.md](docs/03-running.md)).

## Documentation

- [docs/01-setup.md](docs/01-setup.md): Python, the ntfy app, all settings
- [docs/02-finding-ids.md](docs/02-finding-ids.md): office and service addresses, checking them with `--check-once`
- [docs/03-running.md](docs/03-running.md): terminal, systemd service, sleep and lid
- [docs/04-troubleshooting.md](docs/04-troubleshooting.md): TLS errors, HTTP 403 and 429, missing notifications
- [ppa-slot-watch-brief.md](ppa-slot-watch-brief.md): technical brief with the API findings, requirements, test plan and open assumptions

## Files

| Path | Content |
|---|---|
| `slot_watch.py` | The bot |
| `settings.example.py` | Template of `settings.py` |
| `certs/gogetssl-rsa-dv-ca.pem` | Intermediate certificate the site does not send |
| `systemd/ppa-slot-watch.service` | systemd user service |
| `tools/check_host.py` | Host check |
| `tests/` | Tests and sample API responses |
