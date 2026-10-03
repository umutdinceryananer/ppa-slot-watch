# Office and service addresses

Each entry in `OFFICES` holds the dates address that the booking page uses for one service at one office:

```
https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/<office id>/dates;servicePublicId=<service id>;customSlotLength=<minutes>
```

The bot reads the three values from this address and builds the address of the free times of a day from it. `settings.example.py` already holds the addresses of the residence permit service ("Applying for or extending a residence permit") at the five offices that offer it: Tammsaare in Tallinn, Tartu, Pärnu, Jõhvi and Narva. The steps below are needed only for another service, or if the IDs change.

## Copying the address in the browser

The steps are written for Firefox; Chrome works the same way.

1. Open https://broneering.politsei.ee/. Press F12, open the Network tab and type `schedule` in the filter box.
2. Select the service, then the office.
3. A request ending in `dates;servicePublicId=...;customSlotLength=...` appears. Right click it, then Copy Value, Copy URL.
4. In `settings.py`, add an entry to `OFFICES` with a `name` and the copied address as `url`.

Do not select a time and do not go on to the personal data form. Selecting a time holds the slot for up to 10 minutes.

`customSlotLength` is the length of the service in minutes, 60 for the residence permit service. A wrong value can hide free slots, so always copy it from the browser.

## IDs in the API

- Services and their IDs: `GET .../rest/schedule/serviceGroups`. Sample: `tests/fixtures/service_groups.json`.
- Offices offering a service: `GET .../rest/schedule/branches/available;servicePublicId=<service id>`. The office ID is in the field `id`. Sample: `tests/fixtures/branches_available.json`.

## Confirming with --check-once

```bash
python3 slot_watch.py --check-once
```

Example output:

```
Reported days: Tue 06.10.2026 to Mon 26.10.2026.
Tallinn Tammsaare: 25 free dates, earliest Thu 19.11.2026
  no slot in the reported days
```

The first line shows which days the bot reports, after `MIN_DAYS_AHEAD` and the school rule (`SCHOOL_EMAIL_DEADLINE`, `SCHOOL_WORKDAYS`, `BOOKING_MINUTES`). Free days before the current appointment that leave the school too little time are listed in an extra line, "free, but too close for the school".

Open the booking page, select the same service and office, and compare the first free day of the calendar with the earliest date in the output. If they match, the address is right.
