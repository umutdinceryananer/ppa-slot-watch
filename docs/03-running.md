# Running

## In a terminal

```bash
cd ~/ppa-slot-watch
systemd-inhibit --what=sleep python3 slot_watch.py
```

`systemd-inhibit` keeps the machine from sleeping while the bot runs. Ctrl+C stops the bot. It logs one line per check to the terminal and to `slot_watch.log` in the project directory (1 MB, 2 older files kept).

## As a systemd user service

The service starts the bot at login, restarts it after a crash and keeps the machine from sleeping. The unit file expects the project in `~/ppa-slot-watch`; for another location, change the two paths in the file.

```bash
mkdir -p ~/.config/systemd/user
cp ~/ppa-slot-watch/systemd/ppa-slot-watch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ppa-slot-watch
```

| Command | Purpose |
|---|---|
| `systemctl --user status ppa-slot-watch` | State and the last log lines |
| `journalctl --user -u ppa-slot-watch -f` | Follow the log |
| `systemctl --user restart ppa-slot-watch` | Restart, for example after changing `settings.py` |
| `systemctl --user disable --now ppa-slot-watch` | Stop and remove from the autostart |

To keep the service running when nobody is logged in:

```bash
loginctl enable-linger $USER
```

After 5 starts within an hour, systemd stops restarting the service, so that a persistent error does not send a message every minute. Fix the cause, then run `systemctl --user restart ppa-slot-watch`.

## Sleep, lid and power

- `systemd-inhibit --what=sleep` blocks suspend requests, for example from the idle timer, while the bot runs.
- It does not decide what closing the lid does. To keep the machine running with the lid closed, set the lid action to "Switch off display" in the XFCE Power Manager, both on battery and plugged in, and check `HandleLidSwitch` in `/etc/systemd/logind.conf`.
- Keep the machine plugged in; the bot runs for days.
- `tools/check_host.py` prints the current lid and idle settings (M9).

## When the job is done

After booking an earlier appointment, set `CURRENT_APPOINTMENT` to the new date and restart the bot, or stop it:

```bash
systemctl --user disable --now ppa-slot-watch
```
