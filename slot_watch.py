#!/usr/bin/env python3
"""ppa-slot-watch: report earlier appointment slots at PPA service offices.

The bot asks the booking system of the Estonian Police and Border Guard Board
(broneering.politsei.ee) for free dates and sends an ntfy notification to the
phone when a slot before the current appointment opens. Booking is done by
hand on the site.

    python3 slot_watch.py                      watch continuously
    python3 slot_watch.py --check-once         check once, print a summary, send nothing
    python3 slot_watch.py --test-notification  send a test message to ntfy

The settings are in settings.py; copy settings.example.py to start.
Standard library only, Python 3.10 or later. Section numbers in the comments
refer to ppa-slot-watch-brief.md.
"""

import argparse
import collections
import dataclasses
import datetime
import email.utils
import http.client
import json
import logging
import logging.handlers
import os
import random
import re
import runpy
import shutil
import signal
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

log = logging.getLogger("slot_watch")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(PROJECT_DIR, "settings.py")
LOG_FILE = os.path.join(PROJECT_DIR, "slot_watch.log")

BOOKING_PAGE = "https://broneering.politsei.ee/"
PLACEHOLDER_TOPIC = "change-me"

# Timing rules (4.3). Tests give the Watcher smaller values.
MIN_INTERVAL_SEC = 60            # checks never run more often than this
JITTER = 0.15                    # the interval varies randomly by +-15%
PAUSE_RANGE_SEC = (2.0, 5.0)     # random pause between two requests
BACKOFF_CAP_SEC = 15 * 60        # longest wait after repeated errors
FORBIDDEN_WAIT_SEC = 15 * 60     # wait after HTTP 403
RETRY_AFTER_CAP_SEC = 60 * 60    # longer Retry-After values are cut to this
REQUEST_TIMEOUT_SEC = 20

TIMES_DAYS_PER_CHECK = 3                       # times are read for the earliest 3 days
TODAY_MARGIN = datetime.timedelta(minutes=60)  # today's slots must be this far away

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Default value of every setting (4.5). settings.py overrides them.
DEFAULTS = {
    "CURRENT_APPOINTMENT": "2026-10-27",
    "MIN_DAYS_AHEAD": 1,
    "SCHOOL_EMAIL_DEADLINE": "12:00",
    "SCHOOL_WORKDAYS": 0,
    "BOOKING_MINUTES": 30,
    "OFFICES": [
        {
            "name": "Tallinn Tammsaare",
            "url": "https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/"
                   "89f89ac30f7f6329397e447102ce1ed13e5459eaa5a630c071d0577bdae6600a/dates;"
                   "servicePublicId=b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40;"
                   "customSlotLength=60",
        },
    ],
    "CHECK_INTERVAL_SEC": 120,
    "TIME_WINDOW": None,
    "WEEKDAYS": None,
    "NTFY_SERVER": "https://ntfy.sh",
    "NTFY_TOPIC": PLACEHOLDER_TOPIC,
    "DAILY_REPORT_HOUR": 9,
    "ERROR_ALERT_THRESHOLD": 5,
    "DESKTOP_ALERTS": True,
    "USER_AGENT": "Mozilla/5.0 (X11; Linux x86_64) ppa-slot-watch/1.0",
    "EXTRA_CA_FILE": "certs/gogetssl-rsa-dv-ca.pem",
    "BOOKING_LANGUAGE": "en_en",
    "APPOINTMENT_LINK": None,
    "SCHOOL_EMAIL": "study@taltech.ee",
    "SCHOOL_EMAIL_SUBJECT": "Earlier PPA appointment: {date} {time}",
    "SCHOOL_EMAIL_BODY": (
        "Hello,\n\n"
        "My residence permit appointment at the PPA {office} service office was on {current}. "
        "I have found an earlier appointment on {date} at {time}. "
        "Could you please send the documents to the office for the new date today?\n\n"
        "Thank you."
    ),
}

# Placeholders of SCHOOL_EMAIL_SUBJECT and SCHOOL_EMAIL_BODY
EMAIL_PLACEHOLDERS = ("date", "time", "office", "current")

TLS_HELP = (
    "TLS certificate verification failed. broneering.politsei.ee does not send its "
    "intermediate certificate, so the bot loads it from EXTRA_CA_FILE "
    "(certs/gogetssl-rsa-dv-ca.pem). Check that EXTRA_CA_FILE is set in settings.py. "
    "If the site's certificate was renewed by another CA, get the new intermediate "
    "as described in docs/04-troubleshooting.md."
)


# ---------------------------------------------------------------- settings

class SettingsError(Exception):
    """A problem in settings.py, explained in plain words."""


@dataclasses.dataclass
class Office:
    name: str
    url: str              # the dates address of the office
    branch_id: str
    service_id: str
    slot_length: str


@dataclasses.dataclass
class Settings:
    current_appointment: datetime.date
    min_days_ahead: int
    school_email_deadline: Optional[str]  # "12:00", or None when the school rule is off
    school_workdays: int               # working days the school needs after the email day
    booking_minutes: int               # minutes from a notification to the email to the school
    offices: list
    check_interval: float
    time_window: Optional[tuple]       # ("09:00", "15:00") or None
    weekdays: Optional[frozenset]      # {0, 2, 4} or None
    ntfy_server: str
    ntfy_topic: str
    daily_report_hour: Optional[int]
    error_alert_threshold: int
    desktop_alerts: bool
    user_agent: str
    extra_ca_file: Optional[str]       # absolute path or None
    school_email: Optional[str]        # address for the "Email school" button, or None
    school_email_subject: str
    school_email_body: str
    booking_language: Optional[str]   # "en_en", "et_ee", or None for the site's default
    appointment_link: Optional[str]   # ".../qmaticwebbooking/#/<id>" of the user's appointment, or None


def load_settings(path, require_topic=True):
    """Read settings.py, apply the defaults and check every value."""
    name = os.path.basename(path)
    if not os.path.exists(path):
        raise SettingsError(f"{path} not found. Copy settings.example.py to {name} and edit it.")
    try:
        values = runpy.run_path(path)
    except SyntaxError as exc:
        raise SettingsError(f"syntax error in {name}, line {exc.lineno}: {exc.msg}") from None
    except Exception as exc:
        raise SettingsError(f"{name} could not be read: {exc!r}") from None
    raw = dict(DEFAULTS)
    for key, value in values.items():
        if not key.isupper():
            continue
        if key in DEFAULTS:
            raw[key] = value
        else:
            log.warning("%s: unknown setting %s is ignored", name, key)
    return validate_settings(raw, require_topic=require_topic)


def validate_settings(raw, require_topic=True, base_dir=PROJECT_DIR):
    """Turn the raw setting values into a Settings object, or raise SettingsError."""

    def fail(key, problem):
        raise SettingsError(f"{key}: {problem}")

    value = raw["CURRENT_APPOINTMENT"]
    try:
        current = datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        fail("CURRENT_APPOINTMENT", f'expected a date like "2026-10-27", got {value!r}')

    min_days = raw["MIN_DAYS_AHEAD"]
    if not is_int(min_days) or min_days < 0:
        fail("MIN_DAYS_AHEAD", f"expected a whole number of days, 0 or more, got {min_days!r}")

    deadline = raw["SCHOOL_EMAIL_DEADLINE"]
    if deadline is not None:
        if normalize_time(deadline) is None:
            fail("SCHOOL_EMAIL_DEADLINE", f'expected None or a time like "12:00", got {deadline!r}')
        deadline = normalize_time(deadline)

    school_workdays = raw["SCHOOL_WORKDAYS"]
    if not is_int(school_workdays) or school_workdays < 0:
        fail("SCHOOL_WORKDAYS", f"expected a whole number of working days, 0 or more, got {school_workdays!r}")

    booking_minutes = raw["BOOKING_MINUTES"]
    if not is_int(booking_minutes) or booking_minutes < 0:
        fail("BOOKING_MINUTES", f"expected a whole number of minutes, 0 or more, got {booking_minutes!r}")

    offices = []
    if not isinstance(raw["OFFICES"], (list, tuple)) or not raw["OFFICES"]:
        fail("OFFICES", "expected a list with at least one office")
    for number, item in enumerate(raw["OFFICES"], start=1):
        if not isinstance(item, dict):
            fail("OFFICES", f'office {number} must look like {{"name": ..., "url": ...}}')
        name, url = item.get("name"), item.get("url")
        if not isinstance(name, str) or not name.strip():
            fail("OFFICES", f"office {number} has no name")
        if not isinstance(url, str) or not url.strip():
            fail("OFFICES", f"{name}: the url is empty")
        try:
            branch, service, length = parse_office_url(url)
        except ValueError as exc:
            fail("OFFICES", f"{name}: {exc}")
        offices.append(Office(name.strip(), url.strip(), branch, service, length))
    if len({office.name for office in offices}) != len(offices):
        fail("OFFICES", "every office needs a different name")

    interval = raw["CHECK_INTERVAL_SEC"]
    if not is_number(interval) or interval <= 0:
        fail("CHECK_INTERVAL_SEC", f"expected a number of seconds, got {interval!r}")

    window = raw["TIME_WINDOW"]
    if window is not None:
        if isinstance(window, (list, tuple)) and len(window) == 2:
            start, end = normalize_time(window[0]), normalize_time(window[1])
        else:
            start = end = None
        if start is None or end is None or start > end:
            fail("TIME_WINDOW", f'expected None or two times like ("09:00", "15:00"), got {window!r}')
        window = (start, end)

    weekdays = raw["WEEKDAYS"]
    if weekdays is not None:
        if (not isinstance(weekdays, (list, tuple, set, frozenset)) or not weekdays
                or not all(is_int(day) and 0 <= day <= 6 for day in weekdays)):
            fail("WEEKDAYS", f"expected None or numbers from 0 (Monday) to 6 (Sunday), got {weekdays!r}")
        weekdays = frozenset(weekdays)

    server = raw["NTFY_SERVER"]
    if not isinstance(server, str) or not re.match(r"https?://", server):
        fail("NTFY_SERVER", f"expected an address starting with https://, got {server!r}")
    topic = raw["NTFY_TOPIC"]
    if require_topic:
        if topic == PLACEHOLDER_TOPIC:
            fail("NTFY_TOPIC", "still the placeholder; set your own topic name in settings.py")
        if not isinstance(topic, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
            fail("NTFY_TOPIC", "use 1 to 64 letters, digits, - or _")

    hour = raw["DAILY_REPORT_HOUR"]
    if hour is not None and (not is_int(hour) or not 0 <= hour <= 23):
        fail("DAILY_REPORT_HOUR", f"expected None or an hour from 0 to 23, got {hour!r}")

    threshold = raw["ERROR_ALERT_THRESHOLD"]
    if not is_int(threshold) or threshold < 1:
        fail("ERROR_ALERT_THRESHOLD", f"expected a number of checks, 1 or more, got {threshold!r}")

    if not isinstance(raw["DESKTOP_ALERTS"], bool):
        fail("DESKTOP_ALERTS", f"expected True or False, got {raw['DESKTOP_ALERTS']!r}")

    agent = raw["USER_AGENT"]
    if not isinstance(agent, str) or not agent.strip():
        fail("USER_AGENT", "expected a non-empty text")

    appointment_link = raw["APPOINTMENT_LINK"]
    if appointment_link is not None:
        match = APPOINTMENT_LINK_RE.fullmatch(appointment_link.strip()) if isinstance(appointment_link, str) else None
        if not match:  # the value is not printed: it gives access to the appointment
            fail("APPOINTMENT_LINK", 'expected None or the "modify or cancel" link of the confirmation e-mail, '
                                     "like https://broneering.politsei.ee/qmaticwebbooking/#/<long id>")
        appointment_link = f"{match.group('base')}/#/{match.group('id')}"

    language = raw["BOOKING_LANGUAGE"]
    if language is not None and (not isinstance(language, str) or not re.fullmatch(r"[a-z]{2}_[a-z]{2}", language)):
        fail("BOOKING_LANGUAGE", f'expected None or a language code like "en_en" or "et_ee", got {language!r}')

    school_email = raw["SCHOOL_EMAIL"]
    if school_email is not None and (not isinstance(school_email, str)
                                     or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", school_email)):
        fail("SCHOOL_EMAIL", f"expected None or an e-mail address, got {school_email!r}")
    for key in ("SCHOOL_EMAIL_SUBJECT", "SCHOOL_EMAIL_BODY"):
        template = raw[key]
        if not isinstance(template, str) or not template.strip():
            fail(key, "expected a text")
        try:
            template.format(**{name: "" for name in EMAIL_PLACEHOLDERS})
        except (KeyError, IndexError, ValueError) as exc:
            fail(key, f"unknown placeholder or stray brace ({exc!r}); "
                      "the placeholders are {date}, {time}, {office} and {current}")

    ca_file = raw["EXTRA_CA_FILE"]
    if ca_file is not None:
        if not isinstance(ca_file, str) or not ca_file.strip():
            fail("EXTRA_CA_FILE", "expected None or a file path")
        if not os.path.isabs(ca_file):
            ca_file = os.path.join(base_dir, ca_file)
        if not os.path.isfile(ca_file):
            fail("EXTRA_CA_FILE", f"file not found: {ca_file}")

    return Settings(
        current_appointment=current, min_days_ahead=min_days, school_email_deadline=deadline,
        school_workdays=school_workdays, booking_minutes=booking_minutes, offices=offices, check_interval=interval, time_window=window, weekdays=weekdays,
        ntfy_server=server, ntfy_topic=topic, daily_report_hour=hour,
        error_alert_threshold=threshold, desktop_alerts=raw["DESKTOP_ALERTS"],
        user_agent=agent, extra_ca_file=ca_file, school_email=school_email,
        school_email_subject=raw["SCHOOL_EMAIL_SUBJECT"], school_email_body=raw["SCHOOL_EMAIL_BODY"],
        booking_language=language, appointment_link=appointment_link,
    )


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize_time(text):
    """ "9:15" -> "09:15"; None if the text is not a time of day."""
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", text) if isinstance(text, str) else None
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        return None
    return f"{int(match.group(1)):02d}:{match.group(2)}"


# ------------------------------------------------------------------- URLs

# The dates address: .../branches/{branchPublicId}/dates;servicePublicId=...;customSlotLength=...
OFFICE_URL_RE = re.compile(r"https?://[^/\s]+/\S*/branches/(?P<branch>[0-9A-Fa-f]+)/dates;(?P<params>[^/?#\s]+)")


def parse_office_url(url):
    """Return (branchPublicId, servicePublicId, customSlotLength) from a dates address."""
    match = OFFICE_URL_RE.fullmatch(url.strip())
    if not match:
        raise ValueError("the url must be the dates address of the booking page, "
                         ".../branches/<id>/dates;servicePublicId=<id>;customSlotLength=<minutes>")
    params = dict(part.split("=", 1) for part in match.group("params").split(";") if "=" in part)
    for name in ("servicePublicId", "customSlotLength"):
        if not params.get(name):
            raise ValueError(f"the url has no {name}")
    return match.group("branch"), params["servicePublicId"], params["customSlotLength"]


def times_url(dates_url, day):
    """The address of the free times of one day: /dates; becomes /dates/{day}/times;"""
    return dates_url.replace("/dates;", f"/dates/{day}/times;", 1)


# The "modify or cancel" link of the confirmation e-mail: .../qmaticwebbooking/#/<appointment id>
APPOINTMENT_LINK_RE = re.compile(
    r"(?P<base>https?://[^\s#]+?)/?#/(?P<id>[0-9A-Fa-f]{16,})(?:/reschedule)?/?(?:\?[^\s#]*)?"
)


def reschedule_url(settings):
    """The page that moves the user's appointment to a new date and time, in BOOKING_LANGUAGE."""
    language = settings.booking_language
    return f"{settings.appointment_link}/reschedule" + (f"?lang={language}" if language else "")


def booking_url(office, route, language=None):
    """An address of the booking page, in the given language ("en_en", "et_ee") or the site's default."""
    base = office.url.split("/rest/schedule/")[0]  # https://broneering.politsei.ee/qmaticwebbooking
    return f"{base}/#/{route}" + (f"?lang={language}" if language else "")


def calendar_url(office, language=None):
    """The booking page with the office and the service already selected (2.2).

    It opens directly at the calendar, which saves two steps when booking.
    """
    return booking_url(office, f"preselect/branch/{office.branch_id}/services/{office.service_id}", language)


def school_mailto(settings, office_name, day, times, subject_prefix=""):
    """A mailto: link with the e-mail to the school, filled in with the found slot.

    The earliest time of the day is used; the user corrects it when booking
    another one. None when SCHOOL_EMAIL is not set.
    """
    if not settings.school_email:
        return None
    values = {
        "date": format_day(day),
        "time": min(times) if times else "__:__",
        "office": office_name,
        "current": f"{settings.current_appointment:%d.%m.%Y}",
    }
    subject = subject_prefix + settings.school_email_subject.format(**values)
    body = settings.school_email_body.format(**values).replace("\n", "\r\n")
    return (f"mailto:{settings.school_email}?subject={urllib.parse.quote(subject, safe='')}"
            f"&body={urllib.parse.quote(body, safe='')}")


def slot_actions(settings, office, day, times, subject_prefix=""):
    """Tap target and buttons of a slot notification (4.4).

    With APPOINTMENT_LINK, tapping opens the page that moves the user's
    appointment; without it, the booking calendar of the office. "Email school"
    opens the e-mail to the school about the slot.
    """
    if settings.appointment_link:
        click, label = reschedule_url(settings), "Reschedule"
    else:
        click, label = calendar_url(office, settings.booking_language), "Open calendar"
    actions = [{"action": "view", "label": label, "url": click}]
    mailto = school_mailto(settings, office.name, day, times, subject_prefix)
    if mailto:
        actions.append({"action": "view", "label": "Email school", "url": mailto})
    return click, actions


# --------------------------------------------------------------- responses

class ParseError(Exception):
    """The response did not have a form the bot understands."""


DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)")


def response_items(text, wrappers):
    """The list in a response: a plain list, or the list inside a wrapper object (4.7)."""
    try:
        data = json.loads(text)
    except ValueError:
        raise ParseError(f"not JSON: {text[:300]!r}") from None
    if isinstance(data, dict):
        for key in wrappers:
            if isinstance(data.get(key), list):
                return data[key]
    if isinstance(data, list):
        return data
    raise ParseError(f"unexpected response: {text[:300]!r}")


def parse_dates(text):
    """Free dates as sorted "YYYY-MM-DD" texts."""
    dates = set()
    for item in response_items(text, ("dates", "value")):
        value = item.get("date") if isinstance(item, dict) else item
        match = DATE_RE.search(value) if isinstance(value, str) else None
        if not match:
            raise ParseError(f"unexpected date item {str(item)[:100]!r} in: {text[:300]!r}")
        dates.add(match.group(0))
    return sorted(dates)


def parse_times(text):
    """Free times as sorted "HH:MM" texts."""
    times = set()
    for item in response_items(text, ("times", "value")):
        value = item.get("time") if isinstance(item, dict) else item
        match = TIME_RE.search(value) if isinstance(value, str) else None
        if not match:
            raise ParseError(f"unexpected time item {str(item)[:100]!r} in: {text[:300]!r}")
        times.add(f"{int(match.group(1)):02d}:{match.group(2)}")
    return sorted(times)


# ----------------------------------------------------------------- filters

def next_workday(day):
    """The next Monday-to-Friday day after `day`."""
    day += datetime.timedelta(days=1)
    while day.weekday() >= 5:
        day += datetime.timedelta(days=1)
    return day


def school_email_day(now, settings):
    """The working day on which the school receives the email with the new date.

    That is today, when today is a working day and the email can still be sent
    before SCHOOL_EMAIL_DEADLINE after BOOKING_MINUTES; otherwise the next working day.
    """
    today = now.date()
    deadline = datetime.datetime.combine(today, datetime.time.fromisoformat(settings.school_email_deadline))
    if today.weekday() < 5 and now + datetime.timedelta(minutes=settings.booking_minutes) <= deadline:
        return today
    return next_workday(today)


def first_report_day(now, settings):
    """The earliest day that may be reported (4.2).

    MIN_DAYS_AHEAD days from today, and with the school rule on, the day after the
    school sends its documents: SCHOOL_WORKDAYS working days after the email day.
    """
    first = now.date() + datetime.timedelta(days=settings.min_days_ahead)
    if settings.school_email_deadline is not None:
        sending_day = school_email_day(now, settings)
        for _ in range(settings.school_workdays):
            sending_day = next_workday(sending_day)
        first = max(first, sending_day + datetime.timedelta(days=1))
    return first


def report_window_text(now, settings):
    """ "Reported days: Tue 06.10.2026 to Mon 26.10.2026." for messages and --check-once."""
    first = first_report_day(now, settings)
    last = settings.current_appointment - datetime.timedelta(days=1)
    if first > last:
        return (f"No day before {settings.current_appointment:%d.%m.%Y} leaves the school "
                f"time to send its documents; nothing can be reported.")
    return f"Reported days: {format_day(first.isoformat())} to {format_day(last.isoformat())}."


def candidate_dates(dates, now, settings):
    """Dates from the first report day up to the day before the current appointment (4.2)."""
    first = first_report_day(now, settings)
    result = []
    for text in dates:
        day = datetime.date.fromisoformat(text)
        if not first <= day < settings.current_appointment:
            continue
        if settings.weekdays is not None and day.weekday() not in settings.weekdays:
            continue
        result.append(text)
    return result


def usable_times(day, times, now, settings):
    """Times inside TIME_WINDOW; for today only those at least 60 minutes from now."""
    result = []
    for text in times:
        if settings.time_window and not settings.time_window[0] <= text <= settings.time_window[1]:
            continue
        if day == now.date().isoformat():
            start = datetime.datetime.combine(now.date(), datetime.time.fromisoformat(text))
            if start < now + TODAY_MARGIN:
                continue
        result.append(text)
    return result


def find_new(previous, current):
    """What is new in `current` compared with `previous` (both: date -> times or None).

    A date is new when it was not a candidate before. A time is new when the
    date's times were known before and now, and the time was not there before.
    Times that were unknown (None) never count as new times (4.2).
    """
    new = {}
    for day, times in current.items():
        if day not in previous:
            new[day] = times
        elif times is not None and previous[day] is not None and times - previous[day]:
            new[day] = times
    return new


# ---------------------------------------------------------------- messages

def format_day(text):
    """ "2026-10-14" -> "Wed 14.10.2026" """
    day = datetime.date.fromisoformat(text)
    return f"{WEEKDAY_NAMES[day.weekday()]} {day:%d.%m.%Y}"


def describe_earliest(dates):
    return format_day(dates[0]) if dates else "none"


def format_slots(slots):
    """Lines like "Wed 14.10.2026  09:15, 10:15" for a map date -> times or None."""
    lines = []
    for day in sorted(slots):
        times = slots[day]
        lines.append(f"{format_day(day)}  " + (", ".join(sorted(times)) if times else "times not checked"))
    return lines


def school_reminder(now, settings):
    """The last moment to email the school, or None when the school rule is off.

    The reported days count on the email reaching the school by then, so the
    notification says it.
    """
    if settings.school_email_deadline is None:
        return None
    day = school_email_day(now, settings)
    when = "today" if day == now.date() else f"on {format_day(day.isoformat())}"
    return f"Book and email the school the new date before {settings.school_email_deadline} {when}."


def too_close_dates(dates, now, settings):
    """Free dates before the current appointment that leave the school too little time."""
    first = first_report_day(now, settings).isoformat()
    last = settings.current_appointment.isoformat()
    return [day for day in dates if now.date().isoformat() <= day < first and day < last]


def new_slots_message(new_by_office, current_appointment, reminder=None, move=False):
    """Title and body of the notification about new earlier slots (4.4)."""
    earliest = min(day for slots in new_by_office.values() for day in slots)
    short = datetime.date.fromisoformat(earliest).strftime("%d.%m")
    names = list(new_by_office)
    if len(names) == 1:
        title = f"Earlier slot, {names[0]}, {short}"
    else:
        title = f"Earlier slots at {len(names)} offices, {short}"
    blocks = ["\n".join([name] + format_slots(slots)) for name, slots in new_by_office.items()]
    tap = "Tap to move it to the new time." if move else "Tap to book."
    body = "\n\n".join(blocks) + f"\nCurrent appointment {current_appointment:%d.%m.%Y}. {tap}"
    if reminder:
        body += "\n" + reminder
    return title, body


# -------------------------------------------------------------------- HTTP

class HttpError(Exception):
    """The site answered with an HTTP error status."""

    def __init__(self, status, retry_after=None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.retry_after = retry_after    # seconds from a Retry-After header, or None


class NetworkError(Exception):
    """No usable answer: no connection, timeout, connection reset."""


class TlsError(Exception):
    """The site's certificate could not be verified."""


def describe_error(exc):
    """A short text for logs and notifications."""
    if isinstance(exc, HttpError):
        return f"HTTP {exc.status}"
    if isinstance(exc, TlsError):
        return f"TLS verification failed ({exc})"
    if isinstance(exc, NetworkError):
        return f"network error ({exc})"
    if isinstance(exc, ParseError):
        return "unexpected response"
    return f"unexpected error ({exc!r})"


def retry_after_seconds(value, now=None):
    """Seconds from a Retry-After header (seconds or an HTTP date), or None."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return max(0, int((when - now).total_seconds()))


def make_ssl_context(extra_ca_file):
    """System CA store plus the intermediate the site does not send (2.5)."""
    ctx = ssl.create_default_context()
    # Python 3.13 and later turn PARTIAL_CHAIN on; clear it so that the chain
    # must always end at a root certificate from the system store.
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0x80000)
    if extra_ca_file:
        try:
            ctx.load_verify_locations(cafile=extra_ca_file)
        except (OSError, ssl.SSLError) as exc:
            raise SettingsError(f"EXTRA_CA_FILE: {extra_ca_file} could not be loaded ({exc})") from None
    return ctx


def http_get(url, ssl_context, user_agent, timeout=REQUEST_TIMEOUT_SEC):
    """GET one API address and return the text. Raises HttpError, NetworkError or TlsError."""
    request = urllib.request.Request(url, headers={
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Referer": "https://broneering.politsei.ee/qmaticwebbooking/",
        "User-Agent": user_agent,
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        retry_after = retry_after_seconds(exc.headers.get("Retry-After") if exc.headers else None)
        exc.close()  # the error holds the open response
        raise HttpError(exc.code, retry_after) from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise TlsError(exc.reason.verify_message) from None
        raise NetworkError(str(exc.reason)) from None
    except ssl.SSLCertVerificationError as exc:
        raise TlsError(exc.verify_message) from None
    except (OSError, http.client.HTTPException) as exc:
        raise NetworkError(str(exc) or type(exc).__name__) from None


# ----------------------------------------------------------- notifications

class Ntfy:
    """Publishes notifications to an ntfy topic with a JSON body (4.4)."""

    def __init__(self, server, topic, user_agent):
        self.url = server.rstrip("/") + "/"
        self.topic = topic
        self.user_agent = user_agent

    def send(self, title, message, priority, click=None, actions=None):
        """click: address opened by tapping the notification; actions: up to 3 buttons."""
        data = {
            "topic": self.topic,
            "title": title,
            "message": message,
            "priority": priority,
            "click": click or BOOKING_PAGE,
        }
        if actions:
            data["actions"] = actions
        body = json.dumps(data).encode("utf-8")
        request = urllib.request.Request(self.url, data=body, method="POST", headers={
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        })
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SEC) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            exc.close()
            log.error("notification not sent (%s): HTTP %s", title, exc.code)
            return False
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            log.error("notification not sent (%s): %s", title, exc)
            return False
        log.info("notification sent: %s", title)
        return True


SOUND_FILES = (
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
    "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga",
)


def desktop_alert(title, message):
    """Desktop notification and sound, when notify-send and paplay exist (Linux)."""
    notify = shutil.which("notify-send")
    if notify:
        try:
            subprocess.run([notify, "--urgency=critical", "--app-name=ppa-slot-watch", title, message],
                           timeout=10, capture_output=True)
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("notify-send failed: %s", exc)
    paplay = shutil.which("paplay")
    sound = next((path for path in SOUND_FILES if os.path.exists(path)), None)
    if paplay and sound:
        try:
            subprocess.Popen([paplay, sound], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            log.debug("paplay failed: %s", exc)


# ----------------------------------------------------------------- watcher

@dataclasses.dataclass
class OfficeState:
    known: Optional[dict] = None    # date -> times or None, from the last successful check
    dates: Optional[list] = None    # all free dates from the last successful check
    failures: int = 0               # failed checks in a row
    alerted: bool = False           # an error notification went out, no recovery yet
    last_error: str = ""


@dataclasses.dataclass
class CycleOutcome:
    failed: bool = False            # at least one office check failed
    forbidden: bool = False         # the site answered 403
    retry_after: Optional[int] = None
    summary: str = ""


class Watcher:
    """Checks the offices, compares with the last successful check and notifies."""

    def __init__(self, settings, fetch, notifier=None, desktop=None,
                 now=datetime.datetime.now, sleep=time.sleep,
                 min_interval=MIN_INTERVAL_SEC, pause_range=PAUSE_RANGE_SEC):
        self.settings = settings
        self.fetch = fetch                # function(url) -> response text
        self.notifier = notifier          # Ntfy, or None to send nothing
        self.desktop = desktop            # function(title, message), or None
        self.now = now
        self.sleep = sleep
        self.min_interval = min_interval
        self.pause_range = pause_range
        self.states = {office.name: OfficeState() for office in settings.offices}
        self.started = False              # the startup message went out
        self.failed_cycles = 0            # cycles in a row with a failed check
        self.cycles = 0
        self.history = collections.deque()  # (time, ok) of every office check
        self.last_report_day = None

    def pause(self):
        """Random pause between two requests (4.3)."""
        self.sleep(random.uniform(*self.pause_range))

    def notify(self, title, message, priority, desktop=False, click=None, actions=None):
        """Send a notification. Without click, tapping it opens the booking page in BOOKING_LANGUAGE."""
        if click is None:
            click = booking_url(self.settings.offices[0], "", self.settings.booking_language)
        if self.notifier is not None:
            self.notifier.send(title, message, priority, click=click, actions=actions)
        if desktop and self.desktop is not None:
            self.desktop(title, message)

    def base_interval(self):
        return max(self.settings.check_interval, self.min_interval)

    def check_office(self, office, now, previous):
        """One check of one office. Returns (all free dates, candidates).

        candidates maps every candidate date to its usable times, or to None
        when the times are unknown. Raises when the dates request fails.
        """
        dates = parse_dates(self.fetch(office.url))
        candidates = {}
        for index, day in enumerate(candidate_dates(dates, now, self.settings)):
            times = None
            if index < TIMES_DAYS_PER_CHECK:
                self.pause()
                try:
                    times = parse_times(self.fetch(times_url(office.url, day)))
                except Exception as exc:  # a failed times request is not a failed check (4.7)
                    log.warning("%s: times of %s not read: %s", office.name, day, describe_error(exc))
            if times is None:
                # Keep what the last successful check knew about this day
                candidates[day] = (previous or {}).get(day)
                continue
            usable = usable_times(day, times, now, self.settings)
            if usable:  # a day without usable times is not a candidate
                candidates[day] = frozenset(usable)
        return dates, candidates

    def run_cycle(self):
        """Check every office once, send the notifications and return a CycleOutcome."""
        now = self.now()
        self.cycles += 1
        outcome = CycleOutcome()
        new_by_office = {}
        parts = []
        for number, office in enumerate(self.settings.offices):
            if number:
                self.pause()
            state = self.states[office.name]
            try:
                dates, candidates = self.check_office(office, now, state.known)
            except Exception as exc:
                self.record_failure(office, state, exc, outcome, now)
                parts.append(f"{office.name}: {state.last_error}")
                continue
            self.history.append((now, True))
            if state.alerted:
                self.notify(f"Checks work again, {office.name}",
                            f"Earliest free date: {describe_earliest(dates)}.", 3)
                state.alerted = False
            state.failures = 0
            # The first check at startup is reported by the startup message
            if state.known is not None or self.started:
                new = find_new(state.known or {}, candidates)
                if new:
                    new_by_office[office.name] = new
            state.known, state.dates = candidates, dates
            parts.append(f"{office.name}: earliest {dates[0] if dates else 'none'}, "
                         f"{len(candidates)} earlier")

        if not self.started:
            self.send_startup_message(now)
        if new_by_office:
            title, body = new_slots_message(new_by_office, self.settings.current_appointment,
                                            school_reminder(now, self.settings),
                                            move=bool(self.settings.appointment_link))
            click, actions = self.slot_links(new_by_office)
            self.notify(title, body, 5, desktop=True, click=click, actions=actions)
        self.forget_old_history(now)
        self.maybe_send_daily_report(now)
        self.failed_cycles = self.failed_cycles + 1 if outcome.failed else 0
        outcome.summary = f"cycle {self.cycles}: " + "; ".join(parts)
        return outcome

    def record_failure(self, office, state, exc, outcome, now):
        """Count a failed check, log it and send the error notification when due (4.7)."""
        state.failures += 1
        state.last_error = describe_error(exc)
        self.history.append((now, False))
        outcome.failed = True
        forbidden = isinstance(exc, HttpError) and exc.status == 403
        if forbidden:
            outcome.forbidden = True
        if isinstance(exc, HttpError) and exc.retry_after is not None:
            outcome.retry_after = max(outcome.retry_after or 0, exc.retry_after)
        if isinstance(exc, (HttpError, NetworkError, TlsError, ParseError)):
            log.warning("%s: check failed: %s", office.name, state.last_error)
            if isinstance(exc, ParseError):
                log.warning("%s", exc)  # holds the first 300 characters of the response
            if isinstance(exc, TlsError):
                log.error(TLS_HELP)
        else:
            log.error("%s: unexpected error in the check", office.name, exc_info=exc)
        if state.alerted:
            return
        if forbidden:
            text = (f"The site answered HTTP 403 (forbidden). The bot now waits "
                    f"{FORBIDDEN_WAIT_SEC // 60} minutes between checks.")
        elif state.failures >= self.settings.error_alert_threshold:
            text = f"{state.failures} checks in a row failed. Last error: {state.last_error}. The bot keeps trying."
        else:
            return
        self.notify(f"Check failing, {office.name}", text, 4)
        state.alerted = True

    def slot_links(self, slots_by_office):
        """Tap target and buttons for the earliest slot of a notification (4.4)."""
        name, day = min(((name, day) for name, slots in slots_by_office.items() for day in slots),
                        key=lambda pair: pair[1])
        office = next(office for office in self.settings.offices if office.name == name)
        return slot_actions(self.settings, office, day, slots_by_office[name][day])

    def send_startup_message(self, now):
        """One message with the earliest date and the current candidates of each office (4.2)."""
        self.started = True
        lines, priority = [], 3
        current = f"{self.settings.current_appointment:%d.%m.%Y}"
        for office in self.settings.offices:
            state = self.states[office.name]
            if state.known is None:
                lines.append(f"{office.name}: check failed ({state.last_error})")
            elif state.known:
                lines.append(f"{office.name}: earlier than {current}:")
                lines.extend("  " + line for line in format_slots(state.known))
                priority = 5
            else:
                line = (f"{office.name}: earliest free date {describe_earliest(state.dates)}, "
                        f"no slot in the reported days")
                close = too_close_dates(state.dates, now, self.settings)
                if close:
                    line += "; too close for the school: " + ", ".join(format_day(day) for day in close)
                lines.append(line)
        if priority == 5 and school_reminder(now, self.settings):
            lines.append(school_reminder(now, self.settings))
        lines.append(report_window_text(now, self.settings))
        lines.append(f"Checking every {self.base_interval():.0f} seconds.")
        found = {name: state.known for name, state in self.states.items() if state.known}
        click, actions = self.slot_links(found) if found else (None, None)
        self.notify("ppa-slot-watch started", "\n".join(lines), priority, desktop=priority == 5,
                    click=click, actions=actions)
        hour = self.settings.daily_report_hour
        if hour is not None and now.hour >= hour:
            self.last_report_day = now.date()  # the startup message replaces today's report

    def forget_old_history(self, now):
        since = now - datetime.timedelta(hours=24)
        while self.history and self.history[0][0] < since:
            self.history.popleft()

    def maybe_send_daily_report(self, now):
        """A low-priority status message once a day at DAILY_REPORT_HOUR (4.2)."""
        hour = self.settings.daily_report_hour
        if hour is None or now.hour < hour or self.last_report_day == now.date():
            return
        self.last_report_day = now.date()
        failed = sum(1 for _, ok in self.history if not ok)
        lines = [f"Last 24 hours: {len(self.history)} checks, {failed} failed."]
        for office in self.settings.offices:
            state = self.states[office.name]
            lines.append(f"{office.name}: earliest free date {describe_earliest(state.dates or [])}")
        self.notify("ppa-slot-watch status", "\n".join(lines), 2)

    def next_delay(self, outcome):
        """Seconds until the next cycle (4.3)."""
        if outcome.forbidden:
            return FORBIDDEN_WAIT_SEC
        if self.failed_cycles:
            delay = min(self.base_interval() * 2 ** self.failed_cycles, BACKOFF_CAP_SEC)
            if outcome.retry_after:
                delay = max(delay, min(outcome.retry_after, RETRY_AFTER_CAP_SEC))
            return delay
        return self.base_interval() * random.uniform(1 - JITTER, 1 + JITTER)

    def run_forever(self):
        if self.settings.check_interval < self.min_interval:
            log.warning("CHECK_INTERVAL_SEC is below %d seconds and is raised to it", self.min_interval)
        while True:
            outcome = self.run_cycle()
            delay = self.next_delay(outcome)
            log.info("%s; next check in %.0f s", outcome.summary, delay)
            self.sleep(delay)


# -------------------------------------------------------------------- main

def check_once(watcher):
    """--check-once: one check of every office, printed; no notifications (4.6)."""
    settings = watcher.settings
    current = f"{settings.current_appointment:%d.%m.%Y}"
    now = watcher.now()
    print(report_window_text(now, settings))
    all_ok = True
    for number, office in enumerate(settings.offices):
        if number:
            watcher.pause()
        try:
            dates, candidates = watcher.check_office(office, now, None)
        except Exception as exc:
            all_ok = False
            print(f"{office.name}: check failed: {describe_error(exc)}")
            if isinstance(exc, (TlsError, ParseError)):
                print(TLS_HELP if isinstance(exc, TlsError) else exc)
            continue
        print(f"{office.name}: {len(dates)} free dates, earliest {describe_earliest(dates)}")
        if candidates:
            print(f"  earlier than {current}:")
            for line in format_slots(candidates):
                print("    " + line)
        else:
            print("  no slot in the reported days")
        close = too_close_dates(dates, now, settings)
        if close:
            print("  free, but too close for the school: " + ", ".join(format_day(day) for day in close))
    return 0 if all_ok else 1


def send_test_notification(settings, notifier, now):
    """--test-notification: a test message with the buttons of a slot message (4.6).

    The buttons use a sample slot on the first day that could be reported, at
    09:15, so that the links and the e-mail draft can be tried before a real
    slot appears. The subject of the draft starts with "[TEST]", and the
    message asks not to send it.
    """
    office = settings.offices[0]
    day = first_report_day(now, settings)
    while day.weekday() >= 5:  # offices are closed at weekends
        day += datetime.timedelta(days=1)
    sample = day.isoformat()
    click, actions = slot_actions(settings, office, sample, frozenset({"09:15"}), subject_prefix="[TEST] ")
    lines = ["Test message. If you read this, notifications work. Non-ASCII text: Jõhvi, Pärnu.",
             f"The buttons use a sample slot, {format_day(sample)} 09:15."]
    if settings.appointment_link:
        lines.append("Tapping this message or \"Reschedule\" opens your real appointment: "
                     "look at it, but do not select a time.")
    if settings.school_email:
        lines.append("\"Email school\" only opens a draft marked [TEST]: do not send it, delete the draft.")
    return notifier.send("ppa-slot-watch test", "\n".join(lines), 3, click=click, actions=actions)


def setup_logging(log_file):
    """Log to the console and, when log_file is set, to a rotating file (4.7)."""
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.handlers.RotatingFileHandler(
            log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S", handlers=handlers)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Report earlier PPA appointment slots via ntfy.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-once", action="store_true",
                      help="check every office once, print a summary, send nothing")
    mode.add_argument("--test-notification", action="store_true",
                      help="send a test message to the ntfy topic")
    parser.add_argument("--settings", default=SETTINGS_FILE,
                        help="settings file (default: settings.py next to this script)")
    args = parser.parse_args(argv)

    one_shot = args.check_once or args.test_notification
    setup_logging(None if one_shot else LOG_FILE)
    try:
        settings = load_settings(args.settings, require_topic=not args.check_once)
        ssl_context = make_ssl_context(settings.extra_ca_file)
    except SettingsError as exc:
        log.error("settings problem: %s", exc)
        return 2

    notifier = Ntfy(settings.ntfy_server, settings.ntfy_topic, settings.user_agent)
    if args.test_notification:
        sent = send_test_notification(settings, notifier, datetime.datetime.now())
        print("test message sent" if sent else "test message not sent, see the error above")
        return 0 if sent else 1

    def fetch(url):
        return http_get(url, ssl_context, settings.user_agent)

    if args.check_once:
        return check_once(Watcher(settings, fetch))

    watcher = Watcher(settings, fetch, notifier=notifier,
                      desktop=desktop_alert if settings.desktop_alerts else None)
    # systemd stops the service with SIGTERM; leave cleanly with exit code 0
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(0))
    log.info("ppa-slot-watch started: %d office(s), current appointment %s",
             len(settings.offices), settings.current_appointment)
    try:
        watcher.run_forever()
    except KeyboardInterrupt:
        log.info("stopped")
        return 0
    except Exception as exc:  # fatal: report it and exit non-zero, systemd restarts the bot (4.7)
        log.critical("fatal error", exc_info=exc)
        notifier.send("ppa-slot-watch stopped", f"Unexpected error: {exc!r}", 4)
        return 1


if __name__ == "__main__":
    sys.exit(main())
