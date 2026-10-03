# ppa-slot-watch

Watches the booking calendar of the Estonian Police and Border Guard Board (PPA) at broneering.politsei.ee and sends an ntfy notification to the phone when an appointment slot opens before the current appointment. Booking is done by hand on the site.

By default it watches the residence permit service at the Tammsaare office in Tallinn; other offices can be added in the settings. It uses only the Python standard library and runs on Linux with Python 3.10 or later.

## Quick start

```bash
gh repo clone umutdinceryananer/ppa-slot-watch ~/ppa-slot-watch
cd ~/ppa-slot-watch
cp settings.example.py settings.py          # then set NTFY_TOPIC in settings.py
python3 -m unittest discover -s tests       # tests; no requests to the live site
python3 slot_watch.py --test-notification   # test message to the phone
python3 slot_watch.py --check-once          # one check, printed
python3 slot_watch.py                       # watch until Ctrl+C
```

For permanent use, run it as a systemd user service ([docs/03-running.md](docs/03-running.md)).

## Commands

| Command | Effect |
|---|---|
| `python3 slot_watch.py` | Checks about every 120 seconds and sends notifications |
| `python3 slot_watch.py --check-once` | Checks once, prints the earliest dates, sends nothing |
| `python3 slot_watch.py --test-notification` | Sends a test message to the ntfy topic |
| `python3 tools/check_host.py` | Checks the machine: Python, TLS, time zone, systemd, alerts |

`--settings PATH` makes `slot_watch.py` read another settings file.

## Documentation

- [docs/01-setup.md](docs/01-setup.md): Python, the ntfy app, the settings
- [docs/02-finding-ids.md](docs/02-finding-ids.md): office and service addresses, checking them with `--check-once`
- [docs/03-running.md](docs/03-running.md): terminal, systemd service, sleep and lid
- [docs/04-troubleshooting.md](docs/04-troubleshooting.md): TLS errors, HTTP 403 and 429, missing notifications
- [ppa-slot-watch-brief.md](ppa-slot-watch-brief.md): technical brief with the API findings, requirements, test plan and open assumptions

## Files

| Path | Content |
|---|---|
| `slot_watch.py` | The bot |
| `settings.example.py` | Template of `settings.py`, which is not committed |
| `certs/gogetssl-rsa-dv-ca.pem` | Intermediate certificate the site does not send |
| `systemd/ppa-slot-watch.service` | systemd user service |
| `tools/check_host.py` | Host check |
| `tests/` | Tests and sample API responses |
