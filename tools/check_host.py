#!/usr/bin/env python3
"""Check the host assumptions of ppa-slot-watch (section 7.2 of the brief).

Run it on the MateBook, from a terminal inside the desktop session:

    python3 tools/check_host.py
    python3 tools/check_host.py --desktop-test --ntfy-topic YOUR_TOPIC

The default run reads settings, opens three TLS connections to
broneering.politsei.ee and sends one dates request. --desktop-test shows two
desktop notifications and plays two sounds. --ntfy-topic sends one test
message to that ntfy topic; the topic is not printed.

Every output line starts with a status (PASS, FAIL, WARN, INFO, SKIP) and the
ID of the assumption it checks. Paste the whole output into the chat.

Standard library only, Python 3.10 or later. The script also runs on Windows
and macOS, where the Linux-only checks are skipped.
"""

import argparse
import datetime
import email.utils
import getpass
import glob
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

HOST = "broneering.politsei.ee"

# Dates of the residence permit service at the Tammsaare office (brief, 2.3)
DATES_URL = (
    "https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches/"
    "89f89ac30f7f6329397e447102ce1ed13e5459eaa5a630c071d0577bdae6600a/dates;"
    "servicePublicId=b2fed5a24dde4d038dd866e85bcd0f417789116e4c69ae79dfd23cb95b1a7b40;"
    "customSlotLength=60"
)

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Referer": "https://broneering.politsei.ee/qmaticwebbooking/",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ppa-slot-watch/1.0 (host check)",
}

# The intermediate certificate the server does not send. Same certificate as
# certs/gogetssl-rsa-dv-ca.pem, embedded so that this file also works alone.
INTERMEDIATE_PEM = """\
-----BEGIN CERTIFICATE-----
MIIF1zCCA7+gAwIBAgIRAJOLsI5imHtPdfmMtqUEXJYwDQYJKoZIhvcNAQEMBQAw
gYgxCzAJBgNVBAYTAlVTMRMwEQYDVQQIEwpOZXcgSmVyc2V5MRQwEgYDVQQHEwtK
ZXJzZXkgQ2l0eTEeMBwGA1UEChMVVGhlIFVTRVJUUlVTVCBOZXR3b3JrMS4wLAYD
VQQDEyVVU0VSVHJ1c3QgUlNBIENlcnRpZmljYXRpb24gQXV0aG9yaXR5MB4XDTE4
MDkwNjAwMDAwMFoXDTI4MDkwNTIzNTk1OVowTDELMAkGA1UEBhMCTFYxDTALBgNV
BAcTBFJpZ2ExETAPBgNVBAoTCEdvR2V0U1NMMRswGQYDVQQDExJHb0dldFNTTCBS
U0EgRFYgQ0EwggEiMA0GCSqGSIb3DQEBAQUAA4IBDwAwggEKAoIBAQCfwF4hD6E1
kLglXs1n2fH5vMQukCGyyD4LqLsc3pSzeh8we7njU4TB85BH5YXqcfwiH1Sf78aB
hk1FgXoAZ3EQrF49We8mnTtTPFRnMwEHLJRpY9I/+peKeAZNL0MJG5zM+9gmcSpI
OTI6p7MPela72g0pBQjwcExYLqFFVsnroEPTRRlmfTBTRi9r7rYcXwIct2VUCRmj
jR1GX13op370YjYwgGv/TeYqUWkNiEjWNskFDEfxSc0YfoBwwKdPNfp6t/5+RsFn
lgQKstmFLQbbENsdUEpzWEvZUpDC4qPvRrxEKcF0uLoZhEnxhskwXSTC64BNtc+l
VEk7/g/be8svAgMBAAGjggF1MIIBcTAfBgNVHSMEGDAWgBRTeb9aqitKz1SA4dib
wJ3ysgNmyzAdBgNVHQ4EFgQU+ftQxItnu2dk/oMhpqnOP1WEk5kwDgYDVR0PAQH/
BAQDAgGGMBIGA1UdEwEB/wQIMAYBAf8CAQAwHQYDVR0lBBYwFAYIKwYBBQUHAwEG
CCsGAQUFBwMCMCIGA1UdIAQbMBkwDQYLKwYBBAGyMQECAkAwCAYGZ4EMAQIBMFAG
A1UdHwRJMEcwRaBDoEGGP2h0dHA6Ly9jcmwudXNlcnRydXN0LmNvbS9VU0VSVHJ1
c3RSU0FDZXJ0aWZpY2F0aW9uQXV0aG9yaXR5LmNybDB2BggrBgEFBQcBAQRqMGgw
PwYIKwYBBQUHMAKGM2h0dHA6Ly9jcnQudXNlcnRydXN0LmNvbS9VU0VSVHJ1c3RS
U0FBZGRUcnVzdENBLmNydDAlBggrBgEFBQcwAYYZaHR0cDovL29jc3AudXNlcnRy
dXN0LmNvbTANBgkqhkiG9w0BAQwFAAOCAgEAXXRDKHiA5DOhNKsztwayc8qtlK4q
Vt2XNdlzXn4RyZIsC9+SBi0Xd4vGDhFx6XX4N/fnxlUjdzNN/BYY1gS1xK66Uy3p
rw9qI8X12J4er9lNNhrsvOcjB8CT8FyvFu94j3Bs427uxcSukhYbERBAIN7MpWKl
VWxT3q8GIqiEYVKa/tfWAvnOMDDSKgRwMUtggr/IE77hekQm20p7e1BuJODf1Q7c
FPt7T74m3chg+qu0xheLI6HsUFuOxc7R5SQlkFvaVY5tmswfWpY+rwhyJW+FWNbT
uNXkxR4v5KOQPWrY100/QN68/j17paKuSXNcsr56snuB/Dx+MACLBdsF35HxPadx
78vkfQ37WcVmKZtHrHJQ/QUyjxdG8fezMsh0f+puUln/O+NlsFtipve8qYa9h/K5
yD0oZN93ChWve78XrV4vCpjO75Nk5B8O9CWQqGTHbhkgvjyb9v/B+sYJqB22/NLl
R4RPvbmqDJGeEI+4u6NJ5YiLIVVsX+dyfFP8zUbSsj6J34RyCYKBbQ4L+r7k8Srs
LY51WUFP292wkFDPSDmV7XsUNTDOZoQcBh2Fycf7xFfxeA+6ERx2d8MpPPND7yS2
1dkf+SY5SdpSbAKtYmbqb9q8cZUDEImNWJFUVHBLDOrnYhGwJudE3OBXRTxNhMDm
IXnjEeWrFvAZQhk=
-----END CERTIFICATE-----
"""
INTERMEDIATE_SHA256 = "43CAC31EF8E8BA1B4B16B8206E4C0A26C5BADB2FC3AA09E90170E41B66C2FD64"
REPO_PEM = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, "certs", "gogetssl-rsa-dv-ca.pem"
)

# OpenSSL flag values, for Python builds that do not expose the constants
PARTIAL_CHAIN = getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0x80000)
STRICT = getattr(ssl, "VERIFY_X509_STRICT", 0x20)

# logind settings that decide what closing the lid or idling does, with defaults
LOGIND_KEYS = (
    ("HandleLidSwitch", "suspend"),
    ("HandleLidSwitchExternalPower", "same as HandleLidSwitch"),
    ("HandleLidSwitchDocked", "ignore"),
    ("IdleAction", "ignore"),
)

SOUND_FILES = (
    "/usr/share/sounds/freedesktop/stereo/complete.oga",
    "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga",
    "/usr/share/sounds/freedesktop/stereo/bell.oga",
)
SOUND_PATTERNS = (
    "/usr/share/sounds/LinuxMint/stereo/*.og*",
    "/usr/share/sounds/freedesktop/stereo/*.oga",
)

IS_LINUX = sys.platform.startswith("linux")
statuses = []  # every reported status, for the summary line


def report(status, check_id, text):
    """Print one result line and remember its status."""
    statuses.append(status)
    print(f"{status:<4} {check_id:<3} {text}", flush=True)


def run(cmd, timeout=20):
    """Run a command and return (exit code, output). Exit code None: not installed."""
    if shutil.which(cmd[0]) is None:
        return None, f"{cmd[0]} not found"
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1, "timed out"
    return done.returncode, (done.stdout + done.stderr).strip()


def check_m1():
    """M1: operating system and Python version."""
    system = platform.platform()
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    system = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    python3 = shutil.which("python3")
    report("INFO", "M1", f"system: {system}")
    report("INFO", "M1", f"Python {platform.python_version()} ({sys.executable}), python3 on PATH: {python3}")
    if sys.version_info < (3, 10):
        report("FAIL", "M1", "Python 3.10 or later is needed")
    elif IS_LINUX and python3 != "/usr/bin/python3":
        report("WARN", "M1", "python3 is not /usr/bin/python3, the path in the systemd unit must change")
    else:
        report("PASS", "M1", "Python version is supported")


def check_m2():
    """M2: standard library modules the bot and its tests use."""
    missing = []
    for name in ("ssl", "urllib.request", "json", "logging.handlers", "argparse", "unittest", "http.server"):
        try:
            __import__(name)
        except ImportError as exc:
            missing.append(f"{name} ({exc})")
    if missing:
        report("FAIL", "M2", "missing modules: " + ", ".join(missing))
    else:
        report("PASS", "M2", "all needed standard library modules import")


def check_m3():
    """M3: OpenSSL version, default verify flags and CA locations."""
    flags = ssl.create_default_context().verify_flags
    paths = ssl.get_default_verify_paths()
    report("INFO", "M3", ssl.OPENSSL_VERSION)
    report("INFO", "M3", "create_default_context() flags: "
           f"PARTIAL_CHAIN={bool(flags & PARTIAL_CHAIN)}, STRICT={bool(flags & STRICT)}")
    report("INFO", "M3", f"default CA locations: cafile={paths.cafile}, capath={paths.capath}")


def load_intermediate():
    """Return (pem, source). The repository copy wins when it exists."""
    if os.path.exists(REPO_PEM):
        with open(REPO_PEM, encoding="ascii") as f:
            match = re.search(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", f.read(), re.S)
        if match:
            return match.group(0) + "\n", "certs/gogetssl-rsa-dv-ca.pem"
    return INTERMEDIATE_PEM, "the copy embedded in this script"


def make_context(extra_pem=None):
    """System CA store, PARTIAL_CHAIN cleared, plus an optional extra CA, like the bot."""
    ctx = ssl.create_default_context()
    ctx.verify_flags &= ~PARTIAL_CHAIN
    if extra_pem:
        ctx.load_verify_locations(cadata=extra_pem)
    return ctx


def handshake(ctx):
    """Open one TLS connection to the booking site and return the TLS version."""
    with socket.create_connection((HOST, 443), timeout=15) as raw:
        with ctx.wrap_socket(raw, server_hostname=HOST) as tls:
            return tls.version()


def check_m4():
    """M4: without the intermediate, verification fails (the server sends no chain)."""
    try:
        version = handshake(make_context())
    except ssl.SSLCertVerificationError as exc:
        report("PASS", "M4", "without the intermediate verification fails as expected: "
               f"{exc.verify_message} (code {exc.verify_code})")
        return
    except OSError as exc:
        report("FAIL", "M4", f"no TLS connection to {HOST}: {exc}")
        return
    if IS_LINUX:
        report("WARN", "M4", f"verification succeeded without the intermediate ({version}), "
               "the system store may already contain it")
    else:
        report("INFO", "M4", f"verification succeeded without the intermediate ({version}), "
               "normal on Windows and macOS")


def check_m5():
    """M5: with the shipped intermediate, verification ends at a system root."""
    pem, source = load_intermediate()
    fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest().upper()
    if fingerprint != INTERMEDIATE_SHA256:
        report("FAIL", "M5", f"{source} has an unexpected SHA-256 fingerprint {fingerprint}")
        return None
    ctx = make_context(pem)
    try:
        version = handshake(ctx)
    except ssl.SSLCertVerificationError as exc:
        report("FAIL", "M5", "verification fails even with the intermediate: "
               f"{exc.verify_message} (code {exc.verify_code})")
        return None
    except OSError as exc:
        report("FAIL", "M5", f"no TLS connection to {HOST}: {exc}")
        return None
    report("PASS", "M5", f"verification succeeds with {source} ({version}), "
           "the root comes from the system store")
    return ctx


def check_m6(ctx):
    """M6: one dates request with the bot's headers. Returns the server's Date header."""
    if ctx is None:
        report("SKIP", "M6", "needs a working TLS setup (M5)")
        return None
    request = urllib.request.Request(DATES_URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=20, context=ctx) as response:
            status, server_date = response.status, response.headers.get("Date")
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        report("FAIL", "M6", f"the dates request was answered with HTTP {exc.code}")
        return None
    except (urllib.error.URLError, OSError) as exc:
        report("FAIL", "M6", f"the dates request failed: {exc}")
        return None
    try:
        dates = sorted(item["date"] for item in json.loads(body))
    except (ValueError, TypeError, KeyError):
        report("FAIL", "M6", f"unexpected response: {body[:200]!r}")
        return server_date
    if dates:
        report("PASS", "M6", f"HTTP {status}, {len(dates)} dates, earliest {dates[0]}, "
               f"latest {dates[-1]} (compare with the site)")
    else:
        report("WARN", "M6", f"HTTP {status}, but the list is empty")
    return server_date


def check_m7(server_date):
    """M7: time zone and clock."""
    now = datetime.datetime.now().astimezone()
    report("INFO", "M7", f"local time {now:%Y-%m-%d %H:%M:%S} {now.tzname()} (UTC{now:%z})")
    if IS_LINUX:
        code, zone = run(["timedatectl", "show", "-p", "Timezone", "--value"])
        if code == 0:
            report("PASS" if zone == "Europe/Tallinn" else "WARN", "M7",
                   f"time zone {zone} (expected Europe/Tallinn)")
        else:
            report("WARN", "M7", f"timedatectl: {zone}")
        code, synced = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
        if code == 0:
            report("PASS" if synced == "yes" else "WARN", "M7", f"clock synchronised by NTP: {synced}")
    if server_date:
        server = email.utils.parsedate_to_datetime(server_date)
        skew = (datetime.datetime.now(datetime.timezone.utc) - server).total_seconds()
        report("PASS" if abs(skew) < 30 else "WARN", "M7",
               f"local clock differs from the server by {skew:+.0f} s")


def check_m8():
    """M8: systemd user manager, and a sleep inhibitor without a password."""
    if not IS_LINUX:
        report("SKIP", "M8", "Linux only")
        return
    for tool in ("systemctl", "systemd-inhibit", "systemd-run", "loginctl"):
        path = shutil.which(tool)
        report("PASS" if path else "FAIL", "M8", f"{tool}: {path or 'not found'}")
    code, state = run(["systemctl", "--user", "is-system-running"])
    report("PASS" if state in ("running", "degraded") else "WARN", "M8",
           f"systemd user manager state: {state}")
    code, out = run(["systemd-inhibit", "--what=sleep", "--who=ppa-slot-watch-check",
                     "--why=host check", "true"])
    if code == 0:
        report("PASS", "M8", "a sleep inhibitor can be taken without a password")
    else:
        report("FAIL", "M8", f"systemd-inhibit failed (exit {code}): {out[:200]}")


def check_m9():
    """M9: settings that decide whether the machine sleeps (read only)."""
    if not IS_LINUX:
        report("SKIP", "M9", "Linux only")
        return
    code, text = run(["systemd-analyze", "cat-config", "systemd/logind.conf"])
    if code != 0:
        try:
            with open("/etc/systemd/logind.conf", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = ""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if "=" in line and not line.startswith(("#", ";", "[")):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    for key, default in LOGIND_KEYS:
        report("INFO", "M9", f"logind {key}={values.get(key, default + ' (default)')}")
    code, out = run(["systemd-inhibit", "--list", "--no-pager"])
    for line in out.splitlines():
        if re.search(r"handle-lid-switch|sleep|idle", line):
            report("INFO", "M9", "inhibitor: " + " ".join(line.split()))
    code, out = run(["xfconf-query", "-c", "xfce4-power-manager", "-l", "-v"])
    if code is None:
        report("INFO", "M9", "xfconf-query not found, not an XFCE session")
    elif code != 0:
        report("WARN", "M9", f"xfconf-query failed, run this inside the desktop session: {out[:150]}")
    else:
        lines = [l for l in out.splitlines()
                 if re.search(r"lid|inactivity|sleep|suspend|hibernate|dpms|lock", l)]
        for line in lines:
            report("INFO", "M9", "xfce " + " ".join(line.split()))
        if not lines:
            report("INFO", "M9", "xfce power manager: no lid or inactivity settings stored, defaults apply")
    report("INFO", "M9", "the real test is a long run: leave the bot running and look for gaps in its log")


def find_sound():
    """Return a sound file for paplay, or None."""
    for path in SOUND_FILES:
        if os.path.exists(path):
            return path
    for pattern in SOUND_PATTERNS:
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return None


def check_m10(desktop_test):
    """M10: desktop notification and sound, also from the service environment."""
    if not IS_LINUX:
        report("SKIP", "M10", "Linux only")
        return
    notify, paplay, sound = shutil.which("notify-send"), shutil.which("paplay"), find_sound()
    report("PASS" if notify else "WARN", "M10", f"notify-send: {notify or 'not found'}")
    report("PASS" if paplay else "WARN", "M10", f"paplay: {paplay or 'not found'}")
    report("INFO", "M10", f"sound file: {sound or 'none found'}")
    if not desktop_test:
        report("SKIP", "M10", "run with --desktop-test to show a notification and play a sound")
        return
    ways = [("the terminal", [])]
    systemd_run = shutil.which("systemd-run")
    if systemd_run:
        # A transient user service has the same environment as the bot's service
        ways.append(("a user service", [systemd_run, "--user", "--wait", "--quiet", "--collect"]))
    for label, prefix in ways:
        if notify:
            code, out = run(prefix + [notify, "ppa-slot-watch check", f"Desktop notification test from {label}"])
            report("PASS" if code == 0 else "FAIL", "M10", f"notify-send from {label}: exit {code} {out[:150]}".rstrip())
        if paplay and sound:
            code, out = run(prefix + [paplay, sound])
            report("PASS" if code == 0 else "FAIL", "M10", f"paplay from {label}: exit {code} {out[:150]}".rstrip())
    report("INFO", "M10", f"expected {len(ways)} notifications and {len(ways)} sounds, "
           "say in the chat what you saw and heard")


def check_m11(topic, server):
    """M11: one ntfy test message, published as JSON like the bot does."""
    if not topic:
        report("SKIP", "M11", "run with --ntfy-topic to send a test message")
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
        report("FAIL", "M11", "not a valid ntfy topic name: use 1 to 64 letters, digits, - or _ "
               "(replace a placeholder such as <topic> with your own topic)")
        return
    body = json.dumps({
        "topic": topic,
        "title": "ppa-slot-watch check",
        "message": "Test message from tools/check_host.py. Non-ASCII text: Jõhvi, Pärnu.",
        "priority": 3,
    }).encode("utf-8")
    request = urllib.request.Request(
        server.rstrip("/") + "/", data=body, method="POST",
        headers={"Content-Type": "application/json", "User-Agent": HEADERS["User-Agent"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            report("PASS", "M11", f"{server} accepted the message (HTTP {response.status}), "
                   "check that it arrived on the phone")
    except urllib.error.HTTPError as exc:
        report("FAIL", "M11", f"{server} answered HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        report("FAIL", "M11", f"could not reach {server}: {exc}")


def check_m12():
    """M12: linger, git and memory, information for later steps."""
    if not IS_LINUX:
        report("SKIP", "M12", "Linux only")
        return
    user = os.environ.get("USER") or getpass.getuser()
    code, linger = run(["loginctl", "show-user", user, "-p", "Linger", "--value"])
    report("INFO", "M12", f"linger: {linger} (needed only to run without a login session)")
    report("INFO", "M12", f"git: {shutil.which('git') or 'not found'}")
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            kib = int(f.readline().split()[1])
        report("INFO", "M12", f"memory: {kib / 1024 / 1024:.1f} GiB")
    except (OSError, ValueError, IndexError):
        pass


def safe(check_id, check, *args):
    """Run one check; a crash is reported and the other checks still run."""
    try:
        return check(*args)
    except Exception as exc:
        report("FAIL", check_id, f"the check crashed: {exc!r}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Check the host assumptions of ppa-slot-watch.")
    parser.add_argument("--desktop-test", action="store_true",
                        help="show a desktop notification and play a sound")
    parser.add_argument("--ntfy-topic", help="send one test message to this ntfy topic")
    parser.add_argument("--ntfy-server", default="https://ntfy.sh",
                        help="ntfy server (default: %(default)s)")
    args = parser.parse_args()

    print(f"ppa-slot-watch host check, {datetime.datetime.now():%Y-%m-%d %H:%M}")
    safe("M1", check_m1)
    safe("M2", check_m2)
    safe("M3", check_m3)
    safe("M4", check_m4)
    ctx = safe("M5", check_m5)
    server_date = safe("M6", check_m6, ctx)
    safe("M7", check_m7, server_date)
    safe("M8", check_m8)
    safe("M9", check_m9)
    safe("M10", check_m10, args.desktop_test)
    safe("M11", check_m11, args.ntfy_topic, args.ntfy_server)
    safe("M12", check_m12)

    counts = {s: statuses.count(s) for s in ("PASS", "FAIL", "WARN", "INFO", "SKIP")}
    print("summary: " + ", ".join(f"{n} {s}" for s, n in counts.items()))
    print("Paste the whole output into the chat.")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
