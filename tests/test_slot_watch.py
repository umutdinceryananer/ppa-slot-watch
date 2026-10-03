"""Tests of slot_watch.py (section 5 of the brief). Standard library only.

Run them from the project directory:

    python3 -m unittest discover -s tests -v

No test sends requests to the live site or depends on the real date.
"""

import ast
import contextlib
import datetime
import io
import http.server
import json
import logging
import os
import ssl
import sys
import tempfile
import threading
import unittest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(PROJECT_DIR, "tests", "fixtures")
sys.path.insert(0, PROJECT_DIR)

import slot_watch as sw  # noqa: E402

# Keep the test output short; assertLogs still sees the messages it checks.
logging.getLogger("slot_watch").setLevel(logging.CRITICAL)

BRANCH = "89f89ac30f7f6329397e447102ce1ed13e5459eaa5a630c071d0577bdae6600a"
SERVICE = "b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40"
DATES_PATH = (f"/qmaticwebbooking/rest/schedule/branches/{BRANCH}/dates;"
              f"servicePublicId={SERVICE};customSlotLength=60")
DATES_URL = "https://broneering.politsei.ee" + DATES_PATH
NOW = datetime.datetime(2026, 10, 2, 12, 0)   # a Friday
CA_FILE = os.path.join(PROJECT_DIR, "certs", "gogetssl-rsa-dv-ca.pem")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def make_settings(**overrides):
    raw = dict(sw.DEFAULTS)
    raw.update(NTFY_TOPIC="test-topic", EXTRA_CA_FILE=None, DAILY_REPORT_HOUR=None, DESKTOP_ALERTS=False,
               SCHOOL_EMAIL_DEADLINE=None)  # TestSchoolRule covers the school rule
    raw.update(overrides)
    return sw.validate_settings(raw)


class FakeFetch:
    """Answers API requests from memory: a dates list and the times of each day."""

    def __init__(self):
        self.dates = []
        self.times = {}
        self.dates_error = None      # exception raised by the dates request
        self.times_errors = {}       # day -> exception raised by its times request
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if "/times;" in url:
            day = url.split("/dates/")[1].split("/")[0]
            if day in self.times_errors:
                raise self.times_errors[day]
            return json.dumps([{"date": day, "time": t} for t in self.times.get(day, [])])
        if self.dates_error is not None:
            raise self.dates_error
        return json.dumps([{"date": d} for d in self.dates])


class FakeNotifier:
    def __init__(self):
        self.sent = []               # (title, message, priority)
        self.links = []              # {"click": ..., "actions": ...} of each message

    def send(self, title, message, priority, click=None, actions=None):
        self.sent.append((title, message, priority))
        self.links.append({"click": click, "actions": actions})
        return True

    def titles(self, start):
        return [m for m in self.sent if m[0].startswith(start)]


def make_watcher(fetch, now=lambda: NOW, **overrides):
    notifier = FakeNotifier()
    watcher = sw.Watcher(make_settings(**overrides), fetch, notifier=notifier, now=now,
                         sleep=lambda seconds: None, min_interval=0, pause_range=(0, 0))
    return watcher, notifier


class TestUrls(unittest.TestCase):
    def test_parse_office_url(self):
        self.assertEqual(sw.parse_office_url(DATES_URL), (BRANCH, SERVICE, "60"))

    def test_times_url(self):
        self.assertEqual(
            sw.times_url(DATES_URL, "2026-10-14"),
            f"https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/{BRANCH}"
            f"/dates/2026-10-14/times;servicePublicId={SERVICE};customSlotLength=60")

    def test_rejected_urls(self):
        for url in (DATES_URL.replace("/dates;", "/times;"), DATES_URL.split(";")[0], "not a url",
                    DATES_URL.replace(";customSlotLength=60", "")):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    sw.parse_office_url(url)


class TestParsing(unittest.TestCase):
    def test_dates_fixture(self):
        dates = sw.parse_dates(fixture("dates.json"))
        self.assertEqual(len(dates), 25)
        self.assertEqual(dates[0], "2026-11-19")
        self.assertEqual(dates, sorted(dates))

    def test_times_fixtures(self):
        self.assertEqual(sw.parse_times(fixture("times.json")),
                         ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"])
        self.assertEqual(sw.parse_times(fixture("times_empty.json")), [])

    def test_other_accepted_formats(self):
        self.assertEqual(sw.parse_dates('{"dates": [{"date": "2026-10-14"}]}'), ["2026-10-14"])
        self.assertEqual(sw.parse_dates('{"value": ["2026-10-14T00:00:00"]}'), ["2026-10-14"])
        self.assertEqual(sw.parse_dates('["2026-10-15", "2026-10-14"]'), ["2026-10-14", "2026-10-15"])
        self.assertEqual(sw.parse_times('{"times": ["9:15", "10:15"]}'), ["09:15", "10:15"])
        self.assertEqual(sw.parse_times('[{"date": "2026-10-14", "time": "2026-10-14T13:15:00"}]'), ["13:15"])

    def test_unexpected_formats(self):
        for text in ('{"error": "x"}', "<html>maintenance</html>", '[{"day": "2026-10-14"}]', "[42]"):
            with self.subTest(text=text):
                with self.assertRaises(sw.ParseError):
                    sw.parse_dates(text)

    def test_error_shows_the_start_of_the_response(self):
        with self.assertRaises(sw.ParseError) as caught:
            sw.parse_dates("<html>" + "x" * 1000)
        self.assertIn("<html>", str(caught.exception))
        self.assertLess(len(str(caught.exception)), 400)


class TestCandidates(unittest.TestCase):
    def test_boundaries(self):
        dates = ["2026-10-02", "2026-10-03", "2026-10-26", "2026-10-27", "2026-11-19"]
        self.assertEqual(sw.candidate_dates(dates, NOW, make_settings()), ["2026-10-03", "2026-10-26"])

    def test_today_with_zero_days_ahead(self):
        self.assertEqual(sw.candidate_dates(["2026-10-02"], NOW, make_settings(MIN_DAYS_AHEAD=0)),
                         ["2026-10-02"])

    def test_weekdays(self):
        settings = make_settings(WEEKDAYS=[0])  # Mondays only
        self.assertEqual(sw.candidate_dates(["2026-10-05", "2026-10-06"], NOW, settings), ["2026-10-05"])

    def test_time_window_includes_both_ends(self):
        settings = make_settings(TIME_WINDOW=("10:15", "12:15"))
        times = ["09:15", "10:15", "11:15", "12:15", "13:15"]
        self.assertEqual(sw.usable_times("2026-10-14", times, NOW, settings), ["10:15", "11:15", "12:15"])

    def test_today_needs_60_minutes(self):
        settings = make_settings(MIN_DAYS_AHEAD=0)
        self.assertEqual(sw.usable_times("2026-10-02", ["12:15", "13:00", "13:15"], NOW, settings),
                         ["13:00", "13:15"])

    def test_unknown_times_are_reported_despite_a_time_filter(self):
        fetch = FakeFetch()
        fetch.dates = ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]
        fetch.times = {day: ["09:15"] for day in fetch.dates}
        watcher, notifier = make_watcher(fetch, TIME_WINDOW=("09:00", "15:00"))
        watcher.run_cycle()
        self.assertIn("Fri 16.10.2026  times not checked", notifier.sent[0][1])


class TestSchoolRule(unittest.TestCase):
    """The school sends its documents the day it gets the email before noon (4.2)."""

    WEEK = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
            "2026-10-12", "2026-10-13"]  # Monday 05.10 to Tuesday 13.10
    SATURDAY = datetime.datetime(2026, 10, 3, 10, 0)

    def first(self, now, **overrides):
        settings = make_settings(SCHOOL_EMAIL_DEADLINE="12:00", **overrides)
        return sw.candidate_dates(self.WEEK, now, settings)[0]

    def school_watcher(self, fetch, now):
        return make_watcher(fetch, now=lambda: now, SCHOOL_EMAIL_DEADLINE="12:00")

    def test_found_on_saturday(self):
        self.assertEqual(self.first(self.SATURDAY), "2026-10-06")                       # Tuesday

    def test_found_on_friday_morning(self):
        self.assertEqual(self.first(datetime.datetime(2026, 10, 2, 11, 0)), "2026-10-05")    # Monday

    def test_found_on_friday_too_late_for_noon(self):
        self.assertEqual(self.first(datetime.datetime(2026, 10, 2, 11, 45)), "2026-10-06")   # Tuesday

    def test_found_on_monday_morning(self):
        self.assertEqual(self.first(datetime.datetime(2026, 10, 5, 9, 0)), "2026-10-06")     # Tuesday

    def test_booking_minutes_count(self):
        monday = datetime.datetime(2026, 10, 5, 11, 30)
        self.assertEqual(self.first(monday), "2026-10-06")                        # 11:30 + 30 min = 12:00
        self.assertEqual(self.first(monday, BOOKING_MINUTES=31), "2026-10-07")    # email only on Tuesday

    def test_school_workdays(self):
        self.assertEqual(self.first(self.SATURDAY, SCHOOL_WORKDAYS=1), "2026-10-07")   # sent on Tuesday

    def test_rule_off(self):
        settings = make_settings(SCHOOL_EMAIL_DEADLINE=None)
        self.assertEqual(sw.candidate_dates(self.WEEK, self.SATURDAY, settings)[0], "2026-10-05")

    def test_monday_slot_found_on_saturday_is_not_reported(self):
        fetch = FakeFetch()
        fetch.dates = ["2026-11-19"]
        fetch.times = {"2026-10-05": ["09:15"], "2026-10-06": ["09:15"]}
        watcher, notifier = self.school_watcher(fetch, self.SATURDAY)
        watcher.run_cycle()
        fetch.dates = ["2026-10-05", "2026-11-19"]
        watcher.run_cycle()
        self.assertEqual(notifier.titles("Earlier slot"), [])
        fetch.dates = ["2026-10-05", "2026-10-06", "2026-11-19"]
        watcher.run_cycle()
        (message,) = notifier.titles("Earlier slot")
        self.assertIn("Tue 06.10.2026  09:15", message[1])
        self.assertNotIn("Mon 05.10.2026  09:15", message[1])  # 05.10 only appears in the reminder
        self.assertTrue(message[1].endswith(
            "\nBook and email the school the new date before 12:00 on Mon 05.10.2026."))

    def test_reminder_on_a_working_morning(self):
        fetch = FakeFetch()
        fetch.times = {"2026-10-06": ["09:15"]}
        watcher, notifier = self.school_watcher(fetch, datetime.datetime(2026, 10, 5, 9, 0))
        watcher.run_cycle()
        fetch.dates = ["2026-10-06"]
        watcher.run_cycle()
        (message,) = notifier.titles("Earlier slot")
        self.assertTrue(message[1].endswith("\nBook and email the school the new date before 12:00 today."))

    def test_slot_leaves_quietly_at_the_deadline(self):
        clock = [datetime.datetime(2026, 10, 5, 9, 0)]
        fetch = FakeFetch()
        fetch.dates = ["2026-10-06"]
        fetch.times = {"2026-10-06": ["09:15"]}
        watcher, notifier = make_watcher(fetch, now=lambda: clock[0], SCHOOL_EMAIL_DEADLINE="12:00")
        watcher.run_cycle()                                   # startup lists 06.10
        clock[0] = datetime.datetime(2026, 10, 5, 11, 45)
        watcher.run_cycle()                                   # 06.10 is now too close
        self.assertEqual(len(notifier.sent), 1)
        self.assertEqual(watcher.states["Tallinn Tammsaare"].known, {})

    def test_startup_names_free_days_that_are_too_close(self):
        fetch = FakeFetch()
        fetch.dates = ["2026-10-05", "2026-11-19"]
        watcher, notifier = self.school_watcher(fetch, self.SATURDAY)
        watcher.run_cycle()
        title, body, priority = notifier.sent[0]
        self.assertIn("earliest free date Mon 05.10.2026, no slot in the reported days; "
                      "too close for the school: Mon 05.10.2026", body)
        self.assertIn("Reported days: Tue 06.10.2026 to Mon 26.10.2026.", body)
        self.assertEqual(priority, 3)

    def test_check_once_output(self):
        fetch = FakeFetch()
        fetch.dates = ["2026-10-05", "2026-10-08", "2026-11-19"]
        fetch.times = {"2026-10-08": ["10:15"]}
        watcher, _ = self.school_watcher(fetch, self.SATURDAY)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(sw.check_once(watcher), 0)
        self.assertEqual(output.getvalue().splitlines(), [
            "Reported days: Tue 06.10.2026 to Mon 26.10.2026.",
            "Tallinn Tammsaare: 3 free dates, earliest Mon 05.10.2026",
            "  earlier than 27.10.2026:",
            "    Thu 08.10.2026  10:15",
            "  free, but too close for the school: Mon 05.10.2026",
        ])

    def test_window_closed(self):
        settings = make_settings(SCHOOL_EMAIL_DEADLINE="12:00")
        text = sw.report_window_text(datetime.datetime(2026, 10, 26, 10, 0), settings)
        self.assertIn("nothing can be reported", text)


class TestNotifications(unittest.TestCase):
    def setUp(self):
        self.fetch = FakeFetch()
        self.fetch.times = {"2026-10-13": ["12:15"], "2026-10-14": ["09:15"],
                            "2026-10-15": ["10:15"], "2026-10-16": ["11:15"]}
        self.watcher, self.notifier = make_watcher(self.fetch)

    def cycles(self, *date_lists):
        for dates in date_lists:
            self.fetch.dates = dates
            self.watcher.run_cycle()

    def slot_messages(self):
        return self.notifier.titles("Earlier slot")

    def test_startup_message_without_candidates(self):
        self.cycles(["2026-11-19"])
        title, body, priority = self.notifier.sent[0]
        self.assertEqual(title, "ppa-slot-watch started")
        self.assertIn("earliest free date Thu 19.11.2026, no slot in the reported days", body)
        self.assertNotIn("too close", body)
        self.assertNotIn("tell the school", body)
        self.assertEqual(priority, 3)

    def test_startup_message_lists_candidates(self):
        self.cycles(["2026-10-14", "2026-11-19"], ["2026-10-14", "2026-11-19"])
        self.assertEqual(len(self.notifier.sent), 1)
        title, body, priority = self.notifier.sent[0]
        self.assertIn("Wed 14.10.2026  09:15", body)
        self.assertEqual(priority, 5)

    def test_appearing_disappearing_and_returning_date(self):
        self.cycles([], ["2026-10-14"], [], ["2026-10-14"])
        messages = self.slot_messages()
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0][0], "Earlier slot, Tallinn Tammsaare, 14.10")
        self.assertEqual(messages[0][2], 5)

    def test_failed_times_request_does_not_notify_again(self):
        self.cycles(["2026-10-14"])
        self.fetch.times_errors = {"2026-10-14": sw.NetworkError("timeout")}
        self.cycles(["2026-10-14"])
        self.fetch.times_errors = {}
        self.cycles(["2026-10-14"])
        self.assertEqual(self.slot_messages(), [])

    def test_date_leaving_the_earliest_three_does_not_notify_again(self):
        self.cycles(["2026-10-14", "2026-10-15", "2026-10-16"],
                    ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"],
                    ["2026-10-14", "2026-10-15", "2026-10-16"])
        messages = self.slot_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("Tue 13.10.2026  12:15", messages[0][1])
        self.assertNotIn("16.10.2026", messages[0][1])

    def test_new_time_on_a_known_date(self):
        self.cycles(["2026-10-14"])
        self.fetch.times["2026-10-14"] = ["09:15", "13:15"]
        self.cycles(["2026-10-14"])
        messages = self.slot_messages()
        self.assertEqual(len(messages), 1)
        self.assertIn("Wed 14.10.2026  09:15, 13:15", messages[0][1])

    def test_unknown_times_becoming_known_are_not_new(self):
        self.cycles(["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"],
                    ["2026-10-14", "2026-10-15", "2026-10-16"])
        self.assertEqual(self.slot_messages(), [])

    def test_times_are_read_for_the_earliest_three_days_only(self):
        self.cycles(["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"])
        times_requests = [url for url in self.fetch.urls if "/times;" in url]
        self.assertEqual(len(times_requests), 3)
        self.assertNotIn("2026-10-16", " ".join(times_requests))

    def test_day_without_usable_times_is_not_a_candidate(self):
        self.fetch.times["2026-10-14"] = []
        self.cycles([], ["2026-10-14"])
        self.assertEqual(self.slot_messages(), [])


class TestErrors(unittest.TestCase):
    def test_threshold_and_recovery(self):
        fetch = FakeFetch()
        fetch.dates = ["2026-11-19"]
        watcher, notifier = make_watcher(fetch, ERROR_ALERT_THRESHOLD=3)
        watcher.run_cycle()
        fetch.dates_error = sw.HttpError(503)
        for _ in range(4):
            watcher.run_cycle()
        fetch.dates_error = None
        watcher.run_cycle()
        self.assertEqual([priority for _, _, priority in notifier.sent], [3, 4, 3])
        self.assertIn("3 checks in a row failed. Last error: HTTP 503", notifier.sent[1][1])
        self.assertEqual(notifier.sent[2][0], "Checks work again, Tallinn Tammsaare")

    def test_403_notifies_at_once_and_waits(self):
        fetch = FakeFetch()
        fetch.dates_error = sw.HttpError(403)
        watcher, notifier = make_watcher(fetch)
        outcome = watcher.run_cycle()
        self.assertEqual(watcher.next_delay(outcome), sw.FORBIDDEN_WAIT_SEC)
        watcher.run_cycle()
        self.assertEqual(len(notifier.titles("Check failing")), 1)
        self.assertIn("HTTP 403", notifier.titles("Check failing")[0][1])

    def test_unexpected_exception_is_a_failed_check(self):
        fetch = FakeFetch()
        fetch.dates_error = RuntimeError("bug")
        watcher, notifier = make_watcher(fetch, ERROR_ALERT_THRESHOLD=2)
        watcher.run_cycle()
        watcher.run_cycle()
        self.assertEqual(len(notifier.titles("Check failing")), 1)

    def test_backoff_doubles_up_to_15_minutes(self):
        fetch = FakeFetch()
        fetch.dates_error = sw.HttpError(503)
        watcher, _ = make_watcher(fetch)
        delays = [watcher.next_delay(watcher.run_cycle()) for _ in range(4)]
        self.assertEqual(delays, [240, 480, 900, 900])

    def test_retry_after_is_honoured_and_capped(self):
        fetch = FakeFetch()
        fetch.dates_error = sw.HttpError(429, retry_after=1200)
        watcher, _ = make_watcher(fetch)
        self.assertEqual(watcher.next_delay(watcher.run_cycle()), 1200)
        fetch.dates_error = sw.HttpError(429, retry_after=10 ** 6)
        self.assertEqual(watcher.next_delay(watcher.run_cycle()), sw.RETRY_AFTER_CAP_SEC)

    def test_normal_delay_has_jitter_and_a_minimum(self):
        fetch = FakeFetch()
        watcher, _ = make_watcher(fetch)
        outcome = watcher.run_cycle()
        for _ in range(50):
            self.assertTrue(102 <= watcher.next_delay(outcome) <= 138)
        watcher.settings.check_interval = 10
        watcher.min_interval = 60
        for _ in range(50):
            self.assertTrue(51 <= watcher.next_delay(outcome) <= 69)

    def test_retry_after_header(self):
        self.assertEqual(sw.retry_after_seconds("120"), 120)
        self.assertIsNone(sw.retry_after_seconds(None))
        self.assertIsNone(sw.retry_after_seconds("soon"))
        now = datetime.datetime(2026, 10, 2, 10, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(sw.retry_after_seconds("Fri, 02 Oct 2026 10:05:00 GMT", now), 300)


class TestDailyReport(unittest.TestCase):
    def test_once_a_day_at_the_hour(self):
        clock = [datetime.datetime(2026, 10, 2, 8, 0)]
        fetch = FakeFetch()
        fetch.dates = ["2026-11-19"]
        watcher, notifier = make_watcher(fetch, now=lambda: clock[0], DAILY_REPORT_HOUR=9)
        for moment in ((2026, 10, 2, 8, 0), (2026, 10, 2, 9, 1), (2026, 10, 2, 9, 3), (2026, 10, 3, 9, 0)):
            clock[0] = datetime.datetime(*moment)
            watcher.run_cycle()
        reports = [m for m in notifier.sent if m[2] == 2]
        self.assertEqual(len(reports), 2)
        self.assertIn("Last 24 hours: 2 checks, 0 failed.", reports[0][1])
        self.assertIn("earliest free date Thu 19.11.2026", reports[0][1])

    def test_no_report_on_the_day_of_a_late_start(self):
        clock = [datetime.datetime(2026, 10, 2, 14, 0)]
        fetch = FakeFetch()
        watcher, notifier = make_watcher(fetch, now=lambda: clock[0], DAILY_REPORT_HOUR=9)
        watcher.run_cycle()
        clock[0] = datetime.datetime(2026, 10, 2, 15, 0)
        watcher.run_cycle()
        self.assertEqual([m for m in notifier.sent if m[2] == 2], [])


class TestLinks(unittest.TestCase):
    """Tapping a slot notification and its buttons (4.4)."""

    def test_calendar_url(self):
        office = make_settings().offices[0]
        calendar = f"https://broneering.politsei.ee/qmaticwebbooking/#/preselect/branch/{BRANCH}/services/{SERVICE}"
        self.assertEqual(sw.calendar_url(office), calendar)
        self.assertEqual(sw.calendar_url(office, "en_en"), calendar + "?lang=en_en")

    def test_home_url(self):
        office = make_settings().offices[0]
        self.assertEqual(sw.booking_url(office, "", "en_en"),
                         "https://broneering.politsei.ee/qmaticwebbooking/#/?lang=en_en")

    def test_school_mailto(self):
        url = sw.school_mailto(make_settings(), "Tallinn Tammsaare", "2026-10-06", frozenset({"10:15", "09:15"}))
        address, query = url.split("?", 1)
        self.assertEqual(address, "mailto:study@taltech.ee")
        fields = dict(part.split("=", 1) for part in query.split("&"))
        self.assertEqual(sw.urllib.parse.unquote(fields["subject"]), "Earlier PPA appointment: Tue 06.10.2026 09:15")
        body = sw.urllib.parse.unquote(fields["body"])
        self.assertTrue(body.startswith("Hello,\r\n\r\nMy residence permit appointment at the PPA "
                                        "Tallinn Tammsaare service office was on 27.10.2026. "
                                        "I have found an earlier appointment on Tue 06.10.2026 at 09:15."))
        self.assertNotIn(" ", query)   # everything is percent-encoded

    def test_unknown_times_leave_a_blank_to_fill(self):
        url = sw.school_mailto(make_settings(), "Tallinn Tammsaare", "2026-10-06", None)
        self.assertIn("__%3A__", url)

    def test_no_school_email(self):
        self.assertIsNone(sw.school_mailto(make_settings(SCHOOL_EMAIL=None), "x", "2026-10-06", None))

    def test_slot_notification_links(self):
        fetch = FakeFetch()
        fetch.times = {"2026-10-14": ["09:15"]}
        watcher, notifier = make_watcher(fetch)
        watcher.run_cycle()
        fetch.dates = ["2026-10-14"]
        watcher.run_cycle()
        startup, slot = notifier.links
        # without slots, tapping opens the booking page in English
        self.assertEqual(startup["click"], "https://broneering.politsei.ee/qmaticwebbooking/#/?lang=en_en")
        self.assertEqual(slot["click"], sw.calendar_url(watcher.settings.offices[0], "en_en"))
        self.assertTrue(slot["click"].endswith("?lang=en_en"))
        self.assertEqual([a["label"] for a in slot["actions"]], ["Open calendar", "Email school"])
        self.assertIn("Wed%2014.10.2026%2009%3A15", slot["actions"][1]["url"])

    def test_test_notification_shows_the_buttons_with_a_marked_draft(self):
        notifier = FakeNotifier()
        friday_afternoon = datetime.datetime(2026, 10, 2, 14, 0)    # first reportable day: Tuesday 06.10
        sw.send_test_notification(make_settings(SCHOOL_EMAIL_DEADLINE="12:00"), notifier, friday_afternoon)
        (title, body, priority), links = notifier.sent[0], notifier.links[0]
        self.assertEqual((title, priority), ("ppa-slot-watch test", 3))
        self.assertIn("do not send it", body)
        self.assertIn("Tue 06.10.2026 09:15", body)
        self.assertEqual([a["label"] for a in links["actions"]], ["Open calendar", "Email school"])
        subject = sw.urllib.parse.unquote(links["actions"][1]["url"].split("subject=")[1].split("&")[0])
        self.assertEqual(subject, "[TEST] Earlier PPA appointment: Tue 06.10.2026 09:15")

    def test_test_notification_sample_day_skips_the_weekend(self):
        notifier = FakeNotifier()
        thursday_afternoon = datetime.datetime(2026, 10, 1, 14, 0)  # sending day Friday, next day Saturday
        sw.send_test_notification(make_settings(SCHOOL_EMAIL_DEADLINE="12:00"), notifier, thursday_afternoon)
        self.assertIn("Mon 05.10.2026 09:15", notifier.sent[0][1])

    def test_without_school_email_only_the_calendar_button(self):
        fetch = FakeFetch()
        fetch.dates = ["2026-10-14"]
        fetch.times = {"2026-10-14": ["09:15"]}
        watcher, notifier = make_watcher(fetch, SCHOOL_EMAIL=None)
        watcher.run_cycle()                          # startup message lists the slot
        self.assertEqual([a["label"] for a in notifier.links[0]["actions"]], ["Open calendar"])


class TestAppointmentLink(unittest.TestCase):
    """With APPOINTMENT_LINK, a slot notification opens the page that moves the appointment."""

    LINK = "https://broneering.politsei.ee/qmaticwebbooking/#/" + "0123456789abcdef" * 4   # not a real one

    def test_accepted_forms(self):
        for link in (self.LINK, self.LINK + "?lang=en_en", self.LINK + "/reschedule?lang=et_ee",
                     self.LINK.replace("/#/", "#/"), " " + self.LINK + " "):
            with self.subTest(link=link):
                self.assertEqual(make_settings(APPOINTMENT_LINK=link).appointment_link, self.LINK)

    def test_bad_link_is_not_printed(self):
        with self.assertRaises(sw.SettingsError) as caught:
            make_settings(APPOINTMENT_LINK="https://example.com/secret-value")
        self.assertIn("APPOINTMENT_LINK", str(caught.exception))
        self.assertNotIn("secret-value", str(caught.exception))

    def test_appointment_url(self):
        self.assertEqual(sw.appointment_url(make_settings(APPOINTMENT_LINK=self.LINK)), self.LINK + "?lang=en_en")
        self.assertEqual(sw.appointment_url(make_settings(APPOINTMENT_LINK=self.LINK + "/reschedule",
                                                          BOOKING_LANGUAGE=None)), self.LINK)

    def test_slot_notification_opens_the_reschedule_page(self):
        fetch = FakeFetch()
        fetch.times = {"2026-10-14": ["09:15"]}
        watcher, notifier = make_watcher(fetch, APPOINTMENT_LINK=self.LINK)
        watcher.run_cycle()
        fetch.dates = ["2026-10-14"]
        watcher.run_cycle()
        (title, body, _), links = notifier.sent[1], notifier.links[1]
        self.assertEqual(title, "Earlier slot, Tallinn Tammsaare, 14.10")
        self.assertEqual(links["click"], self.LINK + "?lang=en_en")
        self.assertEqual([a["label"] for a in links["actions"]], ["Reschedule", "Email school"])
        self.assertIn("Current appointment 27.10.2026. "
                      "Tap to open it, then \"I want to reschedule my appointment\".", body)

    def test_test_notification(self):
        notifier = FakeNotifier()
        sw.send_test_notification(make_settings(APPOINTMENT_LINK=self.LINK), notifier, NOW)
        self.assertEqual(notifier.links[0]["click"], self.LINK + "?lang=en_en")
        self.assertEqual([a["label"] for a in notifier.links[0]["actions"]], ["Reschedule", "Email school"])
        self.assertIn("do not select a time", notifier.sent[0][1])


class TestMessages(unittest.TestCase):
    def test_format_day(self):
        self.assertEqual(sw.format_day("2026-10-14"), "Wed 14.10.2026")
        self.assertEqual(sw.format_day("2026-10-27"), "Tue 27.10.2026")

    def test_new_slot_message_matches_the_brief(self):
        title, body = sw.new_slots_message(
            {"Tallinn Tammsaare": {"2026-10-14": frozenset({"09:15", "10:15"}),
                                   "2026-10-15": frozenset({"13:15"})}},
            datetime.date(2026, 10, 27))
        self.assertEqual(title, "Earlier slot, Tallinn Tammsaare, 14.10")
        self.assertEqual(body, "Tallinn Tammsaare\n"
                               "Wed 14.10.2026  09:15, 10:15\n"
                               "Thu 15.10.2026  13:15\n"
                               "Current appointment 27.10.2026. Tap to book.")

    def test_several_offices_and_unknown_times(self):
        title, body = sw.new_slots_message(
            {"Tallinn Tammsaare": {"2026-10-20": None}, "Tartu": {"2026-10-14": frozenset({"09:15"})}},
            datetime.date(2026, 10, 27))
        self.assertEqual(title, "Earlier slots at 2 offices, 14.10")
        self.assertIn("Tue 20.10.2026  times not checked", body)


class TestSettings(unittest.TestCase):
    EXAMPLE = os.path.join(PROJECT_DIR, "settings.example.py")

    def write(self, text):
        handle, path = tempfile.mkstemp(suffix=".py")
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_example_file(self):
        settings = sw.load_settings(self.EXAMPLE, require_topic=False)
        self.assertEqual(settings.current_appointment, datetime.date(2026, 10, 27))
        self.assertEqual(settings.booking_language, "en_en")
        self.assertEqual((settings.school_email_deadline, settings.school_workdays, settings.booking_minutes),
                         ("12:00", 0, 30))
        self.assertEqual(settings.offices[0].service_id, SERVICE)
        self.assertEqual(settings.offices[0].slot_length, "60")
        self.assertEqual(os.path.normcase(settings.extra_ca_file), os.path.normcase(CA_FILE))

    def test_placeholder_topic_is_refused(self):
        with self.assertRaisesRegex(sw.SettingsError, "NTFY_TOPIC"):
            sw.load_settings(self.EXAMPLE)

    def test_bad_values(self):
        cases = {
            "CURRENT_APPOINTMENT": "27.10.2026",
            "MIN_DAYS_AHEAD": -1,
            "SCHOOL_EMAIL_DEADLINE": "noon",
            "SCHOOL_WORKDAYS": -1,
            "BOOKING_MINUTES": "30",
            "OFFICES": [{"name": "Tallinn", "url": DATES_URL.replace("/dates;", "/times;")}],
            "CHECK_INTERVAL_SEC": "120",
            "TIME_WINDOW": ("15:00", "09:00"),
            "WEEKDAYS": [7],
            "NTFY_TOPIC": "has spaces",
            "DAILY_REPORT_HOUR": 24,
            "ERROR_ALERT_THRESHOLD": 0,
            "DESKTOP_ALERTS": "yes",
            "EXTRA_CA_FILE": "certs/missing.pem",
            "SCHOOL_EMAIL": "study at taltech",
            "BOOKING_LANGUAGE": "English",
            "SCHOOL_EMAIL_SUBJECT": "New appointment {day}",
            "SCHOOL_EMAIL_BODY": "",
        }
        for key, value in cases.items():
            with self.subTest(key=key):
                with self.assertRaisesRegex(sw.SettingsError, key):
                    make_settings(**{key: value})

    def test_empty_office_url(self):
        with self.assertRaisesRegex(sw.SettingsError, "url is empty"):
            make_settings(OFFICES=[{"name": "Tallinn", "url": ""}])

    def test_time_window_is_normalised(self):
        self.assertEqual(make_settings(TIME_WINDOW=("9:00", "15:00")).time_window, ("09:00", "15:00"))

    def test_syntax_error(self):
        with self.assertRaisesRegex(sw.SettingsError, "syntax error"):
            sw.load_settings(self.write("CURRENT_APPOINTMENT = (\n"))

    def test_missing_file(self):
        with self.assertRaisesRegex(sw.SettingsError, "not found"):
            sw.load_settings(os.path.join(PROJECT_DIR, "no-such-settings.py"))

    def test_unknown_setting_is_reported(self):
        path = self.write('NTFY_TOPIC = "abc"\nNTFY_TOPICS = "typo"\nEXTRA_CA_FILE = None\n')
        with self.assertLogs("slot_watch", level="WARNING") as logs:
            sw.load_settings(path)
        self.assertIn("NTFY_TOPICS", logs.output[0])


class TestSsl(unittest.TestCase):
    def test_context_clears_partial_chain(self):
        ctx = sw.make_ssl_context(CA_FILE)
        self.assertFalse(ctx.verify_flags & getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0x80000))
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)

    def test_shipped_intermediate(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cafile=CA_FILE)
        (cert,) = ctx.get_ca_certs()
        subject = dict(pair[0] for pair in cert["subject"])
        issuer = dict(pair[0] for pair in cert["issuer"])
        self.assertEqual(subject["commonName"], "GoGetSSL RSA DV CA")
        self.assertEqual(issuer["commonName"], "USERTrust RSA Certification Authority")

    def test_unreadable_ca_file(self):
        handle, path = tempfile.mkstemp(suffix=".pem")
        with os.fdopen(handle, "w") as f:
            f.write("not a certificate\n")
        self.addCleanup(os.remove, path)
        with self.assertRaisesRegex(sw.SettingsError, "EXTRA_CA_FILE"):
            sw.make_ssl_context(path)


class TestCompatibility(unittest.TestCase):
    def test_python_310_syntax(self):
        for name in ("slot_watch.py", "settings.example.py", "tools/check_host.py", "tests/test_slot_watch.py"):
            with self.subTest(file=name):
                with open(os.path.join(PROJECT_DIR, name), encoding="utf-8") as f:
                    ast.parse(f.read(), filename=name, feature_version=(3, 10))


class FakeServers:
    """A fake Qmatic API and a fake ntfy server on 127.0.0.1."""

    def __init__(self):
        self.dates = []
        self.dates_status = 200
        self.times = {}
        self.requests = []
        self.messages = []
        site = self

        class QmaticHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                site.requests.append(self.path)
                if "/times;" in self.path:
                    day = self.path.split("/dates/")[1].split("/")[0]
                    self.reply(200, [{"date": day, "time": t} for t in site.times.get(day, [])])
                elif site.dates_status != 200:
                    self.reply(site.dates_status, {"error": "unavailable"})
                else:
                    self.reply(200, [{"date": day} for day in site.dates])

            def reply(self, status, data):
                body = json.dumps(data).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json;charset=UTF-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        class NtfyHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                site.messages.append(json.loads(self.rfile.read(length)))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        self.qmatic = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QmaticHandler)
        self.ntfy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), NtfyHandler)
        for server in (self.qmatic, self.ntfy):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def close(self):
        for server in (self.qmatic, self.ntfy):
            server.shutdown()
            server.server_close()


class TestEndToEnd(unittest.TestCase):
    """The scenario of section 5, over real HTTP with fake servers."""

    def test_scenario(self):
        site = FakeServers()
        self.addCleanup(site.close)
        settings = make_settings(
            OFFICES=[{"name": "Tallinn Tammsaare",
                      "url": f"http://127.0.0.1:{site.qmatic.server_port}{DATES_PATH}"}],
            NTFY_SERVER=f"http://127.0.0.1:{site.ntfy.server_port}",
        )
        watcher = sw.Watcher(settings, lambda url: sw.http_get(url, None, settings.user_agent),
                             notifier=sw.Ntfy(settings.ntfy_server, settings.ntfy_topic, settings.user_agent),
                             now=lambda: NOW, sleep=lambda seconds: None, min_interval=0, pause_range=(0, 0))
        site.times = {"2026-10-14": ["09:15", "10:15"]}

        def cycle(dates, status=200):
            site.dates, site.dates_status = dates, status
            return watcher.next_delay(watcher.run_cycle())

        cycle(["2026-11-19"])                              # 1: nothing earlier
        cycle(["2026-10-14", "2026-11-19"])                # 2: 14.10 appears
        cycle(["2026-11-19"])                              # 3: 14.10 is taken
        cycle(["2026-10-14", "2026-11-19"])                # 4: 14.10 comes back
        delays = [cycle([], 503) for _ in range(5)]        # 5 to 9: the site fails
        cycle(["2026-10-14", "2026-11-19"])                # 10: the site works again

        self.assertEqual([m["priority"] for m in site.messages], [3, 5, 5, 4, 3])
        started, first, second, failing, recovered = site.messages
        self.assertEqual(started["title"], "ppa-slot-watch started")
        self.assertEqual(first["title"], "Earlier slot, Tallinn Tammsaare, 14.10")
        self.assertIn("Wed 14.10.2026  09:15, 10:15", first["message"])
        self.assertEqual(second["title"], first["title"])
        self.assertIn("5 checks in a row failed. Last error: HTTP 503", failing["message"])
        self.assertEqual(recovered["title"], "Checks work again, Tallinn Tammsaare")
        base = f"http://127.0.0.1:{site.qmatic.server_port}/qmaticwebbooking/#/"
        calendar = f"{base}preselect/branch/{BRANCH}/services/{SERVICE}?lang=en_en"
        for message in site.messages:
            self.assertEqual(message["topic"], "test-topic")
            slot = message["title"].startswith("Earlier slot")
            self.assertEqual(message["click"], calendar if slot else base + "?lang=en_en")
            self.assertEqual("actions" in message, slot)
        labels = [action["label"] for action in first["actions"]]
        self.assertEqual(labels, ["Open calendar", "Email school"])
        self.assertTrue(first["actions"][1]["url"].startswith(
            "mailto:study@taltech.ee?subject=Earlier%20PPA%20appointment%3A%20Wed%2014.10.2026%2009%3A15&body="))
        self.assertEqual(delays, [240, 480, 900, 900, 900])
        times_requests = [path for path in site.requests if "/times;" in path]
        self.assertEqual(len(times_requests), 3)   # cycles 2, 4 and 10


if __name__ == "__main__":
    unittest.main()
