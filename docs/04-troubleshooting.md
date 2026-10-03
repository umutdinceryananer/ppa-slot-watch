# Troubleshooting

## TLS: certificate verify failed

broneering.politsei.ee sends only its own certificate, not the intermediate certificate that links it to a trusted root. Browsers and Windows complete the chain themselves. Python and curl on Linux do not, and fail with `unable to get local issuer certificate` or `unable to verify the first certificate`.

The project ships the missing intermediate as `certs/gogetssl-rsa-dv-ca.pem`, and `EXTRA_CA_FILE` loads it. Check that:

1. `EXTRA_CA_FILE` in `settings.py` is `"certs/gogetssl-rsa-dv-ca.pem"`, not `None`.
2. `python3 tools/check_host.py` shows PASS for M5.

If both are right and the error stays, the site's certificate was probably renewed by another CA. The certificate in use on 2 October 2026 is valid until 01.02.2027. To get the new intermediate:

```bash
# 1. Address of the intermediate (the "CA Issuers" line)
openssl s_client -connect broneering.politsei.ee:443 -servername broneering.politsei.ee </dev/null 2>/dev/null \
  | openssl x509 -noout -ext authorityInfoAccess

# 2. Download it and convert it to PEM
curl -sS -o intermediate.crt '<CA Issuers address>'
openssl x509 -inform DER -in intermediate.crt -out intermediate.pem

# 3. It must chain to a root of the system store
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt intermediate.pem
```

If the last command prints `intermediate.pem: OK`, copy the file to `certs/` and point `EXTRA_CA_FILE` to it. Do not turn off certificate verification.

## HTTP 403

The site refused the requests. The bot sends one error notification and then waits 15 minutes between checks. The site may block the User-Agent or the request rate. Do not lower `CHECK_INTERVAL_SEC`. Check whether the booking page works in a browser on the same network; if it does and the 403 stays, raise `CHECK_INTERVAL_SEC`.

## HTTP 429, 5xx and network errors

The bot doubles the wait after each failed check, up to 15 minutes, and follows a `Retry-After` header up to one hour. After `ERROR_ALERT_THRESHOLD` failed checks in a row it sends one error notification, and one more when the checks work again. Nothing needs to be done unless the errors last for hours.

## "unexpected response"

The site answered with something the bot does not understand, for example a maintenance page. The log shows the first 300 characters of the answer. If it lasts, the API may have changed; compare with the requests the booking page sends ([02-finding-ids.md](02-finding-ids.md)).

## No notification on the phone

1. Run `python3 slot_watch.py --test-notification`. If it prints "not sent", the log line above says why.
2. If it prints "sent" but nothing arrives: compare the topic in the app and in `settings.py`, check the server (`https://ntfy.sh`), and check the notification permission and battery optimisation of the ntfy app.
3. The bot reports only days before `CURRENT_APPOINTMENT`, from `MIN_DAYS_AHEAD` on, filtered by `TIME_WINDOW` and `WEEKDAYS`. `python3 slot_watch.py --check-once` shows what it sees now.
4. The daily status message at `DAILY_REPORT_HOUR` shows that the bot and the notifications work.

## No desktop notification or sound

`python3 tools/check_host.py --desktop-test` shows whether `notify-send` and `paplay` exist and work, from the terminal and from a user service (M10). `DESKTOP_ALERTS = True` must be set.

## The bot stopped

`systemctl --user status ppa-slot-watch` shows the state and the last log lines; `journalctl --user -u ppa-slot-watch` shows more. A settings error stops the bot with a message that names the setting. After 5 crashes within an hour systemd stops restarting it: fix the cause, then run `systemctl --user restart ppa-slot-watch`.
