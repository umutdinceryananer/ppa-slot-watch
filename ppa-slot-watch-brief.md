# PPA appointment slot watcher

Technical brief for the bot to be developed with Claude Code. Prepared on 2 October 2026 and updated the same day with the results of the live verification (sections 2, 3 and 7).

The document has two parts. The first part covers the API of the broneering.politsei.ee booking system. The second part covers the requirements, design and test plan of the bot that build on those findings. The findings were first compiled from public sources, because the first automated read of the site failed with a TLS error (explained in 2.5). On 2 October 2026 they were checked on the live site through the booking UI and a few single requests. Each finding carries its status.

| Status label | Meaning |
|---|---|
| verified | Checked on the live site on 2 October 2026 |
| used in code | Present in the code of a working open source project dated 2026 |
| inferred | Derived from the Qmatic API pattern seen in another project |
| unverified | Mentioned in a guide, currency or accuracy unknown |

## 1. Goal and scope

The user has a TRP application appointment at the Tammsaare office in Tallinn on 27.10.2026 at 15:15. When a slot opens at the Tallinn office before that date, the bot sends an ntfy notification to the phone. The user books manually.

User preferences

- Only the Tallinn office is watched. For the residence permit service this is the Tammsaare service office, the only Tallinn office that offers it (see 2.3).
- Notification channel is ntfy (ntfy app on the phone).
- The bot runs continuously on a Huawei MateBook with Linux Mint XFCE.
- Everything in the project is in English: code, comments, user-facing messages, settings, command line options, file names and documentation.
- Before the appointment, the school sends documents about the user to the office. A new appointment must leave the school enough working days for that, so days that are too close are not reported (4.2).

Out of scope

- Automatic booking. The booking endpoints cannot be written without trying them, trying them creates a real booking, the confirmation step has a CAPTCHA (`captchaEnabled: true`, see 2.6) and personal data has to be sent.
- Offices outside Tallinn. The settings structure must allow adding other offices (their IDs are in 2.3), but this version watches only Tallinn.
- Browser automation (Playwright, Selenium). Direct HTTP requests to the API are enough, and the machine has 8 GB RAM.

## 2. Booking system findings

### 2.1 General structure

- broneering.politsei.ee runs on Qmatic Web Booking. `https://broneering.politsei.ee/` redirects to the booking UI at `https://broneering.politsei.ee/qmaticwebbooking/#/`. [verified]
- The REST API used by the UI lives under the same application at `/qmaticwebbooking/rest/schedule/`. [verified]
- The schedule endpoints need no login, cookie or token. Plain GETs without cookies to the dates, times and list endpoints returned the same data as the UI. [verified]
- Parameters are passed as matrix parameters appended to a path segment with semicolons (`;a=b`), not as a query string (`?a=b`). Do not use `urlencode` when building URLs, `;` and `=` must not be encoded. In a shell, put the URL in single quotes, otherwise `;` is read as a command separator. [verified]
- Service and office names come in English and Estonian in the `custom` field of the API responses. [verified]
- The booking page has a "Change / cancel appointment" button, so changes and cancellations happen in the same UI. The cancel page of the old ASP.NET system (`/Reservations/Cancel`) mentioned in older guides is not needed. [verified for the button]
- The residence permit service is listed as "Applying for or extending a residence permit" (Estonian "Elamisloa taotlemine või pikendamine"), third in the list. [verified]

### 2.2 Endpoints

All paths below are relative to `https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/`. Sample responses are in `tests/fixtures/`.

Available dates [verified]

```
GET branches/{branchPublicId}/dates;servicePublicId={servicePublicId};customSlotLength={n}
```

The response is a plain JSON list without a wrapper. Each item is an object with a `date` field holding an ISO date (`YYYY-MM-DD`). Fixture: `tests/fixtures/dates.json`. Days without free times are missing from the list: on 2 October 2026, 14.10.2026 and 02.12.2026, two weekdays missing from the list, both returned an empty time list. [verified] Some missing days are closures, for example 26.11.2026, the last Thursday of the month.

```json
[{"date":"2026-11-19"},{"date":"2026-11-20"},{"date":"2026-11-23"}]
```

Free times on a day [verified]

```
GET branches/{branchPublicId}/dates/{YYYY-MM-DD}/times;servicePublicId={servicePublicId};customSlotLength={n}
```

The path inferred from the Qmatic Calendar Public API was correct. The open-forms Qmatic client uses the same pattern there (`v2/branches/{id}/dates/{day}/times`) with `{"times": [...]}` wrappers, while the web booking layer returns a plain list of objects with `date` and `time` fields. When an office is selected, the UI requests the dates and then, by itself, the times of the first free date. Fixture: `tests/fixtures/times.json`. A day without free times returns an empty list `[]` with status 200 (fixture `tests/fixtures/times_empty.json`). The UI shows exactly the times the API returns (S1 in 7.2).

```json
[{"date":"2026-11-19","time":"09:15"},{"date":"2026-11-19","time":"10:15"}]
```

Service list [verified]

```
GET serviceGroups
```

A list with one group (`"id": "Services in right order"`). Its `services` list holds each service with `publicId`, `name` (Estonian), `duration` and `additionalDuration` in minutes, and `custom`, a JSON string with the English and Estonian names. Fixture: `tests/fixtures/service_groups.json`.

Offices offering a service [verified]

```
GET branches/available;servicePublicId={servicePublicId}
```

The response is wrapped: `{"value": [...]}`. Each office has `id` (the branchPublicId; the field name is not `publicId`), `name`, `addressLine1`, `addressCity`, `timeZone` (`Europe/Tallinn`) and `custom` with the English name. Fixture: `tests/fixtures/branches_available.json`.

Other requests the UI sends on page load: `configuration`, `serviceTemplates`, `customer`, `uiMessages?lang=en_en`, `validateOnLoad` and `appointmentProfiles/`. The bot does not need them. `configuration` holds the booking rules quoted in 2.6. [verified]

UI routes, read from the app script `assets/index-*.js` on 3 October 2026 [verified]: `#/preselect/branch/{branchPublicId}/services/{servicePublicId}` opens the booking page with the office and the service selected, directly at the calendar; it was tried in the browser, and `restrictUrl: false` in the configuration allows it. `#/{appointmentId}` is the page of an existing appointment, the "modify or cancel" link of the confirmation e-mail, and `#/{appointmentId}/reschedule` moves the appointment to a new date and time. The appointment link lets anyone change or cancel the appointment, so the bot never sends it.

Booking and confirmation endpoints were not examined, they are out of scope. Selecting a time in the UI may hold the slot, so the verification stopped at the date step.

### 2.3 Known IDs

Source: the API responses in 2.2, read on 2 October 2026. All IDs are 64-character hexadecimal strings.

| Value | Content | Status |
|---|---|---|
| servicePublicId, residence permit | `b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40` | verified |
| customSlotLength, residence permit | `60` | verified |

- The UI sends `customSlotLength=60` for the residence permit service. This equals the service `duration`. The UI has no person selector and booking for several people is disabled (`multiplePeopleEnabled: false`), so the value is not expected to change.
- The reference project's servicePublicId `3af778a300a86b1d0cb5556f993ab98adfa1a9debaac3c231026c5cb8425fce2` belongs to "Applying for temporary protection (primary)", whose duration is 120 minutes. Its `customSlotLength=120` matches that. These values must not be used for TRP.
- All other services and their IDs are in `tests/fixtures/service_groups.json`.

Offices offering the residence permit service

| Office | Address | branchPublicId |
|---|---|---|
| Tammsaare Service Office | A. H. Tammsaare tee 47, Tallinn | `89f89ac30f7f6329397e447102ce1ed13e5459eaa5a630c071d0577bdae6600a` |
| Tartu Service Office | Riia mnt. 132, Tartu | `7eddbbbfe3cacf5100f4fcf0c8c7b156ca80749142abefb3e7909873bd396011` |
| Pärnu Service Office | A. H. Tammsaare pst 61, Pärnu | `bdfdc72ede1f3a9aafa54ac48ddbdd0658ca07677d34b3e0665ba69baab406d8` |
| Jõhvi Service Office | Rahu 38, Jõhvi | `a109dfb325ff0fb78d217aa76de53a6722a572fac190f3e4f3ab6ca64c886ba7` |
| Narva Service Office | Vahtra 3, Narva | `9f9a45d6e00fbaa0191af2ba26bde6d4aac666f045d3ef99fa3c4cc06cd557a6` |

- The reference project's single Tallinn entry is the Tammsaare office. Its Tartu, Pärnu and Jõhvi IDs are also correct.
- Tammsaare is the only Tallinn office that offers the residence permit service. The Pinna office mentioned in guides is not in the list for this service.
- Tartu, Pärnu, Jõhvi and Narva are not watched in this version.

### 2.4 Request headers

The bot sends the headers below. No cookie and no session.

```
Accept: application/json, text/plain, */*
Accept-Language: en-GB,en-US;q=0.9,en;q=0.8
Referer: https://broneering.politsei.ee/qmaticwebbooking/
User-Agent: Mozilla/5.0 (X11; Linux x86_64) ppa-slot-watch/1.0
```

- Single requests without cookies and with a User-Agent that names the bot (`ppa-randevu-bot/1.0` and `ppa-slot-watch/1.0`) got status 200 and the same data as the UI. [verified]
- Responses are `application/json;charset=UTF-8` with `Cache-Control: no-store`, so no HTTP cache sits between the bot and the data. [verified]
- Whether the server blocks by request rate is unknown. The User-Agent can be changed in the settings.

### 2.5 TLS certificate chain

Findings [verified]

- The server sends only its own certificate. `openssl s_client -showcerts` lists a single certificate (`0 s:CN=broneering.politsei.ee`, issuer `CN=GoGetSSL RSA DV CA`) and reports `Verify return code: 21 (unable to verify the first certificate)`.
- The site's certificate is valid from 23.02.2026 to 01.02.2027. The intermediate will not change before the certificate is renewed.
- The certificate's AIA extension gives the address of the intermediate: `http://crt.usertrust.com/GoGetSSLRSADVCA.crt` (caIssuers, DER, `application/pkix-cert`). OCSP: `http://ocsp.usertrust.com`.
- The intermediate "GoGetSSL RSA DV CA" is signed by "USERTrust RSA Certification Authority", which is in the Mozilla store. It is valid until 05.09.2028.
- This explains why the reference project uses the `truststore` package and has the error message "Python could not build a trusted HTTPS certificate chain".

Platform effects

- Browsers download a missing intermediate from the AIA address or complete the chain from a cache. The site works normally in a browser.
- On macOS and Windows, `truststore` and tools that use the OS verifier (for example curl with Schannel on Windows) complete the chain the same way.
- On Linux, Python and curl verify with OpenSSL and do not follow AIA, and `truststore` does not help. On the MateBook every request is expected to fail without the intermediate. OpenSSL-based tools fail on any platform; the openssl of Git for Windows did.
- Python on Windows also loads the Windows certificate stores. With them, `create_default_context()` verified the site without the intermediate (2 October 2026), so a TLS test on the Windows development machine does not prove the MateBook works. To simulate the MateBook, Python on Windows was run with only the Mozilla roots and `VERIFY_X509_PARTIAL_CHAIN` cleared: the handshake failed with `unable to get local issuer certificate` without the intermediate and succeeded with it (Python 3.14, OpenSSL 3.0). This is a simulation. The confirmation on the MateBook is `tools/check_host.py` (3.3) and `--check-once`.

Solution

The intermediate is shipped with the project as `certs/gogetssl-rsa-dv-ca.pem`. It was downloaded from the AIA address on 2 October 2026, converted to PEM and checked with `openssl verify` against the Mozilla CA bundle. The file header records its subject, issuer, validity and SHA-256 fingerprint. The bot loads it in addition to the system store:

```python
ctx = ssl.create_default_context()
ctx.verify_flags &= ~ssl.VERIFY_X509_PARTIAL_CHAIN
ctx.load_verify_locations(cafile=EXTRA_CA_FILE)
```

- `ssl.create_default_context(cafile=...)` is not used, because then the system store is not loaded.
- `VERIFY_X509_PARTIAL_CHAIN` is cleared. Python 3.13 and later set it in `create_default_context()` (3.12 and earlier do not). When it is set, the added intermediate alone becomes a trust anchor. With the flag cleared, the chain must end at a root from the system store on every Python version.
- Python 3.13 and later also set `VERIFY_X509_STRICT`. If it rejects a chain, it may be cleared. It does not turn off signature or chain checks, it only relaxes RFC 5280 format checks.
- Running with `CERT_NONE`, `check_hostname=False` or `verify=False` is not acceptable.

Renewal. If the site's certificate is renewed by a different intermediate, verification fails again and the bot's TLS error message points here. To get the new intermediate, read the caIssuers address, download the file, convert it and verify it:

```bash
openssl s_client -connect broneering.politsei.ee:443 -servername broneering.politsei.ee </dev/null 2>/dev/null \
  | openssl x509 -noout -ext authorityInfoAccess
curl -sS -o intermediate.crt '<caIssuers URL>'
openssl x509 -inform DER -in intermediate.crt -out intermediate.pem
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt intermediate.pem
```

Alternative: in Firefox, padlock, Connection secure, More information, View Certificate, then "PEM (chain)" under Miscellaneous. Keep only the intermediate from that file.

Automatic AIA chasing (not planned for the first version)

If the manual file becomes a burden, AIA chasing can be implemented in `tls_chain.py`. On a verification error, the server certificate is read over an unverified connection, the intermediate is downloaded from the `caIssuers` address, added with `load_verify_locations(cadata=...)` and the request is repeated. Rules:

- Only certificates that are not self-signed (issuer differs from subject) are added. The root must always come from the system store.
- `VERIFY_X509_PARTIAL_CHAIN` is cleared, as above.
- On Python 3.10 to 3.12, `getpeercert(binary_form=True)` returns only the leaf. On Python 3.13 and later, `get_unverified_chain()` returns the whole chain sent by the server as a list of DER bytes.
- The AIA extension can be read with the standard library. A small DER parser is enough (extension OID 1.3.6.1.5.5.7.1.1, caIssuers OID 1.3.6.1.5.5.7.48.2, URI tag 0x86). The `cryptography` package is the alternative.
- A caIssuers address may return DER or PKCS#7 (`.p7c`). The GoGetSSL address returns DER.
- The unverified connection is used only to read the certificate, never for data requests.

### 2.6 Booking rules and context

- Values from the `configuration` endpoint [verified]:
  - `maxTotal: 2`; `globalRestrictEnabled: true` with `globalRestrictValue: 3`; `branchRestrictEnabled: true` with `branchRestrictValue: 3`; `serviceRestrictEnabled: true` with `serviceRestrictValue: 1`. The UI messages say "You have maximum allowed number of appointments. If you want to proceed, you have to delete one or several of your existing appointments." and "Your appointment has been cancelled, you can now proceed with the current one." The most likely reading is one active appointment per service, so a second residence permit appointment would be refused while the current one exists (B1 in 7.2). Moving the appointment avoids this (B3). The earlier reading of `maxTotal: 2` as two allowed appointments, like the Study in Estonia article, does not fit the per-service limit. MoveMyTalent's guide also suggests that a second appointment under the same name may be blocked. [unverified]
  - `multiplePeopleEnabled: false`, `maxAdults: 1`. One person per booking.
  - `captchaEnabled: true`. The booking flow uses reCAPTCHA, and its badge is visible on the page.
  - `reservationExpiryTimeSeconds: "600"`, `allowReservationExtension: false`, `reservationCountdownPopupDuration: 30`. Selecting a time most likely reserves it for 10 minutes, without extension (B2 in 7.2).
  - `maxReschedules: -1`, `rescheduleFutureDays: -1`, `cancelTimeEnabled: false`. No visible limit on rescheduling and no cancellation deadline, so moving the existing appointment may be possible (B3 in 7.2).
  - `customerIdentificationEnabled: false`, `validateEmail: false`. No identity check when booking, and no e-mail check when rescheduling; the reschedule page shows it only with `validateEmail`. How the limits above recognise a person is unknown (B1 in 7.2).
- The UI says "You are allowed to book an appointment at one client service office at a time." [verified]
- Appointments can be booked at most three months ahead (TalTech, PPA student guide). On 2 October 2026 the last listed date for Tammsaare was 30.12.2026, which fits.
- Snapshot on 2 October 2026 around 13:00 Tallinn time: the earliest free date for the residence permit service at Tammsaare was 19.11.2026, with hourly times from 09:15 to 15:15, and 25 free dates up to 30.12.2026. Nothing before 27.10.2026, so the bot waits for cancellations. [verified]
- According to Study in Estonia, cancellations are unlimited and no confirmation e-mail is sent for a cancellation. The article may refer to the old system. [unverified]
- Cancelled slots appear in the calendar immediately and fill quickly (Study in Estonia). The reference project polls every 60 seconds, so other automated tools watching the same calendar should be assumed.
- The Tammsaare office is open on weekdays from 09.00 to 17.00 and closed on the last Thursday of each month (PPA).
- Appointments can also be booked by phone, +372 612 3000 (TalTech).
- According to Study in Estonia, Pärnu, Narva and Jõhvi usually have more free slots.

## 3. Verification before coding

3.1 and 3.2 were done on 2 October 2026 from the Windows development machine, with the booking UI in Chrome and single requests with curl and openssl. The results are in sections 2 and 7. 3.3 is done on the MateBook. The steps stay here for checking again later, for example if the IDs change.

### 3.1 Collecting IDs and sample responses with DevTools

The steps are written for Firefox, Chrome works the same way.

1. Open `https://broneering.politsei.ee/`. Press F12, go to the Network tab and type `schedule` in the filter box.
2. Select "Applying for or extending a residence permit", then "Tammsaare Service Office".
3. The service list comes from `serviceGroups` (loaded with the page) and the office list from `branches/available;servicePublicId=...`. Save the responses under `tests/fixtures/`.
4. When the office is selected, a `dates;servicePublicId=...` request appears. Right click, Copy Value, Copy URL. Compare `servicePublicId` and `customSlotLength` with the table in 2.3. Save the response as `tests/fixtures/dates.json`.
5. The UI then requests the times of the first free date by itself. Save the URL and the response as `tests/fixtures/times.json`. Do not select a time, because that may hold the slot.
6. Do not go to the personal data form. Fixtures must not contain personal data.

Note for Claude Code: the Claude in Chrome extension hides 64-character hexadecimal values in its output, so the IDs were read from responses saved with curl.

### 3.2 Single-request check

```bash
# 1. Chain sent by the server and the OpenSSL verify result
openssl s_client -connect broneering.politsei.ee:443 -servername broneering.politsei.ee -showcerts </dev/null 2>/dev/null \
  | grep -E '^ *[0-9]+ s:|^ *i:|Verify return code'

# 2. A single dates request
curl -sS \
  -H 'Accept: application/json, text/plain, */*' \
  -H 'Referer: https://broneering.politsei.ee/qmaticwebbooking/' \
  'https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/89f89ac30f7f6329397e447102ce1ed13e5459eaa5a630c071d0577bdae6600a/dates;servicePublicId=b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40;customSlotLength=60'
```

Result on 2 October 2026: the first command shows only the `0 s:` line and `Verify return code: 21`, so the server does not send the intermediate (see 2.5). The second command returned the same 25 dates as the UI, because curl with Schannel on Windows completes the chain through AIA.

On Linux the second command is expected to fail with `curl: (60)`. `--cacert` replaces the system store, so the intermediate has to be given together with the system roots, for example `--cacert <(cat /etc/ssl/certs/ca-certificates.crt certs/gogetssl-rsa-dv-ca.pem)`. Neither was tried on Linux. On the MateBook the checks that matter are 3.3 and `python3 slot_watch.py --check-once` (see 4.6).

### 3.3 Checking the MateBook

`tools/check_host.py` checks the M assumptions in 7.2. It needs only the standard library and Python 3.10 or later. It reads settings, opens three TLS connections to the booking site and sends one dates request. `--desktop-test` shows a desktop notification and plays a sound, once from the terminal and once from a transient user service, which has the same environment as the bot's service. `--ntfy-topic` sends one test message; the topic is not printed. The script embeds a copy of the intermediate, so it also works when it is copied on its own.

Run it from a terminal inside the desktop session:

```bash
cd ~/ppa-slot-watch
python3 tools/check_host.py --desktop-test --ntfy-topic '<topic>'
```

Each output line starts with PASS, FAIL, WARN, INFO or SKIP and the assumption ID. On the Windows development machine on 2 October 2026 the script finished with 5 PASS and 0 FAIL; the Linux-only checks were skipped there.

## 4. Requirements

### 4.1 Environment

- Target machine: Huawei MateBook, Linux Mint XFCE, 8 GB RAM. The solution must be light.
- Python 3.10 or later. Mint 21 ships Python 3.10, Mint 22 ships Python 3.12.
- Development happens on a Windows 11 machine with Python 3.14. The code must run on both. Linux-only tools (`notify-send`, `paplay`, `systemd-inhibit`) are skipped when they are missing.
- Standard library only is preferred (`urllib.request`, `ssl`, `json`, `logging`, `argparse`), so no venv or pip is needed. If a third-party package becomes necessary, the system pip on Mint 22 does not install packages because of PEP 668, and the README must describe a `python3 -m venv .venv` setup.

### 4.2 Behaviour

- In every cycle, the dates endpoint is queried for each office in the settings.
- A day is a candidate if `today + MIN_DAYS_AHEAD <= day < CURRENT_APPOINTMENT`. Defaults: `CURRENT_APPOINTMENT = "2026-10-27"` and `MIN_DAYS_AHEAD = 1`. Today is the local date of the machine (Europe/Tallinn on the MateBook).
- School rule. The school sends its documents to the office only after the user emails it the new appointment date (U4 in 7.2). It sends them the same day if the email arrives on a working day (Monday to Friday) before `SCHOOL_EMAIL_DEADLINE`, default `"12:00"`. The bot therefore computes, at the time of each check:
  - the email day: today, if today is a working day and `now + BOOKING_MINUTES` (default 30, the time to book and write the email) is not later than the deadline; otherwise the next working day;
  - the sending day: the email day plus `SCHOOL_WORKDAYS` working days (default 0, the same day);
  - the first reported day: the day after the sending day, and not earlier than `today + MIN_DAYS_AHEAD`.
  Examples with the defaults: found on Saturday, reported from Tuesday on; found on Friday at 11:00, from Monday on; found on Friday at 11:45, from Tuesday on; found on Monday at 09:00, from Tuesday on. `SCHOOL_EMAIL_DEADLINE = None` turns the rule off. The startup message and `--check-once` print the range of reported days and name free days before the current appointment that are too close.
- Limits of the school rule:
  - The rule assumes the email reaches the school by the deadline of the email day. Every new-slot message ends with that moment, for example "Book and email the school the new date before 12:00 today" or "... before 12:00 on Mon 05.10.2026". Missing it makes the reported slot too close.
  - A slot on the sending day itself is never reported, because "usually the same day" does not guarantee that the documents arrive before the appointment. This may hide a slot the school could still make, but never reports one it cannot.
  - When the deadline passes, slots of the next day stop being candidates without a message.
  - Public holidays and closing days of the school are not known to the bot. Before 27.10.2026 there are none; for a later `CURRENT_APPOINTMENT`, raise `SCHOOL_WORKDAYS` around holidays such as 24 to 26 December.
- With `MIN_DAYS_AHEAD = 0`, today's times are also considered, but only those at least 60 minutes from now.
- Optional filters: `TIME_WINDOW` (for example `("09:00", "15:00")`, both ends included) and `WEEKDAYS` (0 is Monday, 4 is Friday). Both are off by default.
- For candidate days, the times endpoint is called for the earliest 3 days per office in each cycle.
- State: for each office the bot keeps the result of its last successful check, a map from candidate date to its set of times, or "unknown" when no times were fetched. A check is successful when the dates request succeeds. A failed check leaves the state unchanged, so recovering from errors does not repeat notifications.
- If a times request fails, or a date is not among the earliest 3, the date keeps the times from the last successful check, or stays "unknown".
- Notifications are sent for:
  - a candidate date that was not a candidate in the last successful check. A date that disappears and comes back is notified again.
  - a time on a date whose times are known in both the previous and the current check, if the time was not in the previous set.
- New dates and times found in the same cycle go into one message. A date with unknown times is reported without times. If a time filter is set but the times are unknown, the date is still reported.
- Slots that other people are booking can disappear for up to 10 minutes and come back if the booking is not finished (B2 in 7.2). Reporting them again is intended.
- Reason for this design: with `(office, date, time)` as the slot key, a date whose times are fetched in one cycle but not in the next (a failed times request, or the date dropping out of the earliest 3) would be reported as new twice.
- At startup, one message is sent with the earliest date of each office and the current candidates, if any. This first check becomes the initial state.
- Every day at `DAILY_REPORT_HOUR`, a low-priority status message is sent. It contains the number of checks and errors in the last 24 hours and the earliest date of each office.
- State is not written to disk. After a restart, the startup message reports the current candidates anyway.

### 4.3 Polling rate and politeness

- Default interval 120 seconds, with a random deviation of ±15% each time. Values below 60 seconds are raised to 60.
- Requests are sent one after another, with a random pause of 2 to 5 seconds between them, for dates and times requests alike. No parallel requests.
- On 429, 5xx and network errors, the wait doubles with each consecutive failed cycle, up to 15 minutes. A `Retry-After` header is honoured.
- On 403 the bot does not retry quickly. It sends one error notification, not repeated while the 403 lasts, and waits 15 minutes.
- During development no looping requests are sent to the live site. Tests use a fake server. The live check is done only with `--check-once`, by hand.

### 4.4 Notifications (ntfy)

- Publishing uses a JSON body: `POST https://ntfy.sh/`, `Content-Type: application/json`, body fields `topic`, `title`, `message`, `priority` and `click`.
- Publishing with headers is not used. `http.client` encodes header values as latin-1, which fails on characters outside it, for example š and ž in Estonian names or emoji. JSON bodies do not have this problem.
- Priorities: 5 for a new slot and for a startup message that lists earlier slots, 4 for errors, 3 for startup and recovery, 2 for the daily status.
- Tapping a new-slot notification, or a startup message that lists slots, opens the booking page of the office with the earliest slot, at the calendar, with the office and the service selected (2.2). Other messages open `https://broneering.politsei.ee/`.
- New-slot messages carry two buttons (ntfy view actions; the ntfy documentation lists them as supported on Android, iOS and the web; on iOS they show when the notification is pressed and held): "Open calendar", the same address, and "Email school", a `mailto:` link to `SCHOOL_EMAIL` with the subject and text of `SCHOOL_EMAIL_SUBJECT` and `SCHOOL_EMAIL_BODY`, filled in with the date and the earliest time of the slot, the office and the current appointment. Without `SCHOOL_EMAIL` only the first button is sent.
- Anyone who knows the topic name can read the messages. They carry no personal data: office, date and time, and the school's address and e-mail text, which must not contain the user's name or student number. The link of the user's own appointment page is never sent, because it allows cancelling the appointment.
- The topic is a random, hard-to-guess name. The real topic lives only in `settings.py`, which is in `.gitignore`. `settings.example.py` holds a placeholder, and the bot refuses to start while the placeholder is set. No committed file contains the real topic.
- The ntfy app is installed on the phone and subscribed to the topic.
- As an extra alert on the desktop, `notify-send` and `paplay` are used when present, otherwise they are skipped silently.

Example message

```
Title    Earlier slot, Tallinn Tammsaare, 14.10
Body     Tallinn Tammsaare
         Wed 14.10.2026  09:15, 10:15
         Thu 15.10.2026  13:15
         Current appointment 27.10.2026. Tap to book.
         Book and email the school the new date before 12:00 today.
Buttons  Open calendar, Email school
```

The reminder line appears when the school rule is on (4.2), the "Email school" button when `SCHOOL_EMAIL` is set.

### 4.5 Settings

The only file the user edits is `settings.py`. A Python file was chosen because it allows comments and needs no extra parser. The repository holds `settings.example.py`; the real file is in `.gitignore`.

| Setting | Default | Description |
|---|---|---|
| `CURRENT_APPOINTMENT` | `"2026-10-27"` | Days before this date are searched |
| `MIN_DAYS_AHEAD` | `1` | Minimum number of days from today |
| `SCHOOL_EMAIL_DEADLINE` | `"12:00"` | The school must get the email with the new date before this time on a working day; `None` turns the school rule off (4.2) |
| `SCHOOL_WORKDAYS` | `0` | Working days the school needs after the email day; 0 means the same day |
| `BOOKING_MINUTES` | `30` | Minutes from a notification to the email to the school |
| `OFFICES` | Tammsaare entry | Each item is `{"name": ..., "url": ...}`, the url is the dates address |
| `CHECK_INTERVAL_SEC` | `120` | Lower limit 60 |
| `TIME_WINDOW` | `None` | Example `("09:00", "15:00")` |
| `WEEKDAYS` | `None` | Example `[0, 2, 4]` |
| `NTFY_SERVER` | `"https://ntfy.sh"` | |
| `NTFY_TOPIC` | placeholder | The real value only in `settings.py` |
| `DAILY_REPORT_HOUR` | `9` | `None` turns it off |
| `ERROR_ALERT_THRESHOLD` | `5` | Number of consecutive failed cycles |
| `DESKTOP_ALERTS` | `True` | notify-send and sound |
| `USER_AGENT` | value naming the bot | See 2.4 |
| `EXTRA_CA_FILE` | `"certs/gogetssl-rsa-dv-ca.pem"` | Intermediate missing from the server chain, see 2.5. `None` turns it off |
| `SCHOOL_EMAIL` | `"study@taltech.ee"` | Address of the "Email school" button; `None` removes it |
| `SCHOOL_EMAIL_SUBJECT` | `"Earlier PPA appointment: {date} {time}"` | Subject of that e-mail |
| `SCHOOL_EMAIL_BODY` | see `settings.example.py` | Text of that e-mail; placeholders `{date}`, `{time}`, `{office}`, `{current}` |

Offices are stored as URLs. The bot reads `branchPublicId`, `servicePublicId` and `customSlotLength` from the URL. The times address is built by replacing `/dates;` with `/dates/{YYYY-MM-DD}/times;`. The default entry:

```python
OFFICES = [
    {
        "name": "Tallinn Tammsaare",
        "url": "https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/"
               "89f89ac30f7f6329397e447102ce1ed13e5459eaa5a630c071d0577bdae6600a/dates;"
               "servicePublicId=b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40;"
               "customSlotLength=60",
    },
]
```

`settings.example.py` also lists Tartu, Pärnu, Jõhvi and Narva as commented-out entries. Relative paths in the settings (`EXTRA_CA_FILE`) are resolved against the project directory, not the working directory.

### 4.6 Command line

```
python3 slot_watch.py                      continuous watching
python3 slot_watch.py --check-once         one cycle, prints a summary per office, sends no notification
python3 slot_watch.py --test-notification  sends a test message to ntfy
python3 slot_watch.py --settings PATH      reads another settings file (with any of the above)
```

The earliest date printed by `--check-once` is compared with the calendar on the site to confirm the IDs.

### 4.7 Error handling and logging

- Consecutive errors are counted per office. When the threshold is crossed, one error notification is sent. When the office recovers, one recovery notification is sent.
- A failed times request is logged but does not count as a failed cycle. See 4.2 for how its times are handled.
- Unexpected exceptions inside a cycle are caught, logged with a traceback and counted as a failed cycle for that office. The bot keeps running, so a persistent bug produces one error notification instead of a crash loop.
- Only fatal errors outside the cycle end the process. The bot then sends a short ntfy message and exits with a non-zero code, and systemd restarts it within the limits in 4.8.
- On a TLS verification error, an explanatory message points to the options in 2.5: check `EXTRA_CA_FILE`, renew the intermediate.
- Settings errors are caught at startup with a clear message: wrong date format, empty URL, URL without `/dates;`, syntax error, placeholder topic, missing `EXTRA_CA_FILE`.
- Response parsing is lenient. Accepted: a list of objects (`date` and `time` keys), the `{"dates": [...]}`, `{"times": [...]}` and `{"value": [...]}` wrappers, and plain string lists. Dates are normalised with the pattern `\d{4}-\d{2}-\d{2}`, times with `\d{1,2}:\d{2}`. On an unexpected format, the first 300 characters of the raw response are logged.
- Logs go to the console and to a rotating file (`slot_watch.log`, 1 MB, 2 backups). Each cycle produces a one-line summary.

### 4.8 Running continuously

- In a terminal: `systemd-inhibit --what=sleep python3 slot_watch.py`. The system does not sleep while the bot runs.
- For permanent use, a systemd user service. Draft below.

```ini
[Unit]
Description=PPA appointment slot watcher
StartLimitIntervalSec=1h
StartLimitBurst=5

[Service]
WorkingDirectory=%h/ppa-slot-watch
ExecStart=/usr/bin/systemd-inhibit --what=sleep --who=ppa-slot-watch --why=watching-appointments /usr/bin/python3 %h/ppa-slot-watch/slot_watch.py
Restart=on-failure
RestartSec=60
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
```

- `StartLimitIntervalSec` and `StartLimitBurst` stop the restarts after 5 starts within an hour. Without them, the default limit (5 starts in 10 seconds) never triggers with `RestartSec=60`, and a persistent fatal error would send a notification every minute.
- The project is cloned to `~/ppa-slot-watch` on the MateBook. If the location differs, the paths in the unit change accordingly.
- The file is saved as `~/.config/systemd/user/ppa-slot-watch.service`, then `systemctl --user daemon-reload` and `systemctl --user enable --now ppa-slot-watch` are run. Logs: `journalctl --user -u ppa-slot-watch -f`. To keep it running without a login session: `loginctl enable-linger $USER`.
- `--what=sleep` does not block the lid-close action. For use with the lid closed, check the XFCE Power Manager and `HandleLidSwitch` in `/etc/systemd/logind.conf`.

### 4.9 Code and documentation style

- The code is simple and commented, so that someone new to Python can read it and change settings.
- Everything is in English: comments, user-facing messages, notifications, log lines, identifiers, settings, command line options, file names and documentation.
- File names are ASCII.
- README and docs are written in a technical reference tone. No bold, no promotional language, no em dashes. Documentation is not collected in one file, it is split as below. The files live at the repository root.

```
ppa-slot-watch/
  slot_watch.py
  settings.example.py
  tls_chain.py              only if AIA chasing is implemented
  certs/
    gogetssl-rsa-dv-ca.pem  intermediate missing from the server chain
  tools/
    check_host.py           checks the host assumptions (3.3)
  README.md                 short description and quick start
  docs/
    01-setup.md             Python, ntfy app, settings
    02-finding-ids.md       DevTools steps, confirming with --check-once
    03-running.md           terminal, systemd service, sleep
    04-troubleshooting.md   TLS, 403, 429, missing notifications
  systemd/
    ppa-slot-watch.service
  tests/
    fixtures/
    test_slot_watch.py
```

## 5. Test plan

- Unit tests use `unittest`, with no extra dependencies. Coverage:
  - URL parsing and building the times URL.
  - Response parsing, with the real samples in `tests/fixtures/` and the other formats in 4.7.
  - The candidate filter: boundary days, the today rule, day and time filters.
  - The notification diff: appearing, disappearing and reappearing dates and times. A failed times request, a date leaving the earliest 3 and a failed check followed by recovery must not cause a notification.
  - The SSL context: `EXTRA_CA_FILE` is loaded and `VERIFY_X509_PARTIAL_CHAIN` is cleared.
- No test depends on the real date. The current time is passed in from outside, for example as a `now` parameter or an injectable clock.
- The end-to-end test uses a fake Qmatic server and a fake ntfy server built with `http.server`. Scenario: the first cycle has no candidates. In the second cycle 14.10 is added, a notification is expected. In the third cycle it disappears. In the fourth it comes back, a new notification is expected. Then five cycles return 503, one error notification is expected. Then the server recovers with 14.10 still listed: one recovery notification is expected and no new slot notification. The interval lower limit and the pauses can be reduced from outside for the test.
- If AIA chasing is implemented, a TLS test is added. A test root, intermediate and leaf are generated with openssl. The leaf's `caIssuers` points to a local HTTP address, the server sends only the leaf, and the test root is trusted through the `SSL_CERT_FILE` environment variable. Expected result: the bot downloads the intermediate and connects. Negative test: when the AIA address returns a self-signed certificate, the connection is refused.
- Where the tests run: on the development machine with Python 3.14 during development, and once on the MateBook with its own Python (3.10 on Mint 21, 3.12 on Mint 22, see M1) before the bot goes live. The MateBook run is the one that counts: it has the target Python, and only there does the TLS setup behave as in production. The code avoids features newer than Python 3.10; the development machine checks this with `ast.parse(source, feature_version=(3, 10))`.
- Final step on the MateBook: one `--check-once`. The earliest date in its output must match the site. This also confirms the TLS setup on Linux.

## 6. When a notification arrives

1. Move the existing appointment instead of booking a second one. Open the appointment page (the "modify or cancel" link of the confirmation e-mail, kept as a home screen shortcut on the phone and never in the repository), choose "I want to reschedule my appointment", select the new date and time and confirm (B3 in 7.2). A second residence permit appointment would most likely be refused (B1). Selecting a time holds it for 10 minutes without extension (B2).
2. If moving is not offered, book through the notification ("Open calendar") and cancel the 27.10 appointment, so that the slot opens for someone else. If the site asks to cancel the old appointment first, the new time stays held for 10 minutes; if that time runs out, both may be lost.
3. Right after that, send the e-mail to the school with the "Email school" button, before the moment named in the last line of the notification. Check the time in the e-mail; it names the earliest time of the day. The school confirmed that such an e-mail is enough for it to send its invitation document to the office (U4).
4. Update `CURRENT_APPOINTMENT` with the new date and restart the bot, or stop it.
5. The documents for an earlier day should be ready in advance: passport, completed application form, family information form, proof of payment of the state fee and a 40x50 mm colour photo (TalTech's list), proof of income (bank statements; the migration advisor confirms whether a translation is needed) and the student status certificate issued by the study consultant.

## 7. Open questions and unverified assumptions

### 7.1 Questions about the booking site

Status on 2 October 2026. A checked box means the question was answered from the live site.

- [x] Is servicePublicId `3af778a3...` the residence permit service? No, it is "Applying for temporary protection (primary)". The residence permit service is `b2fed5a2...7b40` (2.3).
- [x] Which `customSlotLength` does the UI send for TRP? 60 (2.3).
- [x] Which office is the reference project's Tallinn ID, and what is the ID of the second Tallinn office? Tammsaare. No other Tallinn office offers the residence permit service (2.3).
- [x] What are the path and response format of the times endpoint? As inferred, a list of objects with `date` and `time` (2.2).
- [x] Which endpoints return the service and office lists? `serviceGroups` and `branches/available;servicePublicId=...` (2.2).
- [x] Is there a TLS chain error on the MateBook? Yes, verified on 3 October 2026: without the intermediate the handshake fails, with `certs/gogetssl-rsa-dv-ca.pem` it succeeds, and `--check-once` read the live site (M4 to M6 in 7.2).
- [x] Does the two-appointments-per-person rule apply in the new system? Most likely not for the same service: `serviceRestrictValue: 1` (2.6). Moving the appointment avoids the question (6).
- [ ] Does the server block by User-Agent or request rate? Single requests with the bot's User-Agent and no cookies were answered normally. Rate-based blocking is unknown (R1 in 7.2).

### 7.2 Unverified assumptions

Everything in this document that has not been checked yet, grouped by what is needed to check it. Each item gives the assumption, why it matters and how to check it. Status on 2 October 2026. Items checked or decided since then start with "Verified" or "Decided" and keep their ID.

Needs the MateBook (`tools/check_host.py`, see 3.3)

- M1. Verified on 3 October 2026: Linux Mint 22.3, Python 3.12.3 at `/usr/bin/python3`.
- M2. Verified on 3 October 2026: all needed standard library modules import.
- M3. Verified on 3 October 2026: OpenSSL 3.0.13; `create_default_context()` sets neither `VERIFY_X509_PARTIAL_CHAIN` nor `VERIFY_X509_STRICT`.
- M4. Verified on 3 October 2026: without the intermediate the handshake fails with `unable to get local issuer certificate` (code 20).
- M5. Verified on 3 October 2026: with `certs/gogetssl-rsa-dv-ca.pem` the handshake succeeds (TLS 1.3) and ends at a root of the system CA store.
- M6. Verified on 3 October 2026: status 200, 25 dates, earliest 19.11.2026, as on the site; `--check-once` printed the same.
- M7. Verified on 3 October 2026: Europe/Tallinn, synchronised by NTP, 1 second from the server's clock.
- M8. Verified on 3 October 2026: the user manager runs; `systemctl`, `systemd-inhibit`, `systemd-run` and `loginctl` exist; a sleep inhibitor can be taken without a password. The service was installed and sent its startup message.
- M9. Partly verified on 3 October 2026: XFCE Power Manager handles the lid itself (it holds the `handle-lid-switch` inhibitor; `logind-handle-lid-switch false`), and the lid action is "Switch off display" on battery and plugged in (`lid-action-on-ac 0`, `lid-action-on-battery 0`). No inactivity setting is stored, so the defaults apply. The long run (M13) still has to confirm it.
- M10. Verified on 3 October 2026: two desktop notifications and two sounds, from the terminal and from a user service.
- M11. Verified on 3 October 2026: `--test-notification` from the MateBook reached the phone, with "Jõhvi, Pärnu" shown correctly. A first try with the placeholder `<konu>` as topic got HTTP 400 from ntfy; the host check now rejects invalid topic names before sending.
- M12. Verified on 3 October 2026: linger is off, git is installed, 6.7 GiB of memory. Linger is not needed while the desktop session stays open.
- M13. Still open: the service runs since 3 October 2026. A test with the lid closed for about 10 minutes, then the daily status messages, show whether the machine stays awake and online.

Needs the user

- U1. Verified on 2 October 2026 from the booking confirmation: the current appointment is on 27.10.2026 at 15:15, at the Tammsaare office, for "Applying for or extending a residence permit".
- U2. Verified on 3 October 2026: the ntfy app is installed on the phone and subscribed to the topic, and the test message arrived. Not checked: whether priority 5 messages come through in Do Not Disturb mode.
- U3. Decided on 3 October 2026: the private GitHub repository; the MateBook clones it with `gh`.
- U4. Verified with the user on 3 October 2026: the school (study@taltech.ee) sends its invitation document to the office electronically before the appointment, and an e-mail from the user with the appointment date is sufficient confirmation; it cannot send it before the date is known. It usually sends it the same day if the e-mail arrives before noon on a working day; the exchange is by e-mail, so the reply is not immediate. Still open: "usually" is not a guarantee. If the school is late once, raise `SCHOOL_WORKDAYS` to 1, which hides the slots of the next working day.

Needs the development machine

- D1. Decided on 2 October 2026: Python 3.10 and 3.12 are not installed on the development machine. The tests run there with Python 3.14 during development and once on the MateBook with its own Python before the bot goes live (5). The bot runs only on the MateBook, so its Python version is the one that matters.
- D2. Verified on 3 October 2026: the tests of that day (61) passed on Windows with Python 3.14 and on the MateBook with Python 3.12.3.

Needs a few single requests or the booking UI (any machine, no booking)

- S1. Verified on 2 October 2026: the UI shows exactly the times the times endpoint returns. Checked on four dates, 19.11 (6 times), 27.11 (5), 30.11 (5) and 30.12 (7), each in one row and without paging. Earlier that day the API had returned 7 times for 19.11 while the page showed 5 a few minutes later; the likely cause is that the times changed in between, for example because other people were holding them (B2).
- S2. Verified on 2 October 2026: days missing from the dates list have no free times. 14.10.2026 (inside the watched period) and 02.12.2026 both returned `[]` with status 200. Fixture: `tests/fixtures/times_empty.json`.

Needs the running bot (seen over days)

- R1. The server tolerates one dates request about every 120 seconds, plus up to 3 times requests while candidates exist, for weeks. Cannot be tested in advance without load. The bot backs off on 429 and 403 and reports them (4.3).
- R2. A cancelled slot appears in the API within a minute or two. The bot depends on it. Evidence so far: responses carry `Cache-Control: no-store`, and the free times changed within minutes to hours (09:15 on 19.11 was taken, and the times of 19.11 differed between two reads a few minutes apart). Shown when the first slot is reported.
- R3. Error responses (403, 429, 5xx, maintenance pages) come in forms the parser and the error handling cope with. Unknown until seen; the bot logs the first 300 characters of unexpected responses (4.7).
- R4. The IDs and `customSlotLength` stay valid until 27.10. If they change, the API may answer with an error or with an empty list. The startup and daily messages show the earliest date, so an empty list stands out; compare it with the site now and then.
- R5. ntfy.sh accepts the bot's volume, a few messages a day, and delivers promptly. Check ntfy's documentation on limits; the daily status message shows that delivery keeps working.

Shown only when booking

- B1. Most likely only one active appointment per service (`serviceRestrictEnabled: true`, `serviceRestrictValue: 1`, see 2.6), so a second residence permit appointment would be refused while the current one exists; `maxTotal: 2` alone had suggested two. Which fields identify a person is unknown; identity checks are off. The confirmation e-mail says that the appointment can only be used by the person in whose name it was made. Moving the appointment (B3) avoids the question.
- B2. Selecting a time reserves it for 10 minutes without extension (`reservationExpiryTimeSeconds: "600"`, `allowReservationExtension: false`). The form has to be completed within that time.
- B3. The existing appointment can be moved to a new date and time. Strongly supported, not yet tried: the app has the route `#/{appointmentId}/reschedule` and the button "I want to reschedule my appointment"; `maxReschedules: -1`, `cancelTimeEnabled: false`, and the e-mail check of the reschedule page is off (`validateEmail: false`). The confirmation e-mail contains a personal link to the appointment page; anyone with it can cancel the appointment, so it must not be shared, committed or sent through ntfy. Can be checked before a slot appears: open the link, tap "I want to reschedule my appointment", look at the calendar and leave without selecting a time or pressing cancel.
- B4. Information from guides: unlimited cancellations, no cancellation e-mail, the document list, office hours, phone booking (2.6, 6). Needs the official PPA pages or a call to PPA.

Checked by the tests once the code exists (5)

- C1. The state and diff rules in 4.2, the parser in 4.7, backoff and 403 handling in 4.3, ntfy JSON publishing in 4.4 and the SSL context in 2.5.

## 8. Starting message for Claude Code

```
Read ppa-slot-watch-brief.md. Sections 3.1 and 3.2 are done; section 7.2 lists the
assumptions that are still unverified. Write the bot according to section 4, add the
tests from section 5 and run them. Do not send looping requests to the live site; I will
do the live check with --check-once. Keep the code simple and explain each step briefly.
```

## 9. Sources

- [PPA booking system](https://broneering.politsei.ee/)
- [Reference project, sagaryadavlost/politsei.ee__new_appointment_times_detector](https://github.com/sagaryadavlost/politsei.ee__new_appointment_times_detector) (`config.py`, `appointment_monitor/api_client.py`)
- [open-forms Qmatic client](https://github.com/open-formulieren/open-forms/blob/master/src/openforms/appointments/contrib/qmatic/client.py)
- [PPA, Applying for a residence permit](https://www.politsei.ee/en/instructions/applying-for-a-residence-permit/applying-for-a-residence-permit)
- [PPA, Tammsaare service office](https://www.politsei.ee/en/services/services/tallinn-tammsaare)
- [PPA, Student guide (PDF)](https://www.politsei.ee/files/2025-05/student-guide.pdf)
- [TalTech, Settling In](https://taltech.ee/en/practical)
- [Study in Estonia, Applying for a Temporary Residence Permit in Estonia](https://www.studyinestonia.ee/index.php/blog/applying-TRP-estonia)
- [MoveMyTalent, TRP appointment guide](https://movemytalent.com/wise-guide-appointment-process-for-temporary-residence-permit-trp-for-employment-process-at-the-police-and-border-guard/)
- [ntfy, Publishing](https://docs.ntfy.sh/publish/)
