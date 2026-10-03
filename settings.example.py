# Settings of ppa-slot-watch.
#
# Copy this file to settings.py and edit settings.py:
#
#     cp settings.example.py settings.py
#
# settings.py is not committed to git, because it holds your ntfy topic.
# After a change, restart the bot. Check the settings with:
#
#     python3 slot_watch.py --check-once

# Your current appointment. Only days before this date are reported.
CURRENT_APPOINTMENT = "2026-10-27"

# Report days starting this many days after today. 1 means tomorrow at the
# earliest. 0 also reports today, but only times at least 60 minutes from now.
MIN_DAYS_AHEAD = 1

# The school sends its documents to the office after you email it the new
# appointment date. It must get the email on a working day (Monday to Friday)
# before SCHOOL_EMAIL_DEADLINE, and sends the documents SCHOOL_WORKDAYS working
# days later (0: the same day). Only days after that sending day are reported.
# BOOKING_MINUTES is the time you need after a notification to book the slot
# and send the email. Examples with "12:00", 0 and 30: a slot found on Saturday
# is reported from Tuesday on; one found on Friday at 11:00 from Monday on; one
# found on Friday at 11:45 from Tuesday on. SCHOOL_EMAIL_DEADLINE = None turns
# the school rule off.
SCHOOL_EMAIL_DEADLINE = "12:00"
SCHOOL_WORKDAYS = 0
BOOKING_MINUTES = 30

# The "Email school" button of a slot notification opens your mail app with an
# e-mail to this address, filled in with the slot. {date}, {time}, {office} and
# {current} are replaced; {time} is the earliest time of the day, so correct it
# if you book another one. Do not put your name or student number here, the
# text travels through ntfy; your mail signature adds them. None removes the button.
SCHOOL_EMAIL = "study@taltech.ee"
SCHOOL_EMAIL_SUBJECT = "Earlier PPA appointment: {date} {time}"
SCHOOL_EMAIL_BODY = (
    "Hello,\n\n"
    "My residence permit appointment at the PPA {office} service office was on {current}. "
    "I have found an earlier appointment on {date} at {time}. "
    "Could you please send the documents to the office for the new date today?\n\n"
    "Thank you."
)

# Offices to watch. "url" is the dates address the booking page uses for the
# residence permit service at that office; docs/02-finding-ids.md explains how
# to copy it from the browser. To watch another office, remove the # signs in
# front of its lines.
OFFICES = [
    {
        "name": "Tallinn Tammsaare",
        "url": "https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/"
               "89f89ac30f7f6329397e447102ce1ed13e5459eaa5a630c071d0577bdae6600a/dates;"
               "servicePublicId=b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40;"
               "customSlotLength=60",
    },
    # {
    #     "name": "Tartu",
    #     "url": "https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/"
    #            "7eddbbbfe3cacf5100f4fcf0c8c7b156ca80749142abefb3e7909873bd396011/dates;"
    #            "servicePublicId=b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40;"
    #            "customSlotLength=60",
    # },
    # {
    #     "name": "Parnu",
    #     "url": "https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/"
    #            "bdfdc72ede1f3a9aafa54ac48ddbdd0658ca07677d34b3e0665ba69baab406d8/dates;"
    #            "servicePublicId=b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40;"
    #            "customSlotLength=60",
    # },
    # {
    #     "name": "Johvi",
    #     "url": "https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/"
    #            "a109dfb325ff0fb78d217aa76de53a6722a572fac190f3e4f3ab6ca64c886ba7/dates;"
    #            "servicePublicId=b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40;"
    #            "customSlotLength=60",
    # },
    # {
    #     "name": "Narva",
    #     "url": "https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/"
    #            "9f9a45d6e00fbaa0191af2ba26bde6d4aac666f045d3ef99fa3c4cc06cd557a6/dates;"
    #            "servicePublicId=b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40;"
    #            "customSlotLength=60",
    # },
]

# Seconds between two checks. Values below 60 are raised to 60.
CHECK_INTERVAL_SEC = 120

# Only report times inside this window, both ends included. None reports all.
# Example: TIME_WINDOW = ("09:00", "15:00")
TIME_WINDOW = None

# Only report these weekdays: 0 Monday, 1 Tuesday, ..., 6 Sunday. None reports all.
# Example: WEEKDAYS = [0, 2, 4]
WEEKDAYS = None

# ntfy server and topic. Anyone who knows the topic can read the messages, so
# use a long random name, for example ppa-trp- followed by 12 random letters
# and digits, and subscribe to it in the ntfy app on the phone.
NTFY_SERVER = "https://ntfy.sh"
NTFY_TOPIC = "change-me"

# Hour (0 to 23) of the daily status message. None turns it off.
DAILY_REPORT_HOUR = 9

# Send an error notification after this many failed checks in a row.
ERROR_ALERT_THRESHOLD = 5

# Also show a desktop notification and play a sound (Linux, when available).
DESKTOP_ALERTS = True

# User-Agent header sent to the booking site.
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) ppa-slot-watch/1.0"

# Intermediate certificate the booking site does not send (docs/04-troubleshooting.md).
# A relative path is relative to the project directory. None turns it off.
EXTRA_CA_FILE = "certs/gogetssl-rsa-dv-ca.pem"
