# chrome_manager

Chrome Manager (Windows). Opens many Chrome profiles on claude.ai/new, detects the free-limit message, closes the window and reopens it
at the reset time. It does NOT press "Continue" -- for that use the Chrome extension in the folder `claude_background_continue`.

| File | What it does |
|---|---|
| `Chrome_Opener.bat` | Starts Chrome Manager (open profiles, watch for the limit message, reopen at reset time). |
| `Stop_All.bat` | Stops Chrome Manager and closes the Chrome windows. |
| `Chrome_Opener_Close_All.bat` | Closes all Chrome windows of this Chrome. |
| `Chrome_Opener_Shut_Down.py` (`Shout_Down.py` is an identical copy) | Stops Chrome Manager, closes Chrome, then shuts the PC down. |

So the PC does not hang with many windows open: a new window is opened only while CPU is at most 70%, RAM in use at most 80% and at least 2 GB of RAM is free, with at least 3 seconds between two windows; Chrome runs at "below normal" CPU priority. Open windows are never closed because of these limits, and they can still grow (a very long chat uses more RAM), so if the PC still struggles lower `MAX_CONCURRENT_PROFILES`. The numbers are the constants at the top of `Chrome_Opener.py` (`SAFE_CPU_PERCENT`, `SAFE_RAM_PERCENT`, `MIN_FREE_RAM_MB`, `LAUNCH_SPACING_SECONDS`, `LOWER_CHROME_PRIORITY`).

Version: `VERSION` in `Chrome_Opener.py`, history in `CHANGELOG.md`. Personal runtime files (`activity_log.txt`, `profile_state.json`) stay on your computer.

## Known limits (found in a code review, not fixed)

- A Chrome window you open yourself at the very moment a profile is being launched can be mistaken for that profile's window (the first new window is taken), and later be closed with it.
- A window opened by hand is matched to a profile by looking for the profile's display name anywhere in the window's text, page text included. A short name can match by accident.
- The reset time is read only from wording like "resets at / returns at / until H:MM AM/PM". Other wording (for example a weekly reset) falls back to the default wait.
- `Chrome_Opener_Shut_Down.py` shuts the PC down at once (`SHUTDOWN_DELAY_SECONDS = 0`) and only checks that no other Chrome is running, not other programs.
- The switches that keep covered windows awake (`KEEP_COVERED_WINDOWS_AWAKE`) work only when Chrome is started by this tool, so Chrome must not be open before.
