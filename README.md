# ppa-slot-watch

Watches the booking calendar of the Estonian Police and Border Guard Board (PPA) at broneering.politsei.ee and sends a notification to the phone when an appointment slot opens before the current appointment. Earlier slots appear when other people cancel, and they are taken again within minutes, so the notification has to be fast and has to say exactly what to do.

The bot only reports. Booking, or moving the existing appointment, is done by hand on the site, because the confirmation step has a CAPTCHA and needs personal data.

By default it watches the residence permit service ("Applying for or extending a residence permit") at the Tammsaare office in Tallinn. It uses only the Python standard library and runs on Linux with Python 3.10 or later; it was set up on Linux Mint 22 with Python 3.12.

## How it works

- About every two minutes the bot asks the booking API for the free dates of the service at the office, and the free times of the earliest three days that qualify. Requests go one at a time with short random pauses; errors make it wait longer, up to 15 minutes.
- A day qualifies if it is before the current appointment and leaves the school time to send its documents. The school sends them the same day if it gets an e-mail with the new date before 12:00 on a working day, so only days after that sending day are reported. Examples: a slot found on Saturday counts from Tuesday on, one found on Friday at 11:00 from Monday on, one found on Friday at 11:45 from Tuesday on.
- Each new qualifying date or time is reported once, with priority 5. A slot that disappears and comes back, for example because someone else held it for 10 minutes, is reported again.
- Other messages: one at startup with the current state, one status message every morning at 09:00, one when checks keep failing and one when they work again.
- The site does not send its intermediate TLS certificate, which Python on Linux needs; the project ships it in `certs/`.

## A notification

```
Earlier slot, Tallinn Tammsaare, 06.10
Tallinn Tammsaare
Tue 06.10.2026  09:15, 10:15
Current appointment 27.10.2026. Tap to book.
Book and email the school the new date before 12:00 on Mon 05.10.2026.
[Open calendar]  [Email school]
```

- Tapping the notification, or "Open calendar", opens the booking page in English (`BOOKING_LANGUAGE`) with the office and the service already selected, directly at the calendar.
- "Email school" opens the mail app with an e-mail to the school (study@taltech.ee) that already names the new date and time. The earliest time of the day is filled in; correct it if you take another one.
- On iPhone, press and hold the notification, or pull it down, to see the buttons.
- The last line of the text is the latest moment for the e-mail to the school. After that the slot is too close.
- To try the buttons before a real slot appears, run `python3 slot_watch.py --test-notification`. It sends a test message with both buttons for a sample slot. Its "Email school" draft has a subject starting with `[TEST]`: look at it, then close it without sending and delete the draft.

## When a notification arrives

1. Move the existing appointment instead of booking a second one. Open your appointment page (the "modify or cancel" link of the confirmation e-mail, best as a home screen shortcut, see below), choose "I want to reschedule my appointment", pick the new date and time and confirm. The site most likely allows only one active appointment per service, so a second booking may be refused. Selecting a time holds it for 10 minutes.
2. If moving is not offered, book with "Open calendar". If the site asks to cancel the existing appointment first, it holds the new time for 10 minutes while you do so.
3. Tap "Email school", check the date and time, and send it before the time in the last line of the notification.
4. Set `CURRENT_APPOINTMENT` in `settings.py` to the new date and restart the bot (`systemctl --user restart ppa-slot-watch`), or stop it.
5. Have the documents ready for the earlier day: passport, application form, family information form, proof of payment of the state fee, a 40x50 mm colour photo, proof of income (bank statements; ask the migration advisor about translation) and the student status certificate from your study consultant. The school sends its invitation document to the office itself.

## Home screen shortcut to your appointment page

The confirmation e-mail of the current appointment ends with a link that opens the page to modify or cancel it. Anyone who has this link can cancel the appointment, so it is never put into a notification, a setting or this repository. Keep it only on your phone, as a home screen icon.

The page opens in Estonian unless the address ends with `?lang=en_en`. Add these characters to the end of the link before saving it, so that it looks like `https://broneering.politsei.ee/qmaticwebbooking/#/<long id>?lang=en_en`:

- iPhone, Safari: open the link in Safari. Tap the address bar, move to the end of the address, type `?lang=en_en` and tap "Go"; the page reloads in English. Then tap the Share button (the square with an arrow pointing up), scroll down, tap "Add to Home Screen", give it a name such as "PPA appointment" and tap "Add".
- Android, Chrome: open the link in Chrome, add `?lang=en_en` to the end of the address in the same way and open it. Then tap the menu with the three dots, "Add to Home screen" and "Add".

To try it without changing anything: open the shortcut, tap "I want to reschedule my appointment", look at the calendar and leave without selecting a time. Do not press cancel.

## Quick start

```bash
gh repo clone umutdinceryananer/ppa-slot-watch ~/ppa-slot-watch
cd ~/ppa-slot-watch
cp settings.example.py settings.py          # then set NTFY_TOPIC in settings.py
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
| `python3 slot_watch.py --test-notification` | Sends a test message with both buttons for a sample slot; the e-mail draft is marked `[TEST]` and is not meant to be sent |
| `python3 tools/check_host.py` | Checks the machine; `--desktop-test` and `--ntfy-topic TOPIC` add alert tests |
| `systemctl --user restart ppa-slot-watch` | Restarts the service, for example after changing `settings.py` |
| `journalctl --user -u ppa-slot-watch -f` | Follows the log |

`--settings PATH` makes `slot_watch.py` read another settings file.

## Settings

All settings are in `settings.py`, which is not committed because it holds the ntfy topic. Settings missing from it use the defaults of `settings.example.py`. The ones most likely to change:

| Setting | Default | Meaning |
|---|---|---|
| `CURRENT_APPOINTMENT` | `"2026-10-27"` | Only days before this date are reported |
| `NTFY_TOPIC` | placeholder | Your ntfy topic |
| `SCHOOL_EMAIL_DEADLINE` | `"12:00"` | The school must get the e-mail before this time on a working day |
| `SCHOOL_WORKDAYS` | `0` | Working days the school needs after the e-mail; raise to 1 if it is ever late |
| `BOOKING_MINUTES` | `30` | Time you need from a notification to the e-mail |
| `SCHOOL_EMAIL` | `"study@taltech.ee"` | Address of the "Email school" button |
| `BOOKING_LANGUAGE` | `"en_en"` | Language of the booking page opened from a notification; `"et_ee"` for Estonian |

The full list is in [docs/01-setup.md](docs/01-setup.md).

## Limits

- The bot never books, and it cannot do anything about slots that others take faster.
- Only weekends are treated as days off. No Estonian public holiday falls before 27.10.2026; for later dates, raise `SCHOOL_WORKDAYS` around holidays.
- That rescheduling works and that only one appointment per service is allowed were read from the site's code and configuration, not tried with a real appointment.
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
