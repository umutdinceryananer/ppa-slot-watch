# Setup

## Python

The bot needs Python 3.10 or later and nothing outside the standard library, so no virtual environment and no pip packages. Linux Mint 21 ships Python 3.10, Linux Mint 22 ships Python 3.12.

```bash
python3 --version
```

## Getting the code

The repository is private. Log in to GitHub once, then clone it:

```bash
sudo apt install gh
gh auth login
gh repo clone umutdinceryananer/ppa-slot-watch ~/ppa-slot-watch
```

Later updates: `cd ~/ppa-slot-watch && git pull`.

## Checking the machine

`tools/check_host.py` checks Python, the TLS setup, one request to the booking site, the time zone, systemd, the desktop alerts and, when a topic is given, ntfy. Run it from a terminal inside the desktop session:

```bash
python3 tools/check_host.py --desktop-test --ntfy-topic YOUR_TOPIC
```

Each output line starts with PASS, FAIL, WARN, INFO or SKIP and the ID of the assumption it checks (section 7.2 of the brief).

## ntfy app

1. Install the ntfy app on the phone (Google Play, F-Droid or the App Store).
2. Choose a topic name that is hard to guess, for example `ppa-trp-` followed by 12 random letters and digits. Anyone who knows the name can read the messages. They contain only office, date and time.
3. In the app, subscribe to the topic on the server `https://ntfy.sh`.
4. In the notification settings of the topic, make sure that priority 5 messages make a sound. If they should also come through in Do Not Disturb mode, allow that for the app.

Priorities used by the bot:

| Priority | Message |
|---|---|
| 5 | New earlier slot; startup message that lists earlier slots |
| 4 | Checks failing; bot stopped by an error |
| 3 | Startup; checks working again; test message |
| 2 | Daily status |

## Settings

```bash
cp settings.example.py settings.py
```

Edit `settings.py`. It is a Python file: texts need quotes, and `None`, `True` and `False` are written as shown. `settings.py` is in `.gitignore` because it holds the topic.

| Setting | Default | Meaning |
|---|---|---|
| `CURRENT_APPOINTMENT` | `"2026-10-27"` | Only days before this date are reported |
| `MIN_DAYS_AHEAD` | `1` | First day to report, counted from today; `0` includes today, with times at least 60 minutes away |
| `SCHOOL_EMAIL_DEADLINE` | `"12:00"` | The school sends its documents the same day if it gets your email with the new date before this time on a working day; only days after that sending day are reported; `None` turns this off |
| `SCHOOL_WORKDAYS` | `0` | Working days the school needs after the email day; `0` means the same day |
| `BOOKING_MINUTES` | `30` | Minutes you need after a notification to book and email the school |
| `BOOKING_LANGUAGE` | `"en_en"` | Language of the booking page opened from a notification: `"en_en"` English, `"et_ee"` Estonian, `None` the site's default (Estonian) |
| `SCHOOL_EMAIL` | `"study@taltech.ee"` | Address of the "Email school" button; `None` removes the button |
| `SCHOOL_EMAIL_SUBJECT` | see `settings.example.py` | Subject of that e-mail; `{date}`, `{time}`, `{office}` and `{current}` are filled in |
| `SCHOOL_EMAIL_BODY` | see `settings.example.py` | Text of that e-mail, same placeholders; no name or student number, the text travels through ntfy |
| `OFFICES` | Tammsaare | Offices to watch, see [02-finding-ids.md](02-finding-ids.md) |
| `CHECK_INTERVAL_SEC` | `120` | Seconds between checks, at least 60; every wait varies by up to 15% |
| `TIME_WINDOW` | `None` | For example `("09:00", "15:00")`; both ends included |
| `WEEKDAYS` | `None` | For example `[0, 2, 4]` for Monday, Wednesday and Friday |
| `NTFY_SERVER` | `"https://ntfy.sh"` | ntfy server |
| `NTFY_TOPIC` | `"change-me"` | Your topic; the bot does not start with the placeholder |
| `DAILY_REPORT_HOUR` | `9` | Hour of the daily status message; `None` turns it off |
| `ERROR_ALERT_THRESHOLD` | `5` | Failed checks in a row before an error message |
| `DESKTOP_ALERTS` | `True` | Desktop notification and sound with `notify-send` and `paplay` |
| `USER_AGENT` | names the bot | User-Agent header sent to the site |
| `EXTRA_CA_FILE` | `"certs/gogetssl-rsa-dv-ca.pem"` | Intermediate certificate the site does not send |

The bot checks the settings at startup. A wrong value stops it with a message that names the setting. After a change, check the result:

```bash
python3 slot_watch.py --check-once
```
